"""OrientationServer — MCP read-through over the materialized tree. See ARCHITECTURE.md §2.5, invariant 3."""

from pathlib import Path
from typing import TYPE_CHECKING

from context_kernel.graph.protocol import KnowledgeStore

if TYPE_CHECKING:
    from context_kernel.config_store import OrientationConfig

__all__ = ["serve"]


def serve(
    tree_root: Path,
    store: KnowledgeStore,
    config: "OrientationConfig",
) -> None:
    """Run the MCP stdio server until shutdown. Spawned by `ck mcp`."""
    raise NotImplementedError("TODO(impl)")
