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
    """A resolved entity (ADR-0017). ID is identity-derived; stable only within one GraphCommit.

    A canonical node may merge a code definition with the docs/ADRs that describe it:
    `aliases` are the surface names that merged, `sources` the files they came from,
    `kinds` the secondary kinds (the primary `kind` is code-authoritative when present).
    """

    id: str
    name: str
    kind: str
    description: str
    aliases: tuple[str, ...] = ()
    sources: tuple[str, ...] = ()
    kinds: tuple[str, ...] = ()
    # Scoring axes (ADR-0015 / ADR-0020). Materialized at ingest, stored on the record.
    # Defaults are neutral so an unscored or legacy node carries no penalty.
    source_tier: float = 0.0      # max authority over `sources` (0 = unscored)
    centrality: float = 0.0       # distinct-source in-degree, normalized; never folded into confidence
    confidence: float = 1.0       # authority × (1 − node_drift); 1.0 = fully trusted / unscored
    def_line: int | None = None   # 0-based start line of the code definition (for line-anchored edges)


@dataclass(frozen=True)
class Relationship:
    """A directed edge between two entities, within one GraphCommit."""

    source_id: str
    target_id: str
    kind: str
    description: str
    # Scoring (ADR-0015 Axis 4 / ADR-0020). `weight` is a static f(kind); `drift` is the
    # edge's directional staleness (referent→claimant), loaded on the claimant end.
    weight: float = 0.5           # edge_weight(kind); 0.5 = unknown-kind mid weight
    drift: float = 0.0            # normalized churn to the referent since the claimant last changed
    source_line: int | None = None  # 0-based line of the call/import site in the source file


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
    # Composition handles (ADR-0019): let `find` rerank by stored confidence + proximity
    # without re-reading the graph. Populated by `search_similar`; neutral when unknown.
    entity_id: str | None = None
    confidence: float = 1.0


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

    def list_summaries(self) -> list[Summary]:
        """Return all per-scope summaries. Used by cross-cutting views (S6)."""
        ...

    def list_entities_by_scope(self) -> dict[ScopePath, list[Entity]]:
        """Return scope→entity mapping. Used by cross-cutting views (S6)."""
        ...

    def list_relationships(self) -> list[Relationship]:
        """Return every edge in the current GraphCommit. Used by full-graph export (`ck graph`)."""
        ...

    def upsert(
        self,
        graph_commit: GraphCommit,
        entities: list[Entity],
        relationships: list[Relationship],
        summaries: list[Summary],
        chunks: list[EmbeddedChunk] | None = None,
        scope_entities: dict[ScopePath, list[Entity]] | None = None,
    ) -> None:
        """Sole write path; only Ingester calls this. Ingester provides the commit identity per ADR-0008."""
        ...
