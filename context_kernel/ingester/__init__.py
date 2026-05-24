"""Ingester — sole graph writer. See ARCHITECTURE.md §2.2, invariant 1."""

from pathlib import Path
from typing import TYPE_CHECKING

from context_kernel.graph.protocol import KnowledgeStore
from context_kernel.ingester.errors import IngestionError
from context_kernel.types import GraphCommit

if TYPE_CHECKING:
    from context_kernel.config_store import IngesterConfig

__all__ = ["IngestionError", "ingest"]


def ingest(
    store: KnowledgeStore,
    sources_root: Path,
    blob_root: Path,
    config: "IngesterConfig",
) -> GraphCommit:
    """Detect changed sources, extract entities, upsert into Graph. Return the new GraphCommit."""
    raise NotImplementedError("TODO(impl)")
