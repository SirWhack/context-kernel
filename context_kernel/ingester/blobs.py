"""Write content-addressed derived blobs under .context-kernel/{embeddings,summaries}/. See ARCHITECTURE.md §2.2."""

from pathlib import Path

from context_kernel.types import Sha256


def write_embedding(blob_root: Path, content: bytes) -> Sha256:
    """Write to .context-kernel/embeddings/<sha256>.bin; return the digest."""
    raise NotImplementedError("TODO(impl)")


def write_summary(blob_root: Path, markdown: str) -> Sha256:
    """Write to .context-kernel/summaries/<sha256>.md; return the digest."""
    raise NotImplementedError("TODO(impl)")
