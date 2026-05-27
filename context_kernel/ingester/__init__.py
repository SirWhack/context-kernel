"""Ingester — sole graph writer. See ARCHITECTURE.md §2.2, invariant 1."""

import hashlib
import logging
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from context_kernel.graph.protocol import EmbeddedChunk, Entity, KnowledgeStore, Relationship, Summary
from context_kernel.ingester.blobs import write_embedding, write_summary
from context_kernel.change_detection import walk_source_files
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

    all_entities: list[Entity] = []
    all_relationships: list[Relationship] = []
    all_chunks: list[EmbeddedChunk] = []
    scope_entities: dict[str, list[Entity]] = defaultdict(list)
    entity_source: dict[str, str] = {}  # entity_id → rel_path
    entity_scope: dict[str, str] = {}  # entity_id → scope_key

    # Partition files by handler type: structured (instant) vs chunk (LLM-dependent)
    structured_files: list[tuple[Path, str, str, StructuredHandler]] = []
    chunk_files: list[tuple[Path, str, str, ChunkHandler]] = []

    for file_path in all_files:
        rel_path = str(file_path.relative_to(sources_root))
        scope_key = str(file_path.parent.relative_to(sources_root))
        if project_name:
            scope_key = str(Path(project_name) / scope_key)

        matched = False
        for handler in _STRUCTURED:
            if handler.supports(file_path):
                structured_files.append((file_path, rel_path, scope_key, handler))
                matched = True
                break
        if matched:
            continue
        for handler in _CHUNK:
            if handler.supports(file_path):
                chunk_files.append((file_path, rel_path, scope_key, handler))
                break

    # Phase 1: Process structured files (instant — no LLM, no parallelism needed)
    t_phase1 = time.monotonic()
    for file_path, rel_path, scope_key, handler in structured_files:
        raw_ents, raw_rels = handler.extract(file_path)
        if raw_ents:
            entities, relationships = _resolve_raw_entities(raw_ents, raw_rels, rel_path, project_name)
            all_entities.extend(entities)
            all_relationships.extend(relationships)
            scope_entities[scope_key].extend(entities)
            for entity in entities:
                entity_source[entity.id] = rel_path
                entity_scope[entity.id] = scope_key
    phase1_ms = int((time.monotonic() - t_phase1) * 1000)

    # Phase 2: Process chunk files (LLM-dependent — parallelized at chunk level)
    t_phase2 = time.monotonic()

    # Flatten all chunks across files into individual work items
    _ChunkItem = tuple[str, str, str]  # (chunk_text, rel_path, scope_key)
    chunk_items: list[_ChunkItem] = []
    for file_path, rel_path, scope_key, handler in chunk_files:
        for chunk_text in handler.chunks(file_path):
            chunk_items.append((chunk_text, rel_path, scope_key))

    def _process_chunk(item: _ChunkItem) -> _FileResult:
        chunk_text, rel_path, scope_key = item
        result = _FileResult(rel_path=rel_path, scope_key=scope_key)
        raw_ents, raw_rels = summarizer.summarize(chunk_text)
        entities, relationships = _resolve_raw_entities(raw_ents, raw_rels, rel_path, project_name)
        result.entities.extend(entities)
        result.relationships.extend(relationships)

        if embedder is not None:
            embedding = embedder.embed(chunk_text)
            write_embedding(blob_root, embedding)
        return result

    if chunk_items and summarizer is not None:
        n_workers = min(n_parallel, len(chunk_items))
        with ThreadPoolExecutor(max_workers=n_workers) as pool:
            futures = {
                pool.submit(_process_chunk, item): item
                for item in chunk_items
            }
            for future in as_completed(futures):
                item = futures[future]
                try:
                    result = future.result()
                    all_entities.extend(result.entities)
                    all_relationships.extend(result.relationships)
                    scope_entities[result.scope_key].extend(result.entities)
                    for entity in result.entities:
                        entity_source[entity.id] = result.rel_path
                        entity_scope[entity.id] = result.scope_key
                except Exception:
                    log.warning("Failed to process chunk from %s, skipping", item[1], exc_info=True)
    elif chunk_files:
        for file_path, rel_path, scope_key, handler in chunk_files:
            log.warning("No summarizer configured, skipping %s", rel_path)
    phase2_ms = int((time.monotonic() - t_phase2) * 1000)

    # Phase 3: Embed entity descriptions (parallelized)
    t_phase3 = time.monotonic()
    if embedder is not None and all_entities:
        def _embed_entity(entity: Entity) -> EmbeddedChunk | None:
            try:
                emb = embedder.embed(entity.description, mode="passage")
                write_embedding(blob_root, emb)
                return EmbeddedChunk(
                    id=entity.id,
                    embedding=emb,
                    chunk_text=entity.description,
                    source_path=entity_source.get(entity.id, ""),
                    kind="entity",
                    scope=ScopePath(Path(entity_scope.get(entity.id, "."))),
                )
            except Exception:
                log.warning("Failed to embed entity %s, skipping", entity.name)
                return None

        n_workers = min(n_parallel, len(all_entities))
        with ThreadPoolExecutor(max_workers=n_workers) as pool:
            for chunk in pool.map(_embed_entity, all_entities):
                if chunk is not None:
                    all_chunks.append(chunk)
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
