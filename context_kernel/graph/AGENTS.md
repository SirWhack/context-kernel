<!-- context-kernel-freshness
graph: ce4c30de6021574f8be593ca3ef2c62ccfde5e39118e774477c1d6d76f0f9abe
source-tree: 1a68f5e6a410ee6e2f8ebe02300b4c41032a3824264c1e499cac18fa2340d5ee
materialized: 2026-06-01T01:08:19Z
-->

The graph scope owns the knowledge store — the system’s source of truth for entities, relationships, and vector embeddings. It provides a read-heavy query surface for the rest of the application while restricting writes to a single `upsert` entry point, enforcing the invariant that only the ingester can mutate the graph. The scope also handles content-addressed blob storage for derived artifacts like summaries and embeddings, using SHA-256 digests as filenames via the `hash_bytes` and `blob_path` functions in `addressing.py`.

The public API is defined by the `KnowledgeStore` Protocol in `protocol.py`, which acts as a Parnas seam hiding the backend choice. It exposes nine methods: `graph_commit`, `get_entity`, `get_neighbors`, `get_summary`, `get_embedding`, `search_similar`, `list_summaries`, `list_entities_by_scope`, and `upsert`. The protocol also defines the data types that flow through these methods — `Entity`, `Relationship`, `Neighbor`, `Summary`, `EmbeddedChunk`, and `SearchResult` — all plain dataclasses with no behavior. The `__init__.py` re-exports these seven types for convenient importing by other scopes.

The sole concrete implementation is `LightRAGStore` in `lightrag_adapter.py`, which persists the graph to JSON files and performs brute-force cosine similarity for vector search (using a private `_cosine_sim` helper). It stores a NetworkX-compatible graph topology for neighbor lookups and manages on-disk state through `_load` and `_save` methods. This is the v1 backend; the architecture document notes that a future async LightRAG library integration is deferred. The scope depends on `context_kernel.types` for `GraphCommit`, `ScopePath`, and `Sha256`, and on Python standard library modules `json`, `math`, `os`, `struct`, and `pathlib`.

## Recommended documentation

This scope has 15 code entities across 1 files but no reference documentation. To create one: `/init-reference graph`

