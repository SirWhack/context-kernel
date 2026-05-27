# Ingester — Reference

How the ingestion pass works today. Operational reference for agents and engineers working in `context_kernel/ingester/`.

Contract: [ARCHITECTURE.md](../../ARCHITECTURE.md) §2.2.
Decisions: [ADR-0007](../adr/0007-per-scope-summaries-at-ingest.md), [ADR-0008](../adr/0008-content-derived-graph-commit.md), [ADR-0009](../adr/0009-cross-scope-relationships-via-source-id.md), [ADR-0011](../adr/0011-two-handler-protocols.md), [ADR-0013](../adr/0013-markdown-entity-taxonomy.md).

## Overview

The Ingester is the sole legitimate writer to the Graph (THEORY.md invariant 1). It reads source files from a portfolio, extracts entities and relationships via two handler protocols, optionally embeds them into the hybrid corpus, generates per-scope summaries, and upserts everything into the Graph in a single atomic commit. The ingestion pass is idempotent and incremental — re-running on unchanged source is a no-op, enforced by content-addressed GraphCommit hashes. Invoked as `ck ingest`.

The pipeline flows: file discovery → handler dispatch → entity extraction → embedding → per-scope summary generation → graph upsert.

## Ingestion pipeline

### File discovery and change detection

`walk_source_files(sources_root)` in `change_detection.py` finds all eligible files under the portfolio root. It excludes `.git/`, `.context-kernel/`, `node_modules/`, `__pycache__/`, and materialized files (`AGENTS.md`, `CLAUDE.md`). The result is a flat list of `Path` objects in filesystem order.

`discover_scopes(root)` identifies all directories containing source files — each becomes a scope. `source_tree_hash(scope_dir, tree_root)` computes a deterministic SHA-256 over the sorted (relative-path, file-content-hash) pairs in a scope, enabling the Materializer's freshness check.

`changed_since(root, prev_commit)` compares the current source tree hash against a previous GraphCommit. If they match, no files have changed and ingestion can be skipped. When `prev_commit` is None (first run), all files are returned.

### Handler dispatch

Each source file is routed to exactly one handler. The Ingester tries StructuredHandlers first (Python, then TypeScript/JS), falling back to ChunkHandlers (Markdown) if no StructuredHandler claims the file. Unsupported file types are silently skipped — extending the handler set is a code change, not a config change.

The two-protocol design ([ADR-0011](../adr/0011-two-handler-protocols.md)) separates structured sources (where the parser extracts entities mechanically) from unstructured sources (where an LLM must interpret the content). This is a Parnas information-hiding boundary: each handler hides one parsing strategy behind a common dispatch interface.

Handler registries are module-level constants in `__init__.py`: `_STRUCTURED = [PythonHandler(), TypeScriptHandler()]` and `_CHUNK = [MarkdownHandler()]`.

### Markdown ingestion (ChunkHandler)

The MarkdownHandler in `handlers.py` implements the ChunkHandler protocol. It splits markdown files at heading boundaries using `_parse_heading_tree()`, which preserves the full heading hierarchy. Each chunk is prefixed with its heading ancestry path — `[heading: Top > Section A > Subsection]` — providing contextual retrieval without an extra LLM call (analogous to Anthropic's contextual retrieval, but structural).

Oversized sections (> `_CHUNK_SIZE` of 1500 chars) are split at sentence or line boundaries via `_split_oversized()`. Empty sections and files are skipped.

Each chunk is then passed to the Summarizer, which uses LLM-based extraction to produce entities and relationships. The entity taxonomy is defined in [ADR-0013](../adr/0013-markdown-entity-taxonomy.md): 8 entity kinds (decision, constraint, invariant, trade-off, risk, workflow, interface, open-question) and 5 relationship kinds (implements, governed-by, motivates, supersedes, addresses). This is schema-guided extraction — the Summarizer's prompt constrains the LLM to the defined taxonomy.

If no Summarizer is configured, markdown files are skipped with a warning. This means markdown ingestion requires a running LLM endpoint.

### Python ingestion (StructuredHandler)

The PythonHandler in `handlers.py` implements the StructuredHandler protocol. It parses Python source via the `ast` module and extracts three entity kinds:

- **Module**: file-level entity with exports list, private constants, imports, and LOC depth. Uses `__all__` when present to determine the public API; falls back to name-based visibility (`_`-prefix = private).
- **Class**: extracts docstring, public/private methods with full signatures, public/private attributes with type annotations, base classes. Detects Protocol and ABC bases. Reports Ousterhout depth metrics (public method count, private method count, LOC).
- **Function**: extracts signature with parameter types and return type, visibility (public/private by `_`-prefix), LOC.

Relationships extracted: `imports` (from import statements) and `inherits` (from class base lists).

Syntax errors cause the file to be skipped with a warning; empty files are skipped silently.

### TypeScript/JS ingestion (StructuredHandler)

The TypeScriptHandler in `handlers.py` implements the StructuredHandler protocol using `tree-sitter` for parsing. Supports `.ts`, `.tsx`, `.js`, `.jsx`, `.mjs`, `.cjs` via language-specific parsers (`tree-sitter-typescript`, `tree-sitter-javascript`).

Extracts the same three entity kinds as Python (module, class, function), with TS-specific adaptations:
- **Interfaces** and **enums** are folded into the `class` entity kind with appropriate labels
- **Export keyword** determines visibility (not `_`-prefix)
- **Arrow functions** assigned to `const` are extracted as function entities
- **Type aliases** appear in the module preamble's export list

Import extraction handles ES6 named imports, namespace imports, default imports, and CommonJS `require()`. Relationships: `imports`, `inherits`, `implements`.

Parse errors in tree-sitter are handled gracefully — if the entire file is errors, it's skipped; partial errors allow extraction from the valid portions.

### Entity ID derivation

Entity IDs are deterministic SHA-256 hashes of `(project_name:name:kind:source_file)`, computed by `_derive_entity_id()` in `__init__.py`. This ensures:
- Same source → same IDs across re-ingests (idempotence)
- Different projects → different IDs even for same-named entities (cross-project namespacing per THEORY.md non-goal 2)
- Content-addressing at the entity level ([ADR-0008](../adr/0008-content-derived-graph-commit.md))

RawEntity/RawRelationship (handler output) are resolved to final Entity/Relationship (with graph IDs) by `_resolve_raw_entities()`. Relationship endpoints are resolved by name within the same source file; unresolved names get synthetic IDs.

### Embedding

When an Embedder is provided, the Ingester embeds both entity descriptions and scope summaries into the hybrid corpus. Entity descriptions are embedded in `"passage"` mode (per asymmetric prompting — [CONTEXT.md](../../CONTEXT.md)). Each produces an EmbeddedChunk with scope metadata, enabling scope-filtered search at query time.

Embedding bytes are also written as content-addressed blobs to `.context-kernel/embeddings/<sha256>.bin` via `blobs.py`.

The Embedder protocol hides the model choice (Parnas-secret). The current implementation uses Qwen3-Embedding-0.6B via a local OpenAI-compatible endpoint.

### Per-scope summary generation

After all files are processed, `_generate_scope_summary()` produces a one-line summary per scope: entity counts by kind, Protocol detection, and the top 5 public interface names. This is a mechanical summary — no LLM call.

Summaries are written as content-addressed blobs to `.context-kernel/summaries/<sha256>.md` and stored in the Graph. They form half of the hybrid corpus (the other half being entity descriptions). Per [ADR-0007](../adr/0007-per-scope-summaries-at-ingest.md).

If an Embedder is provided, summaries are also embedded for vector search.

### Graph upsert

The final step computes a GraphCommit hash (SHA-256 over sorted entity IDs + sorted relationship tuples) and calls `store.upsert()` with all accumulated entities, relationships, summaries, embedded chunks, and the scope-entity mapping. This is the sole write path to the Graph.

The scope-entity mapping (`Dict[ScopePath, List[Entity]]`) is critical for downstream consumers: the Materializer uses it for gap detection ([ADR-0014](../adr/0014-reference-docs-as-authored-root-nodes.md)), and cross-cutting views use it for by-topic filtering.

## Key decisions

- [ADR-0011: Two handler protocols](../adr/0011-two-handler-protocols.md) — separates ChunkHandler (LLM-dependent, for markdown/prose) from StructuredHandler (deterministic, for code). Each hides one parsing strategy; the Ingester dispatches cleanly.
- [ADR-0013: Markdown entity taxonomy](../adr/0013-markdown-entity-taxonomy.md) — defines 8 entity kinds and 5 relationship kinds for LLM-based extraction from documentation. Schema-guided: the Summarizer's prompt constrains output to this taxonomy.
- [ADR-0007: Per-scope summaries at ingest](../adr/0007-per-scope-summaries-at-ingest.md) — summaries are generated during ingestion (not materialization) and cached as content-addressed blobs.
- [ADR-0008: Content-derived graph_commit](../adr/0008-content-derived-graph-commit.md) — the GraphCommit hash is derived from entity/relationship content, not from graph-internal state. Enables idempotence.
- [ADR-0009: Cross-scope relationships via source-ID](../adr/0009-cross-scope-relationships-via-source-id.md) — cross-scope relationships are derived from LightRAG's native entity merging plus a source-ID traversal post-pass.

## Configuration

All ingester config lives in `IngesterConfig` (loaded from `.context-kernel/config.toml` `[ingester]` section):

| Key | Default | Purpose |
|---|---|---|
| `summarizer_model` | `qwen3-30b-a3b-instruct-2507` | LLM for markdown entity extraction |
| `summarizer_endpoint` | `http://127.0.0.1:8080/v1` | OpenAI-compatible endpoint for Summarizer |
| `embedder_model` | `qwen3-embedding-0.6b` | Embedding model for hybrid corpus |
| `embedder_endpoint` | `http://127.0.0.1:8081/v1` | OpenAI-compatible endpoint for Embedder |
| `embedder_dim` | `1024` | Embedding vector dimensionality |
| `storage_backend` | `networkx` | Graph backend (LightRAG storage adapter) |
| `summary_target_tokens` | `500` | Target length for scope summaries |

No config is needed for handler registration — the handler set is code, not config.

## Interfaces

### Summarizer protocol

`summarizer.py`: `Summarizer.summarize(text: str) → tuple[list[RawEntity], list[RawRelationship]]`. Sends a chunk to the LLM with the ADR-0013 taxonomy prompt. Parses the JSON response. Falls back to empty lists on parse failure.

### Embedder protocol

`embedder.py`: `Embedder.embed(text: str, mode: str = "passage") → bytes`. Returns float32 vector bytes. The `mode` parameter controls asymmetric prompting: `"passage"` for ingest-time content, `"query"` for search-time queries.

### ChunkHandler protocol

`handlers.py`: `ChunkHandler.supports(path: Path) → bool` and `ChunkHandler.chunks(path: Path) → list[str]`. Produces text chunks for the Summarizer.

### StructuredHandler protocol

`handlers.py`: `StructuredHandler.supports(path: Path) → bool` and `StructuredHandler.extract(path: Path) → tuple[list[RawEntity], list[RawRelationship]]`. Produces entities directly — no LLM needed.

## Relationships to other subsystems

- **Graph** — the Ingester is the sole writer. Calls `store.upsert()` with entities, relationships, summaries, and embedded chunks. See [docs/reference/graph.md](./graph.md).
- **Materializer** — consumes the Graph state the Ingester produces. Uses `list_entities_by_scope()` for gap detection and `get_summary()` for AGENTS.md rendering. See [docs/reference/materializer.md](./materializer.md).
- **OrientationServer** — searches the hybrid corpus populated by the Ingester's embedding pass. See [docs/reference/orientation-server.md](./orientation-server.md).
- **Types** — consumes GraphCommit, Sha256, ScopePath from `types.py`. Produces Entity, Relationship, Summary, EmbeddedChunk defined in `graph/protocol.py`. See [docs/reference/types.md](./types.md).

## Current limitations

- **No PDF handler.** Deferred to S11 (PLAN.md). The ChunkHandler protocol is ready; only the handler implementation is missing.
- **No incremental per-file ingestion.** Change detection operates at the scope level (source tree hash). A single changed file re-ingests the entire scope. Acceptable for v1 portfolio sizes.
- **Markdown ingestion requires a running LLM.** Without a Summarizer endpoint, markdown files are silently skipped. No fallback extraction.
- **Entity canonicalization is best-effort.** LLM-extracted entities from markdown may have inconsistent naming across files. No EntityResolver in v1 (deferred per ARCHITECTURE.md §6).
- **No handler for config files.** TOML, YAML, JSON files are skipped. Entities from configuration (e.g., view specs, model choices) are not in the graph.
