# Graph — Reference

How the Graph subsystem works today. Operational reference for agents and engineers working in `context_kernel/graph/`.

Contract: [ARCHITECTURE.md](../../ARCHITECTURE.md) §2.1.
Decisions: [ADR-0004](../adr/0004-switch-to-lightrag.md), [ADR-0008](../adr/0008-content-derived-graph-commit.md), [ADR-0009](../adr/0009-cross-scope-relationships-via-source-id.md), [ADR-0012](../adr/0012-find-retrieval-via-hybrid-embedding-search.md).

## Overview

The Graph is the knowledge store and single source of truth in Context Kernel (THEORY.md invariant 1). It holds entities, relationships, and per-scope summaries derived from the portfolio's source files. Everything else in the system — materialized files, cross-cutting views, MCP responses — is derived from Graph state and is never authoritative on its own.

The Graph is the only mutable state in Context Kernel. The Ingester is the sole writer; the Materializer, OrientationServer, and FreshnessGate are read-only consumers. The backend is hidden behind a `KnowledgeStore` protocol (Parnas information-hiding per ARCHITECTURE.md tenet 1) so the storage engine can change without rippling through callers.

Source: `context_kernel/graph/protocol.py` (protocol + data types), `context_kernel/graph/lightrag_adapter.py` (v1 backend), `context_kernel/graph/addressing.py` (content addressing).

## KnowledgeStore protocol

The `KnowledgeStore` in `protocol.py` is a Python `Protocol` class — the Parnas seam hiding the graph backend. Any implementation that satisfies the method signatures is a valid backend. The protocol defines both read and write paths, but the write path (`upsert`) is called only by the Ingester. This separation is by convention, not enforcement — the protocol does not distinguish reader from writer callers.

The protocol deliberately does not expose a generic graph query language. There is no Cypher, Gremlin, or SQL endpoint. The API is shape-specific: entity lookup, neighbor traversal, summary retrieval, embedding retrieval, and vector similarity search. Adding a new query shape requires a code change to the protocol — this is intentional per ARCHITECTURE.md §8.

### Read path

Read methods serve three consumers: the Materializer (scope summaries, entity-by-scope mappings), the OrientationServer (vector similarity search via `find`), and the FreshnessGate (`graph_commit` comparison).

- `graph_commit() -> GraphCommit` — returns the opaque hash of the current graph state. Downstream modules embed this in freshness headers. Not derived by the Graph itself — provided by the Ingester at upsert time per [ADR-0008](../adr/0008-content-derived-graph-commit.md).
- `get_entity(entity_id) -> Entity | None` — single entity lookup by ID.
- `get_neighbors(entity_id) -> list[Neighbor]` — one-hop traversal from a starting entity. Returns both the neighboring entity and the connecting relationship.
- `get_summary(scope) -> Summary | None` — per-scope summary lookup. Used by the Materializer when rendering AGENTS.md.
- `get_embedding(digest) -> bytes | None` — raw embedding bytes by content-address digest.
- `search_similar(query_embedding, k, scope?) -> list[SearchResult]` — top-k vector similarity search over the hybrid corpus. Optional scope filter. Per [ADR-0012](../adr/0012-find-retrieval-via-hybrid-embedding-search.md).
- `list_summaries() -> list[Summary]` — all per-scope summaries. Used by cross-cutting views (index and by-topic).
- `list_entities_by_scope() -> dict[ScopePath, list[Entity]]` — scope-to-entity mapping. Used by cross-cutting views and the Materializer's gap detection ([ADR-0014](../adr/0014-reference-docs-as-authored-root-nodes.md)).

### Write path

A single method handles all mutations:

- `upsert(graph_commit, entities, relationships, summaries, chunks?, scope_entities?)` — the sole write path. Only the Ingester calls this. The caller provides the `graph_commit` identity (per [ADR-0008](../adr/0008-content-derived-graph-commit.md)) and all artifacts to associate with it. The graph stores the commit and returns it on subsequent `graph_commit()` calls.

The `upsert` signature takes optional `chunks` (embedded vectors for the hybrid corpus) and `scope_entities` (the scope-to-entity mapping). Both are populated when an Embedder is configured during ingestion.

## Data types

All data types are frozen dataclasses in `protocol.py`, imported via `context_kernel/graph/__init__.py`. The types split into write-path (produced by the Ingester, consumed by `upsert`) and read-path (returned by query methods).

### Entity

A LightRAG-extracted entity with `id`, `name`, `kind`, and `description`. Entity IDs are deterministic SHA-256 hashes of `(project_name:name:kind:source_file)`, computed by the Ingester. IDs are stable within one GraphCommit but not guaranteed stable across re-ingests if entity resolution changes — only `graph_commit` is a stable handle to a state-in-time.

### Relationship

A directed edge between two entities: `source_id`, `target_id`, `kind`, `description`. Kinds include `imports`, `inherits`, `implements` (from structured handlers) and the ADR-0013 taxonomy kinds (from markdown handlers). Cross-scope relationships — where endpoint entities have source files in different scopes — are the system's central differentiator per [ADR-0009](../adr/0009-cross-scope-relationships-via-source-id.md).

### Neighbor

A convenience type pairing an `Entity` with the `Relationship` that connects it to the query origin. Returned by `get_neighbors()` for one-hop graph traversal.

### Summary

A per-scope summary with `scope` (a ScopePath), `digest` (a Sha256 content address), and `markdown` (the rendered summary text). Summaries form half of the hybrid corpus; the other half is entity descriptions. Per [ADR-0007](../adr/0007-per-scope-summaries-at-ingest.md).

### EmbeddedChunk (write-path)

A text chunk with its embedding bytes, ready for vector storage. Fields: `id`, `embedding` (float32 bytes), `chunk_text`, `source_path`, `kind` ("entity" or "summary"), `scope`. Produced by the Ingester's embedding pass and stored in the Graph for `search_similar()` queries. The `kind` field distinguishes entity descriptions from scope summaries in search results.

### SearchResult (read-path)

A ranked result from vector similarity search. Fields: `chunk_text`, `source_path`, `score` (cosine similarity), `kind`, `scope`. Returned by `search_similar()` and consumed by the OrientationServer's `find` tool.

## LightRAGStore implementation

`lightrag_adapter.py` implements the `KnowledgeStore` protocol. Despite the name, the v1 backend is a self-contained JSON-persisted store — the LightRAG library integration (async entity extraction, GraphML storage) is deferred to post-v1. The current implementation handles all v1 protocol methods with minimal dependencies: `json`, `math`, `struct`, and `pathlib`.

### Persistence

All graph state is serialized to a single `state.json` file under the storage root. The file contains entities (as a list of dicts), relationships (as a list of dicts), summaries (keyed by scope string), scope-entity mappings, chunk metadata, and the current graph commit string. Embedding bytes are stored separately as binary files in a `chunks/` subdirectory, keyed by chunk ID.

On initialization, LightRAGStore loads `state.json` if it exists, reconstructing all in-memory data structures. On every `upsert`, the full state is written back — there is no incremental persistence. This is acceptable for v1 portfolio sizes but will not scale to very large graphs.

### Adjacency index

Neighbor lookups use an in-memory adjacency index (`_adj`): a dict mapping entity IDs to lists of relationship indices. The index is bidirectional — both `source_id` and `target_id` of each relationship are indexed. Rebuilt on load and after every upsert.

### Vector search

`search_similar()` implements brute-force cosine similarity. Embedding bytes are unpacked as float32 arrays via `struct.unpack`, dot-product and magnitude computed in pure Python. Results are sorted by score descending and truncated to top-k. An optional `scope` filter skips chunks not in the requested scope.

This is deliberately minimal. The v1 corpus is small enough (hundreds to low thousands of chunks) that brute-force is sub-second. A vector index (FAISS, NanoVectorDB, or similar) becomes necessary only when corpus size makes linear scan measurably slow.

### Upsert semantics

`upsert()` merges new data into existing state: entities are keyed by ID (newer overwrites older), relationships are appended, summaries are keyed by scope string (newer overwrites older), and chunks are deduplicated by ID. The adjacency index is fully rebuilt after every upsert. The full state is then persisted to `state.json` and embedding bytes are written to disk for any new chunks.

## Content addressing

`addressing.py` implements THEORY.md invariant 4 (derived artifacts are content-addressed and immutable). Two functions:

- `hash_bytes(content) -> Sha256` — SHA-256 hex digest of arbitrary bytes. The canonical content-address used as blob filenames.
- `blob_path(root, digest, kind) -> Path` — resolves the on-disk path for a content-addressed blob under `.context-kernel/{kind}/{digest}.{ext}`. Kind is `"embeddings"` (`.bin`) or `"summaries"` (`.md`).

Content addressing ensures that re-ingesting unchanged content produces the same blob paths — enabling the "re-ingest is a no-op" idempotence guarantee. The Ingester writes blobs; the Graph module provides the addressing scheme.

## Scope-entity mapping

The `scope_entities` dict maps `ScopePath` to a list of `Entity` objects (stored internally as entity IDs). This mapping is built by the Ingester during the ingestion pass — each entity is associated with the scope of its source file. The mapping is passed to `upsert()` and persisted in `state.json`.

Downstream consumers rely on this mapping: `list_entities_by_scope()` returns it for cross-cutting views (index view lists entities per scope; by-topic view filters entities by kind across scopes) and the Materializer uses it for gap detection — identifying scopes with high code-entity density but no reference documentation ([ADR-0014](../adr/0014-reference-docs-as-authored-root-nodes.md)).

## The graph_commit concept

`graph_commit` is the opaque hash that answers: "is this materialized file derived from a Graph state that is still current?" It is not derived from graph contents — it is derived from source content by the Ingester and passed to `upsert()` as input. Per [ADR-0008](../adr/0008-content-derived-graph-commit.md):

- Computed as SHA-256 over `(portfolio_root_relative_path, SHA-256(file_contents))` pairs, sorted by path.
- Re-ingest on unchanged sources produces the same `graph_commit` — genuine idempotence.
- Swapping the indexing LLM does not change `graph_commit`. The graph contents differ (different entity descriptions), but the commit identity does not, because it tracks source content, not graph state.
- The Graph stores it and returns it on `graph_commit()`, but never computes it. This is intentionally inverted from a typical "transactional store" interface.

The per-scope `source-tree hash` stored in materialized freshness headers uses the same primitive scoped to one directory's files.

## Key decisions

- [ADR-0004: Switch to LightRAG](../adr/0004-switch-to-lightrag.md) — LightRAG chosen over fast-graphrag (dormant), Microsoft GraphRAG (no incremental), Graphiti (Neo4j dependency), and others. Actively maintained, first-class incremental upsert, pluggable storage backends.
- [ADR-0008: Content-derived graph_commit](../adr/0008-content-derived-graph-commit.md) — `graph_commit` is derived from source file content, not graph state. Avoids the LLM-nondeterminism problem: re-ingest on unchanged sources is a genuine no-op.
- [ADR-0009: Cross-scope relationships via source-ID](../adr/0009-cross-scope-relationships-via-source-id.md) — cross-scope relationships are derived from entity merging plus source-ID traversal. The mechanism that lets a scope's AGENTS.md name its dependencies elsewhere in the portfolio.
- [ADR-0012: find retrieval via hybrid embedding search](../adr/0012-find-retrieval-via-hybrid-embedding-search.md) — `search_similar()` searches over both entity descriptions and scope summaries. Query-time embedding via the Embedder (infrastructure, not runtime synthesis).

## Configuration

The Graph backend is selected via the `storage_backend` key in `.context-kernel/config.toml` under `[ingester]`. The default is `networkx` (which in v1 means the JSON-persisted LightRAGStore). The storage root is `.context-kernel/graph/` under the portfolio root.

No Graph-specific configuration exists beyond the backend choice. The Graph's behavior — what it stores, how it searches, what it returns — is determined entirely by the protocol shape and the data the Ingester provides.

## Relationships to other subsystems

- **Ingester** — the sole writer. Calls `upsert()` with entities, relationships, summaries, embedded chunks, and scope-entity mappings. Provides the `graph_commit` identity. See [docs/reference/ingester.md](./ingester.md).
- **Materializer** — reads scope summaries (`get_summary`), entity-by-scope mappings (`list_entities_by_scope`), and all summaries (`list_summaries`) for cross-cutting views. Embeds `graph_commit` in freshness headers. See [docs/reference/materializer.md](./materializer.md).
- **OrientationServer** — searches the hybrid corpus via `search_similar()` for the `find` tool. Reads `graph_commit` for freshness checks. See [docs/reference/orientation-server.md](./orientation-server.md).
- **FreshnessGate** — compares the current `graph_commit` against freshness headers in materialized files to detect staleness.
- **Types** — consumes `GraphCommit`, `Sha256`, `ScopePath` from `context_kernel/types.py`. See [docs/reference/types.md](./types.md).

## Current limitations

- **No LightRAG library integration in v1.** The "LightRAGStore" name is aspirational. The v1 backend is a JSON-persisted store with brute-force vector search. Full LightRAG integration (async entity extraction, GraphML storage, NanoVectorDB) is deferred to post-v1.
- **No Neo4j or Postgres backend.** ARCHITECTURE.md §2.1 lists pluggable storage as a LightRAG benefit. In v1, only the JSON backend exists. The `KnowledgeStore` protocol makes a future swap a code change in one file, not a ripple through the system.
- **No concurrency guarantees.** The caller must not assume serializable isolation across concurrent `ck ingest` invocations. The JSON store does full-file read and write — concurrent upserts will lose data.
- **Full-state persistence on every upsert.** The entire `state.json` is rewritten on every `upsert()` call. Acceptable for v1 portfolio sizes; will need incremental persistence for larger graphs.
- **Brute-force vector search.** Linear scan over all chunks with pure-Python cosine similarity. Sub-second at v1 scale (hundreds of chunks); will need a vector index for larger corpora.
- **Entity IDs not stable across re-ingests.** If entity resolution changes (different LLM, different extraction prompt), IDs may change. Only `graph_commit` is a stable handle to a state-in-time.
- **No EntityResolver.** Cross-project entity merging is deferred per ARCHITECTURE.md §6 and THEORY.md non-goal 2. Same-named entities in different projects remain distinct.
