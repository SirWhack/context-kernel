"""Embedding-similarity lookup over the hybrid corpus. Used by `find`. Per ADR-0012."""

from __future__ import annotations

from typing import TYPE_CHECKING

from context_kernel.graph.protocol import KnowledgeStore, SearchResult
from context_kernel.types import ScopePath

if TYPE_CHECKING:
    from context_kernel.ingester.embedder import Embedder


def nearest_chunks(
    query: str,
    store: KnowledgeStore,
    embedder: Embedder,
    k: int,
    scope: ScopePath | None = None,
) -> list[SearchResult]:
    """Embed the query and return top-k results by similarity from the hybrid corpus."""
    query_embedding = embedder.embed(query, mode="query")
    return store.search_similar(query_embedding, k, scope)
