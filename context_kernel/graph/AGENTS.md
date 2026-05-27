<!-- context-kernel-freshness
graph: 4828895ec2ab8c46292fc502e3c028e8b68915c679ff81f463cf9148983976a0
source-tree: 1bed2f2377c46c241470e8d8452d0c95090f6e2c57c8f52e6a3bbff9e51d2420
materialized: 2026-05-27T21:03:11Z
-->

This scope owns the graph knowledge store — the persistent source of truth for extracted entities, relationships, embeddings, and per-scope summaries. It is the data backbone that the rest of the context kernel reads from and writes to, implementing the storage and retrieval layer described in ARCHITECTURE.md §2.1. The graph scope is responsible for content-addressed blob storage, vector similarity search, and maintaining the entity-relationship topology that drives context assembly.

The public API surface is defined entirely by the `KnowledgeStore` protocol in `protocol.py`. This protocol declares nine methods: read operations like `get_entity`, `get_neighbors`, `get_summary`, `get_embedding`, and `search_similar`; listing operations `list_summaries` and `list_entities_by_scope`; and a single write operation `upsert` that accepts a `GraphCommit` along with lists of `Entity`, `Relationship`, `Summary`, and `EmbeddedChunk` objects. Supporting data types — `Entity`, `Relationship`, `Neighbor`, `Summary`, `EmbeddedChunk`, and `SearchResult` — are all dataclasses in the same module, forming a clean data contract that decouples graph consumers from any particular backend.

The sole production implementation is `LightRAGStore` in `lightrag_adapter.py`, which persists data as JSON files on disk and performs brute-force cosine similarity for vector search via the private `_cosine_sim` helper. It stores the graph topology using NetworkX conventions for neighbor lookups. The `addressing.py` module provides two utility functions — `hash_bytes` for computing canonical `Sha256` digests and `blob_path` for resolving on-disk paths for content-addressed blobs by kind (`'embeddings'` or `'summaries'`). This scope depends on `context_kernel.types` for `GraphCommit`, `ScopePath`, and `Sha256`, and on the standard library for hashing, JSON, and path operations.

## Recommended documentation

This scope has 15 code entities across 1 files but no reference documentation. To create one: `/init-reference graph`

