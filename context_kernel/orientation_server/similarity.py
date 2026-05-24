"""Embedding-similarity lookup over pre-materialized summary chunks. Used by `find`."""

from context_kernel.graph.protocol import KnowledgeStore, Summary


def nearest_summaries(query: str, store: KnowledgeStore, k: int) -> list[Summary]:
    """Return the top-k pre-materialized Summary chunks by embedding similarity to query."""
    raise NotImplementedError("TODO(impl)")
