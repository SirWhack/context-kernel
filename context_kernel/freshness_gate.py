"""FreshnessGate — read-boundary enforcement of invariant 2 ('no stale serve'). See ARCHITECTURE.md §2.4."""

from pathlib import Path

from context_kernel.graph.protocol import KnowledgeStore

# Does not own:
#   - reads bypassing the hook + MCP (raw `cat AGENTS.md`, scripts reading directly)
#   - content correctness (gate only checks the header; wrong-but-fresh content passes)
#   - regeneration latency (stale read blocks until Materializer finishes)
#   - concurrency arbitration beyond filesystem primitives


class StaleReadError(Exception):
    """Raised only if regeneration itself fails. Happy path returns fresh content silently."""


def check(path: Path, store: KnowledgeStore, tree_root: Path) -> bytes:
    """Compare path's freshness header against current state; regenerate if stale; return fresh bytes.

    Two integration points: Claude Code `PreToolUse` hook (direct Reads) and internal MCP check.
    """
    raise NotImplementedError("TODO(impl)")
