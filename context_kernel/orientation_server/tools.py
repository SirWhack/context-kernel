"""MCP tools: overview(scope_path, max_tokens), find(query, scope_path). See ARCHITECTURE.md §2.5."""

from pathlib import Path

from context_kernel.types import ScopePath


def overview(scope: ScopePath, max_tokens: int, tree_root: Path) -> str:
    """Return a markdown overview of this scope, capped by max_tokens. Cites source file paths."""
    raise NotImplementedError("TODO(impl)")


def find(query: str, scope: ScopePath, tree_root: Path) -> str:
    """Embedding-similarity lookup over pre-materialized summary chunks. Markdown + file-path citations."""
    raise NotImplementedError("TODO(impl)")
