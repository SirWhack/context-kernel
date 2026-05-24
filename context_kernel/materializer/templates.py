"""AGENTS.md + CLAUDE.md bridge templates per ADR-0002. See ARCHITECTURE.md §2.3."""

from context_kernel.graph.protocol import KnowledgeStore
from context_kernel.types import ScopePath


def render_agents_md(scope: ScopePath, store: KnowledgeStore) -> str:
    """Render the canonical AGENTS.md content for this scope."""
    raise NotImplementedError("TODO(impl)")


def render_claude_md_bridge(scope: ScopePath) -> str:
    """Render the thin CLAUDE.md that does `@AGENTS.md`. Per ADR-0002."""
    raise NotImplementedError("TODO(impl)")
