"""Content-addressing for derived blobs. Implements invariant 4. See ARCHITECTURE.md §2.1, §4."""

import hashlib
from pathlib import Path

from context_kernel.types import Sha256


def hash_bytes(content: bytes) -> Sha256:
    """Return the canonical Sha256 used as a blob filename."""
    return Sha256(hashlib.sha256(content).hexdigest())


def blob_path(root: Path, digest: Sha256, kind: str) -> Path:
    """Resolve the on-disk path for a content-addressed blob. kind is 'embeddings' or 'summaries'."""
    return root / ".context-kernel" / kind / f"{digest}.{'bin' if kind == 'embeddings' else 'md'}"
