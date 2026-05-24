"""Freshness header format: graph + source-tree hashes + timestamp. Implements invariant 2."""

from dataclasses import dataclass
from datetime import datetime

from context_kernel.types import GraphCommit, Sha256


@dataclass(frozen=True)
class FreshnessHeader:
    graph_commit: GraphCommit
    source_tree_hash: Sha256
    materialized_at: datetime


def render(header: FreshnessHeader) -> str:
    """Render the header as a markdown comment block to prepend to a materialized file."""
    raise NotImplementedError("TODO(impl)")


def parse(text: str) -> FreshnessHeader | None:
    """Parse a freshness header from the top of a materialized file. None if missing/malformed."""
    raise NotImplementedError("TODO(impl)")
