# ADR-0012: `find` retrieval via hybrid embedding search

**Date:** 2026-05-25
**Status:** accepted
**Decides:** how the OrientationServer's `find` tool retrieves relevant results from the knowledge graph.

## Context

S5 deepens the `find` MCP tool from a canned stub to real embedding-similarity retrieval. The design has three axes: what corpus to search, where similarity computation happens, and whether the embedder runs at query time.

## Decision

**Hybrid corpus.** `find` searches over both entity descriptions (module, class, function — from StructuredHandlers) and per-scope summaries. Entity descriptions give fine-grained results ("what implements the Embedder interface?"); scope summaries give coarse orientation ("what does the ingester module do?"). Both are embedded at ingest time and stored in the same vector index.

**NanoVectorDB via `KnowledgeStore.search_similar()`.** A new protocol method `search_similar(query_embedding, k, scope?)` delegates to NanoVectorDB's built-in similarity search rather than reimplementing cosine similarity in-process. Returns `SearchResult` dataclass (chunk_text, source_path, score, kind, scope). This is the infrastructure LightRAG already provides — no reason to duplicate it.

**Query-time embedding.** `find` calls the `Embedder` at query time to embed the user's query string. This is a deterministic vector computation (sub-second, Qwen3-Embedding-0.6B on port 8081), not runtime synthesis — no LLM generation, no new content created. Invariant 3 ("no runtime synthesis") is not violated. The `Embedder` protocol gains a `mode` parameter (`"passage"` for ingest-time, `"query"` for find-time) to support Qwen3-Embedding's asymmetric prompt requirement (costs 1-5% retrieval accuracy without it, per S0.md).

## Alternatives considered

- **Entity-only corpus.** Simpler, but scope summaries provide altitude that entity descriptions don't — a query about "the auth module" should match the scope summary, not just individual functions.
- **In-process cosine similarity.** Load all embeddings, NumPy dot product, return top-k. Works at small scale but ignores the vector search infrastructure already present in the stack. Designing around it now means retrofitting later.
- **Pre-computed query embeddings.** Avoids calling the embedder at query time but is obviously impractical — can't predict what agents will ask.

## Consequences

- `KnowledgeStore` protocol gains `search_similar()` method; all implementations must support it.
- `Embedder` protocol gains `mode` parameter; all implementations must handle asymmetric prompting.
- `ingest()` must embed entity descriptions (structured handlers) and scope summaries, not just chunk handler output.
- `find` requires a running embedder service. If unreachable, returns a clear error — no silent degradation.
