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

from context_kernel import change_detection as cd
from context_kernel import scoring
from context_kernel.graph.protocol import EmbeddedChunk, Entity, KnowledgeStore, Relationship, Summary
from context_kernel.ingester.blobs import write_embedding, write_summary
from context_kernel.change_detection import walk_source_files
from context_kernel.ingester.concepts import ground_entity_concepts, load_ontology
from context_kernel.ontology import is_ontology_file
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

__all__ = ["IngestionError", "ingest", "ingest_portfolio"]

log = logging.getLogger(__name__)

from context_kernel.ingester.terraform_handler import TerraformHandler
from context_kernel.ingester.yaml_handler import YAMLHandler
from context_kernel.ingester.bicep_handler import BicepHandler
from context_kernel.ingester.html_handler import HTMLHandler
from context_kernel.ingester.graphql_handler import GraphQLHandler
from context_kernel.ingester.rust_handler import RustHandler
from context_kernel.ingester.text_handler import TextHandler
from context_kernel.ingester.pdf_handler import PDFHandler

_STRUCTURED: list[StructuredHandler] = [
    PythonHandler(),
    TypeScriptHandler(),
    TerraformHandler(),
    YAMLHandler(),
    BicepHandler(),
    HTMLHandler(),
    GraphQLHandler(),
    RustHandler(),
]
_CHUNK: list[ChunkHandler] = [MarkdownHandler(), TextHandler(), PDFHandler()]

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


class _SnapshotStore:
    """In-memory sink used to build per-project snapshots before one portfolio upsert."""

    def __init__(self) -> None:
        self.commit: GraphCommit | None = None
        self.entities: list[Entity] = []
        self.relationships: list[Relationship] = []
        self.summaries: list[Summary] = []
        self.chunks: list[EmbeddedChunk] = []
        self.scope_entities: dict[ScopePath, list[Entity]] = {}

    def graph_commit(self) -> GraphCommit:
        return self.commit or GraphCommit("initial")

    def get_entity(self, entity_id: str) -> Entity | None:
        return None

    def get_neighbors(self, entity_id: str):
        return []

    def get_summary(self, scope: ScopePath) -> Summary | None:
        return None

    def get_embedding(self, digest: Sha256) -> bytes | None:
        return None

    def search_similar(self, query_embedding, k, scope=None):
        return []

    def list_summaries(self):
        return list(self.summaries)

    def list_entities_by_scope(self):
        return dict(self.scope_entities)

    def upsert(
        self,
        graph_commit,
        entities,
        relationships,
        summaries,
        chunks=None,
        scope_entities=None,
    ) -> None:
        self.commit = graph_commit
        self.entities = list(entities)
        self.relationships = list(relationships)
        self.summaries = list(summaries)
        self.chunks = list(chunks or [])
        self.scope_entities = dict(scope_entities or {})


def _rewrite_path_mentions(
    entities: list[RawEntity],
    relationships: list[RawRelationship],
    *,
    file_path: Path,
    rel_path: str,
) -> tuple[list[RawEntity], list[RawRelationship]]:
    """Keep handler prose portable even when handlers receive absolute paths."""
    absolute = str(file_path)
    if absolute == rel_path:
        return entities, relationships
    return (
        [
            RawEntity(e.name, e.kind, e.description.replace(absolute, rel_path))
            for e in entities
        ],
        [
            RawRelationship(
                r.source_name,
                r.target_name,
                r.kind,
                r.description.replace(absolute, rel_path),
            )
            for r in relationships
        ],
    )


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


def _include_ontology_file(files: list[Path], *, portfolio_root: Path, commit_root: Path) -> list[Path]:
    ontology_path, _specs = load_ontology(portfolio_root)
    if ontology_path is None:
        return files
    try:
        ontology_path.relative_to(commit_root)
    except ValueError:
        return files
    if ontology_path in files:
        return files
    return [*files, ontology_path]


def _apply_concept_layer(
    all_entities: list[Entity],
    all_relationships: list[Relationship],
    all_chunks: list[EmbeddedChunk],
    scope_entities: dict[str, list[Entity]],
    *,
    portfolio_root: Path,
    blob_root: Path,
    config: "IngesterConfig",
    embedder: "Embedder | None",
) -> None:
    """Ground curated entity-concepts into the production graph when an ontology exists."""
    _ontology_path, specs = load_ontology(portfolio_root)
    if not specs:
        return

    concept_entities, concept_relationships = ground_entity_concepts(all_entities, specs)
    if not concept_entities:
        return

    existing_entity_ids = {e.id for e in all_entities}
    scored_concepts: list[Entity] = []
    for c in concept_entities:
        if c.id in existing_entity_ids:
            continue
        tier = scoring.authority(c.sources, config.scoring)
        scored = Entity(
            id=c.id,
            name=c.name,
            kind=c.kind,
            description=c.description,
            aliases=c.aliases,
            sources=c.sources,
            kinds=c.kinds,
            source_tier=tier,
            centrality=0.0,
            confidence=scoring.confidence(tier, 0.0),
        )
        scored_concepts.append(scored)
        existing_entity_ids.add(c.id)

    if not scored_concepts:
        return

    all_entities.extend(scored_concepts)
    scope_entities.setdefault(".", []).extend(scored_concepts)

    existing_rel_keys = {(r.source_id, r.target_id, r.kind) for r in all_relationships}
    for rel in concept_relationships:
        key = (rel.source_id, rel.target_id, rel.kind)
        if key in existing_rel_keys:
            continue
        existing_rel_keys.add(key)
        weight = scoring.edge_weight(rel.kind, config.scoring)
        all_relationships.append(Relationship(
            source_id=rel.source_id,
            target_id=rel.target_id,
            kind=rel.kind,
            description=rel.description,
            weight=weight,
            drift=0.0,
        ))

    if embedder is None:
        return

    try:
        embeddings = _embed_many(embedder, [e.description for e in scored_concepts], mode="passage")
    except Exception:
        log.warning("Failed to embed concept entities, skipping concept chunks", exc_info=True)
        return

    for concept, emb in zip(scored_concepts, embeddings):
        write_embedding(blob_root, emb)
        src = concept.sources[0] if concept.sources else "ontology.toml"
        all_chunks.append(EmbeddedChunk(
            id=concept.id,
            embedding=emb,
            chunk_text=concept.description,
            source_path=src,
            kind="entity",
            scope=ScopePath(Path(".")),
        ))


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
    apply_concepts: bool = True,
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
        # The ontology is declarative input (it shapes the prompt) — hashed into the
        # commit via walk_source_files but never extracted as content (ADR-0024).
        if is_ontology_file(file_path):
            continue
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
        re_, rr_ = _rewrite_path_mentions(re_, rr_, file_path=file_path, rel_path=rel_path)
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

    # Doc-vs-code contradiction detection (issue #4, ADR-0016). The extractor flags a doc
    # claim that contradicts a known code entity as kind `stale-claim`. Surface them HERE and
    # drop them from the resolution input: resolution is code-anchored (ADR-0017) and would
    # otherwise merge a stale-claim into the very code node it contradicts, erasing the signal.
    # Relationships dangling off a dropped stale-claim resolve to no endpoint and self-drop.
    contradictions = [e for e in raw_entities if e.kind == "stale-claim"]
    if contradictions:
        raw_entities = [e for e in raw_entities if e.kind != "stale-claim"]
        for c in contradictions:
            log.warning(
                "doc-vs-code contradiction: %s claims %r%s",
                c.source_file, c.name, f" — {c.description}" if c.description else "",
            )

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

    # Scoring pass (ADR-0015/0020). All formulas live in `scoring`; all git I/O in
    # `change_detection`. Here we only orchestrate: per-edge weight + drift, then
    # per-node authority / centrality / confidence.
    cfg = config.scoring
    ent_by_id = {c.id: c for c in canonical}

    def _abs(src: str) -> str:
        return str(sources_root / src)

    def _code_src(c) -> str | None:
        return next((s for s in c.sources if s.endswith(CODE_EXT)), None)

    def _doc_src(c) -> str | None:
        return next((s for s in c.sources if not s.endswith(CODE_EXT)), None)

    # Per-edge: static weight, plus drift on doc↔code edges (code = referent, ADR-0020).
    # Drift loads on the claimant (doc) end; node_drift then aggregates a node's
    # claimant-side edges for its confidence.
    claimant_drift: dict[str, list[tuple[float, float]]] = defaultdict(list)
    all_relationships: list[Relationship] = []
    for r in resolved_rels:
        weight = scoring.edge_weight(r.kind, cfg)
        drift = 0.0
        cs, ct = ent_by_id.get(r.source_id), ent_by_id.get(r.target_id)
        if cs is not None and ct is not None and cs.is_code != ct.is_code:
            claimant_c, referent_c = (cs, ct) if ct.is_code else (ct, cs)
            claimant_src, referent_src = _doc_src(claimant_c), _code_src(referent_c)
            if claimant_src and referent_src:
                since = cd.commit_of(_abs(claimant_src))
                lines = cd.churn(_abs(referent_src), since)
                drift = scoring.edge_drift(lines, cd.size(_abs(referent_src)))
                claimant_drift[claimant_c.id].append((drift, weight))
        all_relationships.append(Relationship(
            source_id=r.source_id, target_id=r.target_id, kind=r.kind,
            description=r.description, weight=weight, drift=drift,
        ))

    # Centrality: distinct-source in-degree over centrality kinds (resolver-global edge set).
    node_sources = {c.id: tuple(c.sources) for c in canonical}
    centrality_map = scoring.centrality(node_sources, resolved_rels, cfg)

    all_entities: list[Entity] = []
    scope_entities: dict[str, list[Entity]] = defaultdict(list)
    seen_in_scope: dict[str, set[str]] = defaultdict(set)
    for c in canonical:
        tier = scoring.authority(c.sources, cfg)
        conf = scoring.confidence(tier, scoring.node_drift(claimant_drift.get(c.id, ())))
        ent = Entity(
            id=c.id, name=c.name, kind=c.kind, description=c.description,
            aliases=tuple(c.aliases), sources=tuple(c.sources), kinds=tuple(c.kinds),
            source_tier=tier, centrality=centrality_map.get(c.id, 0.0), confidence=conf,
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

        # ADR-0015 composite: emphasize current, central entities. ranking_weight =
        # confidence × centrality; stable sort keeps insertion order among ties.
        ranked = sorted(
            entities,
            key=lambda e: scoring.ranking_weight(e.confidence, e.centrality),
            reverse=True,
        )

        if summarizer is not None:
            descriptions = [e.description for e in ranked if e.description]
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

    if apply_concepts:
        _apply_concept_layer(
            all_entities,
            all_relationships,
            all_chunks,
            scope_entities,
            portfolio_root=blob_root,
            blob_root=blob_root,
            config=config,
            embedder=embedder,
        )

    commit_files = (
        _include_ontology_file(all_files, portfolio_root=blob_root, commit_root=sources_root)
        if apply_concepts
        else all_files
    )
    commit = _compute_graph_commit(commit_files, sources_root)
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
        "contradictions": len(contradictions),
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


def ingest_portfolio(
    store: KnowledgeStore,
    portfolio_root: Path,
    blob_root: Path,
    config: "IngesterConfig",
    projects: list[tuple[Path, str | None]],
    *,
    summarizer: Summarizer | None = None,
    embedder: "Embedder | None" = None,
    metrics: "LLMMetrics | None" = None,
) -> GraphCommit:
    """Ingest all configured projects and upsert one portfolio-wide graph snapshot.

    `ingest()` is still the single-project primitive. This wrapper prevents two bad
    states in multi-project portfolios: a final graph_commit that only describes the
    last project, and stale entities from projects/scopes that were removed.
    """
    t0 = time.monotonic()
    portfolio_root = portfolio_root.resolve()
    blob_root = blob_root.resolve()

    all_entities: list[Entity] = []
    all_relationships: list[Relationship] = []
    all_summaries: list[Summary] = []
    all_chunks: list[EmbeddedChunk] = []
    all_scope_entities: dict[ScopePath, list[Entity]] = {}
    all_files: list[Path] = []

    for project_path, project_name in projects:
        project_root = (portfolio_root / project_path).resolve()
        all_files.extend(walk_source_files(project_root))

        snapshot = _SnapshotStore()
        ingest(
            snapshot,
            project_root,
            blob_root,
            config,
            project_name=project_name,
            summarizer=summarizer,
            embedder=embedder,
            metrics=metrics,
            apply_concepts=False,
        )

        all_entities.extend(snapshot.entities)
        all_relationships.extend(snapshot.relationships)
        all_summaries.extend(snapshot.summaries)
        all_chunks.extend(snapshot.chunks)
        all_scope_entities.update(snapshot.scope_entities)

    concept_scope_entities = {str(k): list(v) for k, v in all_scope_entities.items()}
    _apply_concept_layer(
        all_entities,
        all_relationships,
        all_chunks,
        concept_scope_entities,
        portfolio_root=portfolio_root,
        blob_root=blob_root,
        config=config,
        embedder=embedder,
    )
    # `_apply_concept_layer` mutates a string-keyed scope map; fold those additions
    # back into the typed map for the final store write.
    all_scope_entities = {ScopePath(Path(k)): v for k, v in concept_scope_entities.items()}

    commit_files = _include_ontology_file(all_files, portfolio_root=portfolio_root, commit_root=portfolio_root)
    commit = (
        _compute_graph_commit(commit_files, portfolio_root)
        if commit_files
        else GraphCommit(hashlib.sha256(b"empty").hexdigest())
    )
    store.upsert(
        commit,
        all_entities,
        all_relationships,
        all_summaries,
        all_chunks or None,
        all_scope_entities or None,
    )

    elapsed = int((time.monotonic() - t0) * 1000)
    log.info(
        "portfolio_ingested",
        extra={
            "projects": len(projects),
            "files_processed": len(all_files),
            "entities": len(all_entities),
            "relationships": len(all_relationships),
            "graph_commit": str(commit),
            "duration_ms": elapsed,
        },
    )
    return commit
