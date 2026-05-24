"""MCP tools: overview(scope_path, max_tokens), find(query, scope_path). See ARCHITECTURE.md §2.5."""

from pathlib import Path

from context_kernel.materializer.headers import parse
from context_kernel.orientation_server.response import _CHARS_PER_TOKEN
from context_kernel.types import ScopePath


def overview(scope: ScopePath, max_tokens: int, tree_root: Path) -> str:
    """Return a markdown overview of this scope, capped by max_tokens. Cites source file paths."""
    agents_path = tree_root / scope / "AGENTS.md"
    if not agents_path.exists():
        return f"No materialized overview for scope `{scope}`."
    text = agents_path.read_text(encoding="utf-8")
    header = parse(text)
    if header:
        end = text.find("-->")
        if end != -1:
            text = text[end + 3:].lstrip("\n")
    budget = max_tokens * _CHARS_PER_TOKEN
    if len(text) <= budget:
        return text
    cut = text[:budget]
    para = cut.rfind("\n\n")
    if para > budget // 2:
        return cut[:para]
    return cut


def find(query: str, scope: ScopePath, tree_root: Path) -> str:
    """Stub for S1 — returns a canned response. Real embedding-similarity lookup in S5."""
    return (
        f"[S1 stub] `find` is not yet implemented. "
        f"Query: \"{query}\", scope: `{scope}`. "
        f"Use `overview` for scope summaries. Real implementation in S5."
    )
