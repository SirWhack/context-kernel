"""AGENTS.md + CLAUDE.md bridge templates per ADR-0002. See ARCHITECTURE.md §2.3."""

from context_kernel.graph.protocol import KnowledgeStore, Summary
from context_kernel.materializer.headers import FreshnessHeader, render
from context_kernel.types import ScopePath


def render_agents_md(header: FreshnessHeader, summary: Summary | None) -> str:
    """Render the canonical AGENTS.md content for this scope."""
    body = summary.markdown if summary else ""
    return render(header) + "\n\n" + body + "\n"


def render_claude_md_bridge() -> str:
    """Render the thin CLAUDE.md that does `@AGENTS.md`. Per ADR-0002."""
    return "@AGENTS.md\n"
