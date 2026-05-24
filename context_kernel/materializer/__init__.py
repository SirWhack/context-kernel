"""Materializer — sole writer to the materialized tree. See ARCHITECTURE.md §2.3, invariant 1."""

from pathlib import Path
from typing import TYPE_CHECKING

from context_kernel.graph.protocol import KnowledgeStore
from context_kernel.materializer.errors import MaterializationError
from context_kernel.types import ScopePath, ViewSpec

if TYPE_CHECKING:
    from context_kernel.config_store import MaterializerConfig

__all__ = ["MaterializationError", "materialize", "materialize_view"]


def materialize(
    scope: ScopePath,
    store: KnowledgeStore,
    tree_root: Path,
    config: "MaterializerConfig",
) -> None:
    """Write AGENTS.md + CLAUDE.md bridge for this scope. Idempotent on unchanged state."""
    raise NotImplementedError("TODO(impl)")


def materialize_view(
    spec: ViewSpec,
    store: KnowledgeStore,
    tree_root: Path,
    config: "MaterializerConfig",
) -> None:
    """Write one configured cross-cutting view under .context-kernel/views/."""
    raise NotImplementedError("TODO(impl)")
