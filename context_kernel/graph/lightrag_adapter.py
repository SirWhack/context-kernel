"""LightRAG-backed KnowledgeStore. The v1 backend per ARCHITECTURE.md §1.1.1.

v1 implementation: JSON-file-persisted store with brute-force cosine similarity.
NetworkX graph topology is stored for neighbor lookups. The LightRAG library
integration (async entity extraction, GraphML storage) is deferred to post-v1;
the current backend handles all v1 protocol methods with minimal dependencies.
"""

import json
import math
import struct
from pathlib import Path

from context_kernel.graph.protocol import (
    EmbeddedChunk,
    Entity,
    KnowledgeStore,
    Neighbor,
    Relationship,
    SearchResult,
    Summary,
)
from context_kernel.types import GraphCommit, ScopePath, Sha256


def _cosine_sim(a: bytes, b: bytes) -> float:
    n = len(a) // 4
    if n == 0 or len(b) // 4 != n:
        return 0.0
    af = struct.unpack(f"{n}f", a)
    bf = struct.unpack(f"{n}f", b)
    dot = sum(x * y for x, y in zip(af, bf))
    ma = math.sqrt(sum(x * x for x in af))
    mb = math.sqrt(sum(x * x for x in bf))
    if ma == 0 or mb == 0:
        return 0.0
    return dot / (ma * mb)


class LightRAGStore(KnowledgeStore):
    """KnowledgeStore impl with JSON persistence and brute-force vector search."""

    def __init__(self, storage_root: Path) -> None:
        self._root = storage_root
        self._root.mkdir(parents=True, exist_ok=True)
        self._state_path = self._root / "state.json"
        self._chunks_dir = self._root / "chunks"
        self._chunks_dir.mkdir(exist_ok=True)

        self._commit: GraphCommit = GraphCommit("initial")
        self._entities: dict[str, Entity] = {}
        self._relationships: list[Relationship] = []
        self._summaries: dict[str, Summary] = {}
        self._scope_entities: dict[str, list[str]] = {}
        self._adj: dict[str, list[int]] = {}
        self._chunks: list[EmbeddedChunk] = []

        if self._state_path.exists():
            self._load()

    def _load(self) -> None:
        raw = json.loads(self._state_path.read_text(encoding="utf-8"))
        self._commit = GraphCommit(raw["commit"])

        self._entities = {
            e["id"]: Entity(
                id=e["id"], name=e["name"], kind=e["kind"], description=e["description"],
                aliases=tuple(e.get("aliases", ())),
                sources=tuple(e.get("sources", ())),
                kinds=tuple(e.get("kinds", ())),
            )
            for e in raw.get("entities", [])
        }
        raw_rels = [
            Relationship(source_id=r["source_id"], target_id=r["target_id"], kind=r["kind"], description=r["description"])
            for r in raw.get("relationships", [])
        ]
        seen: set[tuple[str, str, str]] = set()
        self._relationships = []
        for r in raw_rels:
            key = (r.source_id, r.target_id, r.kind)
            if key not in seen:
                seen.add(key)
                self._relationships.append(r)
        self._summaries = {
            s["scope"]: Summary(scope=ScopePath(Path(s["scope"])), digest=Sha256(s["digest"]), markdown=s["markdown"])
            for s in raw.get("summaries", [])
        }
        self._scope_entities = raw.get("scope_entities", {})

        self._adj = {}
        for i, rel in enumerate(self._relationships):
            self._adj.setdefault(rel.source_id, []).append(i)
            self._adj.setdefault(rel.target_id, []).append(i)

        self._chunks = []
        for c in raw.get("chunks", []):
            emb_path = self._chunks_dir / f"{c['id']}.bin"
            embedding = emb_path.read_bytes() if emb_path.exists() else b""
            self._chunks.append(EmbeddedChunk(
                id=c["id"],
                embedding=embedding,
                chunk_text=c["chunk_text"],
                source_path=c["source_path"],
                kind=c["kind"],
                scope=ScopePath(Path(c["scope"])),
            ))

    def _save(self) -> None:
        raw = {
            "commit": str(self._commit),
            "entities": [
                {"id": e.id, "name": e.name, "kind": e.kind, "description": e.description,
                 "aliases": list(e.aliases), "sources": list(e.sources), "kinds": list(e.kinds)}
                for e in self._entities.values()
            ],
            "relationships": [
                {"source_id": r.source_id, "target_id": r.target_id, "kind": r.kind, "description": r.description}
                for r in self._relationships
            ],
            "summaries": [
                {"scope": str(s.scope), "digest": str(s.digest), "markdown": s.markdown}
                for s in self._summaries.values()
            ],
            "scope_entities": self._scope_entities,
            "chunks": [
                {"id": c.id, "chunk_text": c.chunk_text, "source_path": c.source_path, "kind": c.kind, "scope": str(c.scope)}
                for c in self._chunks
            ],
        }
        self._state_path.write_text(json.dumps(raw, indent=2), encoding="utf-8")

        for chunk in self._chunks:
            if chunk.embedding:
                emb_path = self._chunks_dir / f"{chunk.id}.bin"
                if not emb_path.exists():
                    emb_path.write_bytes(chunk.embedding)

    def graph_commit(self) -> GraphCommit:
        return self._commit

    def get_entity(self, entity_id: str) -> Entity | None:
        return self._entities.get(entity_id)

    def get_neighbors(self, entity_id: str) -> list[Neighbor]:
        neighbors: list[Neighbor] = []
        for idx in self._adj.get(entity_id, []):
            rel = self._relationships[idx]
            other_id = rel.target_id if rel.source_id == entity_id else rel.source_id
            other = self._entities.get(other_id)
            if other:
                neighbors.append(Neighbor(entity=other, relationship=rel))
        return neighbors

    def get_summary(self, scope: ScopePath) -> Summary | None:
        return self._summaries.get(str(scope))

    def get_embedding(self, digest: Sha256) -> bytes | None:
        emb_path = self._chunks_dir / f"{digest}.bin"
        if emb_path.exists():
            return emb_path.read_bytes()
        return None

    def search_similar(
        self,
        query_embedding: bytes,
        k: int,
        scope: ScopePath | None = None,
    ) -> list[SearchResult]:
        scored: list[SearchResult] = []
        for chunk in self._chunks:
            if scope is not None and chunk.scope != scope:
                continue
            score = _cosine_sim(query_embedding, chunk.embedding)
            scored.append(SearchResult(
                chunk_text=chunk.chunk_text,
                source_path=chunk.source_path,
                score=score,
                kind=chunk.kind,
                scope=chunk.scope,
            ))
        scored.sort(key=lambda r: r.score, reverse=True)
        return scored[:k]

    def list_summaries(self) -> list[Summary]:
        return list(self._summaries.values())

    def list_entities_by_scope(self) -> dict[ScopePath, list[Entity]]:
        result: dict[ScopePath, list[Entity]] = {}
        for scope_key, entity_ids in self._scope_entities.items():
            entities = [self._entities[eid] for eid in entity_ids if eid in self._entities]
            if entities:
                result[ScopePath(Path(scope_key))] = entities
        return result

    def upsert(
        self,
        graph_commit: GraphCommit,
        entities: list[Entity],
        relationships: list[Relationship],
        summaries: list[Summary],
        chunks: list[EmbeddedChunk] | None = None,
        scope_entities: dict[ScopePath, list[Entity]] | None = None,
    ) -> None:
        self._commit = graph_commit

        for e in entities:
            self._entities[e.id] = e

        existing_keys = {(r.source_id, r.target_id, r.kind) for r in self._relationships}
        for r in relationships:
            key = (r.source_id, r.target_id, r.kind)
            if key not in existing_keys:
                existing_keys.add(key)
                self._relationships.append(r)
        self._adj = {}
        for i, rel in enumerate(self._relationships):
            self._adj.setdefault(rel.source_id, []).append(i)
            self._adj.setdefault(rel.target_id, []).append(i)

        for s in summaries:
            self._summaries[str(s.scope)] = s

        if chunks:
            existing_ids = {c.id for c in self._chunks}
            for c in chunks:
                if c.id not in existing_ids:
                    self._chunks.append(c)
                    existing_ids.add(c.id)

        if scope_entities:
            for scope, ents in scope_entities.items():
                self._scope_entities[str(scope)] = [e.id for e in ents]

        self._save()
