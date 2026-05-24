"""Decide which source files need re-ingesting. Unchanged source = no-op per invariant 4."""

from pathlib import Path

from context_kernel.types import GraphCommit


def changed_since(sources_root: Path, last_commit: GraphCommit | None) -> list[Path]:
    """Return source files whose content differs from what's in the last GraphCommit."""
    raise NotImplementedError("TODO(impl)")
