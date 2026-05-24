"""Freshness header format: graph + source-tree hashes + timestamp. Implements invariant 2."""

import re
from dataclasses import dataclass
from datetime import datetime, timezone

from context_kernel.types import GraphCommit, Sha256

_SENTINEL = "context-kernel-freshness"

_HEADER_RE = re.compile(
    r"<!--\s*" + _SENTINEL + r"\s*\n"
    r"graph:\s*(?P<graph>[0-9a-f]+)\s*\n"
    r"source-tree:\s*(?P<tree>[0-9a-f]+)\s*\n"
    r"materialized:\s*(?P<ts>\S+)\s*\n"
    r"-->",
)


@dataclass(frozen=True)
class FreshnessHeader:
    graph_commit: GraphCommit
    source_tree_hash: Sha256
    materialized_at: datetime


def render(header: FreshnessHeader) -> str:
    """Render the header as a markdown comment block to prepend to a materialized file."""
    ts = header.materialized_at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return (
        f"<!-- {_SENTINEL}\n"
        f"graph: {header.graph_commit}\n"
        f"source-tree: {header.source_tree_hash}\n"
        f"materialized: {ts}\n"
        f"-->"
    )


def parse(text: str) -> FreshnessHeader | None:
    """Parse a freshness header from the top of a materialized file. None if missing/malformed."""
    m = _HEADER_RE.search(text)
    if not m:
        return None
    return FreshnessHeader(
        graph_commit=GraphCommit(m.group("graph")),
        source_tree_hash=Sha256(m.group("tree")),
        materialized_at=datetime.fromisoformat(m.group("ts")),
    )
