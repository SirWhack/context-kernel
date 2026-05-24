"""Content-addressing for derived blobs. Implements invariant 4. See ARCHITECTURE.md §2.1, §4."""

from pathlib import Path

from context_kernel.types import Sha256


def hash_bytes(content: bytes) -> Sha256:
    """Return the canonical Sha256 used as a blob filename."""
    raise NotImplementedError("TODO(impl)")


def blob_path(root: Path, digest: Sha256, kind: str) -> Path:
    """Resolve the on-disk path for a content-addressed blob. kind is 'embeddings' or 'summaries'."""
    raise NotImplementedError("TODO(impl)")
