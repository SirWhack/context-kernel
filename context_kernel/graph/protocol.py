"""KnowledgeStore Protocol — the Parnas seam hiding the graph backend. See ARCHITECTURE.md §2.1."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from context_kernel.types import GraphCommit, ScopePath, Sha256

# Does not own:
#   - generic graph query language (no Cypher/Gremlin/SQL endpoint at this layer)
#   - stable entity IDs across re-ingests (only GraphCommit is a stable handle)
#   - cross-project entity unification (deferred behind EntityResolver, §6)
#   - serializable isolation across concurrent ck invocations


@dataclass(frozen=True)
class Entity:
    """A LightRAG-extracted entity. ID is stable only within one GraphCommit."""

    id: str
    name: str
    kind: str
    description: str


@dataclass(frozen=True)
class Relationship:
    """A directed edge between two entities, within one GraphCommit."""

    source_id: str
    target_id: str
    kind: str
    description: str


@dataclass(frozen=True)
class Neighbor:
    """One step out from a starting entity."""

    entity: Entity
    relationship: Relationship


@dataclass(frozen=True)
class Summary:
    """A per-scope summary derived from the graph; addressed by Sha256."""

    scope: ScopePath
    digest: Sha256
    markdown: str


@dataclass(frozen=True)
class EmbeddedChunk:
    """Write-path type: a text chunk with its embedding, ready for vector storage."""

    id: str
    embedding: bytes
    chunk_text: str
    source_path: str
    kind: str  # "entity" or "summary"
    scope: ScopePath


@dataclass(frozen=True)
class SearchResult:
    """Read-path type: a ranked result from vector similarity search."""

    chunk_text: str
    source_path: str
    score: float
    kind: str  # "entity" or "summary"
    scope: ScopePath


class KnowledgeStore(Protocol):
    """Backend-agnostic shape over the graph. Read APIs for all; write API for Ingester only."""

    def graph_commit(self) -> GraphCommit:
        """Opaque hash of the current graph state; embedded in materialized freshness headers."""
        ...

    def get_entity(self, entity_id: str) -> Entity | None: ...

    def get_neighbors(self, entity_id: str) -> list[Neighbor]: ...

    def get_summary(self, scope: ScopePath) -> Summary | None: ...

    def get_embedding(self, digest: Sha256) -> bytes | None: ...

    def search_similar(
        self,
        query_embedding: bytes,
        k: int,
        scope: ScopePath | None = None,
    ) -> list[SearchResult]:
        """Return top-k chunks by embedding similarity. Optional scope filter. Per ADR-0012."""
        ...

    def upsert(
        self,
        graph_commit: GraphCommit,
        entities: list[Entity],
        relationships: list[Relationship],
        summaries: list[Summary],
        chunks: list[EmbeddedChunk] | None = None,
    ) -> None:
        """Sole write path; only Ingester calls this. Ingester provides the commit identity per ADR-0008."""
        ...
