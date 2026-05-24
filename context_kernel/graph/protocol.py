"""KnowledgeStore Protocol — the Parnas seam hiding the graph backend. See ARCHITECTURE.md §2.1."""

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


class KnowledgeStore(Protocol):
    """Backend-agnostic shape over the graph. Read APIs for all; write API for Ingester only."""

    def graph_commit(self) -> GraphCommit:
        """Opaque hash of the current graph state; embedded in materialized freshness headers."""
        ...

    def get_entity(self, entity_id: str) -> Entity | None: ...

    def get_neighbors(self, entity_id: str) -> list[Neighbor]: ...

    def get_summary(self, scope: ScopePath) -> Summary | None: ...

    def get_embedding(self, digest: Sha256) -> bytes | None: ...

    def upsert(
        self,
        graph_commit: GraphCommit,
        entities: list[Entity],
        relationships: list[Relationship],
        summaries: list[Summary],
    ) -> None:
        """Sole write path; only Ingester calls this. Ingester provides the commit identity per ADR-0008."""
        ...
