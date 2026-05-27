<!-- context-kernel-freshness
graph: 4828895ec2ab8c46292fc502e3c028e8b68915c679ff81f463cf9148983976a0
source-tree: 7b9fef38b6e54355c63f7dbafc2ec60936b148a49a3a1b5f5795205991434711
materialized: 2026-05-27T21:06:01Z
-->

The ingester is the sole graph writer in the context_kernel system, responsible for detecting changed source files, extracting entities and relationships from them, and upserting the results into a `KnowledgeStore`. It enforces the invariant that only one writer modifies the graph at a time, and it produces a `GraphCommit` that records the new state. The public entry point is the `ingest()` function, which takes a `KnowledgeStore`, source root, blob root, and `IngesterConfig`, and returns a `GraphCommit`. On failure, it raises `IngestionError` with source-file context.

The ingester delegates change detection to `walk_source_files()`, `source_tree_hash()`, and `changed_since()` in the `change_detection` module, which computes a deterministic hash of each scope directory and compares it against the last `GraphCommit` to identify files that need re-ingestion. For each changed file, the ingester uses a two-protocol handler system: `StructuredHandler` (implemented by `PythonHandler` and `TypeScriptHandler`) extracts `RawEntity` and `RawRelationship` objects via AST or tree-sitter parsing, while `ChunkHandler` (implemented by `MarkdownHandler`) splits prose files into text chunks for the `Summarizer`. The `_resolve_raw_entities()` function converts these raw extractions into canonical `Entity` and `Relationship` objects with deterministic IDs derived from `_derive_entity_id()`. The `Summarizer` produces markdown summaries, which are written as content-addressed blobs via `write_summary()` and `write_embedding()` in the `blobs` module.

Internally, the ingester uses `_FileResult` as a simple dataclass to carry extracted entities and relationships per file, and `_compute_graph_commit()` to hash the final graph state. The `Embedder` protocol (with `HttpEmbedder` as the concrete implementation) hides the choice of embedding model behind a clean interface, producing dense vector embeddings for text chunks. The handler classes in `handlers.py` are the most substantial internal components, with `PythonHandler` (122 LOC) using Python's `ast` module and `TypeScriptHandler` (241 LOC) using tree-sitter to extract structured knowledge from source code. The ingester depends on `context_kernel.graph.protocol` for the `KnowledgeStore`, `Entity`, `Relationship`, `EmbeddedChunk`, and `Summary` types, and on `context_kernel.types` for `GraphCommit`, `Sha256`, and `ScopePath`.

## Recommended documentation

This scope has 59 code entities across 1 files but no reference documentation. To create one: `/init-reference ingester`

