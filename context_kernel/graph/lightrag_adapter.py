"""LightRAG-backed KnowledgeStore. The v1 backend per ARCHITECTURE.md §1.1.1."""

from pathlib import Path

from context_kernel.graph.protocol import (
    Entity,
    KnowledgeStore,
    Neighbor,
    Relationship,
    Summary,
)
from context_kernel.types import GraphCommit, ScopePath, Sha256


class LightRAGStore(KnowledgeStore):
    """KnowledgeStore impl wrapping HKUDS/LightRAG with pluggable storage."""

    def __init__(self, storage_root: Path) -> None:
        raise NotImplementedError("TODO(impl)")

    def graph_commit(self) -> GraphCommit:
        raise NotImplementedError("TODO(impl)")

    def get_entity(self, entity_id: str) -> Entity | None:
        raise NotImplementedError("TODO(impl)")

    def get_neighbors(self, entity_id: str) -> list[Neighbor]:
        raise NotImplementedError("TODO(impl)")

    def get_summary(self, scope: ScopePath) -> Summary | None:
        raise NotImplementedError("TODO(impl)")

    def get_embedding(self, digest: Sha256) -> bytes | None:
        raise NotImplementedError("TODO(impl)")

    def upsert(
        self,
        graph_commit: GraphCommit,
        entities: list[Entity],
        relationships: list[Relationship],
        summaries: list[Summary],
    ) -> None:
        raise NotImplementedError("TODO(impl)")
