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
from context_kernel.ingester.change_detection import walk_source_files
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

__all__ = ["IngestionError", "ingest"]

log = logging.getLogger(__name__)

_STRUCTURED: list[StructuredHandler] = [PythonHandler(), TypeScriptHandler()]
_CHUNK: list[ChunkHandler] = [MarkdownHandler()]
_DEFAULT_PARALLEL = 2


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


def _compute_graph_commit(entities: list[Entity], relationships: list[Relationship]) -> GraphCommit:
    h = hashlib.sha256()
    for e in sorted(entities, key=lambda e: e.id):
        h.update(e.id.encode())
    for r in sorted(relationships, key=lambda r: (r.source_id, r.target_id)):
        h.update(f"{r.source_id}:{r.target_id}:{r.kind}".encode())
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
) -> GraphCommit:
    """Detect changed sources, extract entities, upsert into Graph. Return the new GraphCommit."""
    t0 = time.monotonic()
    sources_root = sources_root.resolve()
    blob_root = blob_root.resolve()

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

    # Phase 2: Process chunk files (LLM-dependent — parallelized at file level)
    def _process_chunk_file(
        file_path: Path, rel_path: str, scope_key: str, handler: ChunkHandler,
    ) -> _FileResult:
        result = _FileResult(rel_path=rel_path, scope_key=scope_key)
        chunks = handler.chunks(file_path)
        for chunk in chunks:
            raw_ents, raw_rels = summarizer.summarize(chunk)
            entities, relationships = _resolve_raw_entities(raw_ents, raw_rels, rel_path, project_name)
            result.entities.extend(entities)
            result.relationships.extend(relationships)

            if embedder is not None:
                embedding = embedder.embed(chunk)
                write_embedding(blob_root, embedding)
        return result

    if chunk_files and summarizer is not None:
        n_workers = min(_DEFAULT_PARALLEL, len(chunk_files))
        with ThreadPoolExecutor(max_workers=n_workers) as pool:
            futures = {
                pool.submit(_process_chunk_file, fp, rp, sk, h): (fp, rp, sk)
                for fp, rp, sk, h in chunk_files
            }
            for future in as_completed(futures):
                fp, rp, sk = futures[future]
                try:
                    result = future.result()
                    all_entities.extend(result.entities)
                    all_relationships.extend(result.relationships)
                    scope_entities[result.scope_key].extend(result.entities)
                    for entity in result.entities:
                        entity_source[entity.id] = result.rel_path
                        entity_scope[entity.id] = result.scope_key
                except Exception:
                    log.warning("Failed to process %s, skipping", rp, exc_info=True)
    elif chunk_files:
        for file_path, rel_path, scope_key, handler in chunk_files:
            log.warning("No summarizer configured, skipping %s", rel_path)

    # Embed entity descriptions
    if embedder is not None:
        for entity in all_entities:
            try:
                emb = embedder.embed(entity.description, mode="passage")
                write_embedding(blob_root, emb)
                all_chunks.append(EmbeddedChunk(
                    id=entity.id,
                    embedding=emb,
                    chunk_text=entity.description,
                    source_path=entity_source.get(entity.id, ""),
                    kind="entity",
                    scope=ScopePath(Path(entity_scope.get(entity.id, "."))),
                ))
            except Exception:
                log.warning("Failed to embed entity %s, skipping", entity.name)

    # Generate per-scope summaries (ADR-0007: LLM second pass when available)
    all_summaries: list[Summary] = []
    for scope_key, entities in scope_entities.items():
        scope = ScopePath(Path(scope_key))
        summary_text = None

        if summarizer is not None:
            descriptions = [e.description for e in entities if e.description]
            if descriptions:
                summary_text = summarizer.summarize_scope(str(scope), descriptions)

        if summary_text is None:
            summary_text = _generate_scope_summary(scope, entities)

        digest = write_summary(blob_root, summary_text)
        all_summaries.append(Summary(scope=scope, digest=digest, markdown=summary_text))

        if embedder is not None:
            try:
                emb = embedder.embed(summary_text, mode="passage")
                write_embedding(blob_root, emb)
                all_chunks.append(EmbeddedChunk(
                    id=digest,
                    embedding=emb,
                    chunk_text=summary_text,
                    source_path=scope_key,
                    kind="summary",
                    scope=scope,
                ))
            except Exception:
                log.warning("Failed to embed summary for scope %s, skipping", scope_key)

    commit = _compute_graph_commit(all_entities, all_relationships)
    typed_scope_entities = {ScopePath(Path(k)): v for k, v in scope_entities.items()}
    store.upsert(
        commit, all_entities, all_relationships, all_summaries,
        all_chunks or None,
        typed_scope_entities or None,
    )

    elapsed = int((time.monotonic() - t0) * 1000)
    log.info(
        "ingested",
        extra={
            "files_processed": len(all_files),
            "entities": len(all_entities),
            "relationships": len(all_relationships),
            "graph_commit": str(commit),
            "duration_ms": elapsed,
        },
    )

    return commit
