"""OrientationServer — MCP read-through over the materialized tree. See ARCHITECTURE.md §2.5, invariant 3."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from mcp.server.fastmcp import FastMCP

from context_kernel.graph.protocol import KnowledgeStore
from context_kernel.orientation_server import tools
from context_kernel.types import ScopePath

if TYPE_CHECKING:
    from context_kernel.config_store import OrientationConfig
    from context_kernel.ingester.embedder import Embedder

__all__ = ["serve"]


def serve(
    tree_root: Path,
    store: KnowledgeStore,
    config: "OrientationConfig",
    embedder: "Embedder | None" = None,
) -> None:
    """Run the MCP stdio server until shutdown. Spawned by `ck mcp`."""
    app = FastMCP("context-kernel")

    @app.tool()
    def overview(scope: str, max_tokens: int = config.default_max_tokens) -> str:
        """Get orientation summary for a specific scope (directory)."""
        return tools.overview(ScopePath(Path(scope)), max_tokens, tree_root)

    @app.tool()
    def find(query: str, scope: str | None = None, max_tokens: int = config.default_max_tokens) -> str:
        """Search for relevant code, modules, and documentation across the portfolio by semantic similarity."""
        scope_path = ScopePath(Path(scope)) if scope else None
        return tools.find(query, scope_path, max_tokens, tree_root, store, embedder)

    app.run()
