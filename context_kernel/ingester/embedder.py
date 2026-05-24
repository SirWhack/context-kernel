"""Embedder Parnas-secret — hides which model produces vector embeddings. See ARCHITECTURE.md §2.2."""

from typing import Protocol


class Embedder(Protocol):
    """Produce a dense vector embedding for a text chunk."""

    def embed(self, text: str) -> bytes:
        """Return the serialized embedding. Caller addresses it via Sha256."""
        ...
