"""Write content-addressed derived blobs under .context-kernel/{embeddings,summaries}/. See ARCHITECTURE.md §2.2."""

from pathlib import Path

from context_kernel.graph.addressing import blob_path, hash_bytes
from context_kernel.types import Sha256


def write_embedding(blob_root: Path, content: bytes) -> Sha256:
    """Write to .context-kernel/embeddings/<sha256>.bin; return the digest."""
    digest = hash_bytes(content)
    path = blob_path(blob_root, digest, "embeddings")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return digest


def write_summary(blob_root: Path, markdown: str) -> Sha256:
    """Write to .context-kernel/summaries/<sha256>.md; return the digest."""
    raw = markdown.encode()
    digest = hash_bytes(raw)
    path = blob_path(blob_root, digest, "summaries")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return digest
