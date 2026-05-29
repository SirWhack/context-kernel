"""Ingester — sole graph writer. See ARCHITECTURE.md §2.2, invariant 1."""

import hashlib
import logging
import struct
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from context_kernel.graph.protocol import EmbeddedChunk, Entity, KnowledgeStore, Relationship, Summary
from context_kernel.ingester.blobs import write_embedding, write_summary
from context_kernel.change_detection import walk_source_files
from context_kernel.ingester.entity_resolver import (
    CODE_EXT, ExtractedEntity, ExtractedRelationship, resolve as resolve_entities,
)
from context_kernel.ingester.errors import IngestionError
from context_kernel.ingester.handlers import (
    ChunkHandler,
    MarkdownHandler,
    PythonHandler,
    RawEntity,
    RawRelationship,
    StructuredHandler,
    TypeScriptHandler,
)
from context_kernel.ingester.summarizer import Summarizer
from context_kernel.types import GraphCommit, Sha256, ScopePath

if TYPE_CHECKING:
    from context_kernel.config_store import IngesterConfig
    from context_kernel.ingester.embedder import Embedder
    from context_kernel.types import LLMMetrics

__all__ = ["IngestionError", "ingest"]

log = logging.getLogger(__name__)

_STRUCTURED: list[StructuredHandler] = [PythonHandler(), TypeScriptHandler()]
_CHUNK: list[ChunkHandler] = [MarkdownHandler()]

# Entities embedded per /embeddings round-trip in Phase 3.
_EMBED_BATCH = 96


def _embed_many(embedder: "Embedder", texts: list[str], *, mode: str = "passage") -> list[bytes]:
    """Embed many texts in one call when the embedder supports it, else fall back."""
    batch_fn = getattr(embedder, "embed_batch", None)
    if batch_fn is not None:
        return batch_fn(texts, mode=mode)
    return [embedder.embed(t, mode=mode) for t in texts]


_CHARS_PER_TOKEN = 4
_KIND_WEIGHT = {"module": 3, "class": 2, "function": 1}


def _build_code_context(code_entities, relationships, budget_tokens: int) -> str:
    """ADR-0016 §1: a centrality-ranked, token-capped list of known code entities so the
    doc extractor can reference real identifiers instead of inventing synonyms."""
    if not code_entities:
        return ""
    degree: Counter = Counter()
    for r in relationships:
        degree[r.source_name] += 1
        degree[r.target_name] += 1
    ranked = sorted(
        code_entities,
        key=lambda e: degree.get(e.name, 0) * 2 + _KIND_WEIGHT.get(e.kind, 0),
        reverse=True,
    )
    budget = budget_tokens * _CHARS_PER_TOKEN
    lines: list[str] = []
    used = 0
    seen: set[tuple[str, str]] = set()
    for e in ranked:
        key = (e.name, e.source_file)
        if key in seen:
            continue
        seen.add(key)
        line = f"- {e.name} ({e.kind}, {e.source_file})"
        if used + len(line) > budget:
            break
        lines.append(line)
        used += len(line) + 1
    return "## Known code entities\n" + "\n".join(lines) if lines else ""


def _build_vocab_context(sources_root: Path, budget_tokens: int) -> str:
    """ADR-0016 §2: canonical vocabulary from CONTEXT.md so the extractor uses settled terms."""
    ctx_path = sources_root / "CONTEXT.md"
    if not ctx_path.exists():
        return ""
    try:
        text = ctx_path.read_text(encoding="utf-8")
    except Exception:
        return ""
    budget = budget_tokens * _CHARS_PER_TOKEN
    out: list[str] = []
    used = 0
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith(("- ", "* ", "#")) or "**" in s or " — " in s or (": " in s and len(s) < 200):
            if used + len(line) > budget:
                break
            out.append(line)
            used += len(line) + 1
    return "## Canonical vocabulary\n" + "\n".join(out) if out else ""


@dataclass
class _FileResult:
    """Entities and relationships extracted from a single file."""
    entities: list[Entity] = field(default_factory=list)
    relationships: list[Relationship] = field(default_factory=list)
    rel_path: str = ""
    scope_key: str = ""


def _derive_entity_id(name: str, kind: str, source_file: str, project: str | None = None) -> str:
    if project:
        return hashlib.sha256(f"{project}:{name}:{kind}:{source_file}".encode()).hexdigest()
    return hashlib.sha256(f"{name}:{kind}:{source_file}".encode()).hexdigest()


def _resolve_raw_entities(
    raw_entities: list[RawEntity],
    raw_relationships: list[RawRelationship],
    source_file: str,
    project: str | None = None,
) -> tuple[list[Entity], list[Relationship]]:
    name_to_id: dict[str, str] = {}
    entities: list[Entity] = []

    for raw in raw_entities:
        eid = _derive_entity_id(raw.name, raw.kind, source_file, project)
        name_to_id[raw.name] = eid
        entities.append(Entity(id=eid, name=raw.name, kind=raw.kind, description=raw.description))

    relationships: list[Relationship] = []
    for raw_rel in raw_relationships:
        src_id = name_to_id.get(raw_rel.source_name)
        if src_id is None:
            src_id = _derive_entity_id(raw_rel.source_name, "unknown", source_file, project)
        tgt_id = name_to_id.get(raw_rel.target_name)
        if tgt_id is None:
            tgt_id = _derive_entity_id(raw_rel.target_name, "unknown", raw_rel.target_name, project)
        relationships.append(Relationship(
            source_id=src_id,
            target_id=tgt_id,
            kind=raw_rel.kind,
            description=raw_rel.description,
        ))

    return entities, relationships


def _generate_scope_summary(scope: ScopePath, entities: list[Entity]) -> str:
    n_modules = sum(1 for e in entities if e.kind == "module")
    n_classes = sum(1 for e in entities if e.kind == "class")
    n_protocols = sum(1 for e in entities if e.kind == "class" and "Protocol" in e.description)
    n_functions = sum(1 for e in entities if e.kind == "function")

    class_detail = f"{n_classes} classes"
    if n_protocols:
        class_detail = f"{n_classes} classes ({n_protocols} Protocol)"

    public_names = [
        e.name for e in entities
        if e.kind in {"class", "function"} and "private" not in e.description.lower().split("visibility:")[-1][:20]
        and not e.name.startswith("_")
    ]
    interfaces = ", ".join(public_names[:5]) if public_names else "(none)"

    return (
        f"Scope {scope}/: {n_modules} modules, {class_detail}, {n_functions} functions. "
        f"Key interfaces: {interfaces}."
    )


def _compute_graph_commit(all_files: list[Path], sources_root: Path) -> GraphCommit:
    """Hash (relative_path, sha256(contents)) pairs sorted by path, per ADR-0008."""
    h = hashlib.sha256()
    for f in sorted(all_files):
        rel = str(f.relative_to(sources_root))
        h.update(rel.encode())
        h.update(hashlib.sha256(f.read_bytes()).hexdigest().encode())
    return GraphCommit(h.hexdigest())


def ingest(
    store: KnowledgeStore,
    sources_root: Path,
    blob_root: Path,
    config: "IngesterConfig",
    *,
    project_name: str | None = None,
    summarizer: Summarizer | None = None,
    embedder: "Embedder | None" = None,
    metrics: "LLMMetrics | None" = None,
) -> GraphCommit:
    """Detect changed sources, extract entities, upsert into Graph. Return the new GraphCommit."""
    t0 = time.monotonic()
    sources_root = sources_root.resolve()
    blob_root = blob_root.resolve()
    n_parallel = config.parallel_requests

    all_files = walk_source_files(sources_root)
    if not all_files:
        log.info("No source files found under %s", sources_root)
        commit = GraphCommit(hashlib.sha256(b"empty").hexdigest())
        store.upsert(commit, [], [], [])
        return commit

    all_chunks: list[EmbeddedChunk] = []

    def _scope_of(source_file: str) -> str:
        parent = str(Path(source_file).parent)
        return str(Path(project_name) / parent) if project_name else parent

    # Partition files by handler type: structured (instant) vs chunk (LLM-dependent)
    structured_files: list[tuple[Path, str, StructuredHandler]] = []
    chunk_files: list[tuple[Path, str, ChunkHandler]] = []
    for file_path in all_files:
        rel_path = str(file_path.relative_to(sources_root))
        handler = next((h for h in _STRUCTURED if h.supports(file_path)), None)
        if handler:
            structured_files.append((file_path, rel_path, handler))
            continue
        chandler = next((h for h in _CHUNK if h.supports(file_path)), None)
        if chandler:
            chunk_files.append((file_path, rel_path, chandler))

    # Phases 1+2 now COLLECT raw extractions (with provenance); resolution is global (ADR-0017).
    raw_entities: list[ExtractedEntity] = []
    raw_relationships: list[ExtractedRelationship] = []

    # Phase 1: structured files (instant — no LLM)
    t_phase1 = time.monotonic()
    for file_path, rel_path, handler in structured_files:
        re_, rr_ = handler.extract(file_path)
        raw_entities += [ExtractedEntity(e.name, e.kind, rel_path, e.description) for e in re_]
        raw_relationships += [ExtractedRelationship(r.source_name, r.target_name, r.kind, rel_path, r.description) for r in rr_]
    phase1_ms = int((time.monotonic() - t_phase1) * 1000)

    # ADR-0016: build the run-constant extraction context (known code entities + vocabulary)
    # from Phase-1 output. Constant across all chunk calls in this run → prompt-cache friendly.
    run_context = ""
    if config.contextual_extraction and summarizer is not None:
        code_ents = [e for e in raw_entities if e.source_file.endswith(CODE_EXT)]
        parts = [p for p in (
            _build_code_context(code_ents, raw_relationships, config.code_context_tokens),
            _build_vocab_context(sources_root, 1200),
        ) if p]
        run_context = "\n\n".join(parts)

    def _chunk_context(rel_path: str) -> str:
        if not run_context:
            return ""
        return f"{run_context}\n\n## Source\nFile: {rel_path}"

    # Phase 2: chunk files (LLM-dependent — parallelized at chunk level)
    t_phase2 = time.monotonic()
    chunk_items: list[tuple[str, str]] = []  # (chunk_text, rel_path)
    for file_path, rel_path, handler in chunk_files:
        for chunk_text in handler.chunks(file_path):
            chunk_items.append((chunk_text, rel_path))

    def _process_chunk(item: tuple[str, str]):
        chunk_text, rel_path = item
        re_, rr_ = summarizer.summarize(chunk_text, context=_chunk_context(rel_path))
        ents = [ExtractedEntity(e.name, e.kind, rel_path, e.description) for e in re_]
        rels = [ExtractedRelationship(r.source_name, r.target_name, r.kind, rel_path, r.description) for r in rr_]
        return ents, rels

    if chunk_items and summarizer is not None:
        n_workers = min(n_parallel, len(chunk_items))
        with ThreadPoolExecutor(max_workers=n_workers) as pool:
            futures = {pool.submit(_process_chunk, item): item for item in chunk_items}
            for future in as_completed(futures):
                try:
                    ents, rels = future.result()
                    raw_entities += ents
                    raw_relationships += rels
                except Exception:
                    log.warning("Failed to process chunk from %s, skipping", futures[future][1], exc_info=True)
    elif chunk_files and summarizer is None:
        for _, rel_path, _h in chunk_files:
            log.warning("No summarizer configured, skipping %s", rel_path)
    phase2_ms = int((time.monotonic() - t_phase2) * 1000)

    # Phase 2.5: embed raw entity descriptions BEFORE resolution — embeddings are the
    # collision guard's second signal (ADR-0017) and become the canonical node embeddings.
    t_phase3 = time.monotonic()
    if embedder is not None and raw_entities:
        def _embed_raw_batch(batch: list[ExtractedEntity]) -> list[bytes | None]:
            try:
                return _embed_many(embedder, [e.description for e in batch], mode="passage")
            except Exception:
                log.warning("Failed to embed entity batch of %d, skipping", len(batch), exc_info=True)
                return [None] * len(batch)

        batches = [raw_entities[i:i + _EMBED_BATCH] for i in range(0, len(raw_entities), _EMBED_BATCH)]
        with ThreadPoolExecutor(max_workers=min(n_parallel, len(batches))) as pool:
            for batch, embs in zip(batches, pool.map(_embed_raw_batch, batches)):
                for e, emb in zip(batch, embs):
                    if emb:
                        e.embedding = struct.unpack(f"{len(emb) // 4}f", emb)

    # Phase 3: resolve raw extractions into canonical, code-anchored nodes (ADR-0017).
    canonical, resolved_rels, rstats = resolve_entities(
        raw_entities, raw_relationships, project=project_name,
    )
    log.info("entity_resolution", extra=rstats)

    all_entities: list[Entity] = []
    all_relationships = [
        Relationship(source_id=r.source_id, target_id=r.target_id, kind=r.kind, description=r.description)
        for r in resolved_rels
    ]
    scope_entities: dict[str, list[Entity]] = defaultdict(list)
    seen_in_scope: dict[str, set[str]] = defaultdict(set)
    for c in canonical:
        ent = Entity(
            id=c.id, name=c.name, kind=c.kind, description=c.description,
            aliases=tuple(c.aliases), sources=tuple(c.sources), kinds=tuple(c.kinds),
        )
        all_entities.append(ent)
        if c.embedding is not None:
            emb_bytes = struct.pack(f"{len(c.embedding)}f", *c.embedding)
            write_embedding(blob_root, emb_bytes)
            code_src = next((s for s in c.sources if s.endswith(CODE_EXT)), (c.sources[0] if c.sources else ""))
            all_chunks.append(EmbeddedChunk(
                id=c.id, embedding=emb_bytes, chunk_text=c.description,
                source_path=code_src, kind="entity", scope=ScopePath(Path(_scope_of(code_src))),
            ))
        for src in (c.sources or [""]):
            sk = _scope_of(src)
            if ent.id not in seen_in_scope[sk]:
                seen_in_scope[sk].add(ent.id)
                scope_entities[sk].append(ent)
    phase3_ms = int((time.monotonic() - t_phase3) * 1000)

    # Phase 4: Generate per-scope summaries (ADR-0007: LLM second pass when available, parallelized)
    t_phase4 = time.monotonic()
    all_summaries: list[Summary] = []

    def _process_scope(scope_key: str, entities: list[Entity]) -> tuple[Summary, EmbeddedChunk | None]:
        scope = ScopePath(Path(scope_key))
        summary_text = None

        if summarizer is not None:
            descriptions = [e.description for e in entities if e.description]
            if descriptions:
                summary_text = summarizer.summarize_scope(str(scope), descriptions)

        if summary_text is None:
            summary_text = _generate_scope_summary(scope, entities)

        digest = write_summary(blob_root, summary_text)
        summary = Summary(scope=scope, digest=digest, markdown=summary_text)

        chunk = None
        if embedder is not None:
            try:
                emb = embedder.embed(summary_text, mode="passage")
                write_embedding(blob_root, emb)
                chunk = EmbeddedChunk(
                    id=digest,
                    embedding=emb,
                    chunk_text=summary_text,
                    source_path=scope_key,
                    kind="summary",
                    scope=scope,
                )
            except Exception:
                log.warning("Failed to embed summary for scope %s, skipping", scope_key)

        return summary, chunk

    if scope_entities:
        n_workers = min(n_parallel, len(scope_entities))
        with ThreadPoolExecutor(max_workers=n_workers) as pool:
            futures = {
                pool.submit(_process_scope, sk, ents): sk
                for sk, ents in scope_entities.items()
            }
            for future in as_completed(futures):
                try:
                    summary, chunk = future.result()
                    all_summaries.append(summary)
                    if chunk is not None:
                        all_chunks.append(chunk)
                except Exception:
                    sk = futures[future]
                    log.warning("Failed to process scope %s, skipping", sk, exc_info=True)
    phase4_ms = int((time.monotonic() - t_phase4) * 1000)

    commit = _compute_graph_commit(all_files, sources_root)
    typed_scope_entities = {ScopePath(Path(k)): v for k, v in scope_entities.items()}
    store.upsert(
        commit, all_entities, all_relationships, all_summaries,
        all_chunks or None,
        typed_scope_entities or None,
    )

    elapsed = int((time.monotonic() - t0) * 1000)
    extra: dict[str, object] = {
        "files_processed": len(all_files),
        "entities": len(all_entities),
        "relationships": len(all_relationships),
        "graph_commit": str(commit),
        "duration_ms": elapsed,
        "phase_structured_ms": phase1_ms,
        "phase_chunks_ms": phase2_ms,
        "phase_embed_entities_ms": phase3_ms,
        "phase_scope_summaries_ms": phase4_ms,
    }
    if metrics is not None:
        extra.update({
            "llm_chat_calls": metrics.chat_calls,
            "llm_chat_input_tokens": metrics.chat_input_tokens,
            "llm_chat_output_tokens": metrics.chat_output_tokens,
            "llm_chat_cache_hit_tokens": metrics.chat_cache_hit_tokens,
            "llm_chat_cache_miss_tokens": metrics.chat_cache_miss_tokens,
            "llm_prompt_cache_hit_rate": round(metrics.prompt_cache_hit_rate, 3),
            "llm_embed_calls": metrics.embed_calls,
            "llm_embed_input_tokens": metrics.embed_input_tokens,
            "llm_total_elapsed_ms": metrics.total_elapsed_ms,
            "llm_cache_hits": metrics.cache_hits,
            "llm_cache_misses": metrics.cache_misses,
            "llm_estimated_cost_usd": round(metrics.estimated_cost_usd(
                chat_input_rate=0.14, chat_output_rate=0.28,
                chat_cache_hit_rate=0.0028, embed_input_rate=0.012,
            ), 6),
        })
    log.info("ingested", extra=extra)

    return commit
