# Core Types -- Reference

Cross-module domain primitives, graph protocol types, handler intermediates, materializer types, and configuration types. Operational reference for agents and engineers working across subsystem boundaries.

Contract: [ARCHITECTURE.md](../../ARCHITECTURE.md) §2.1--2.6, §3.1, §4.
Decisions: [ADR-0008](../adr/0008-content-derived-graph-commit.md), [ADR-0011](../adr/0011-two-handler-protocols.md), [ADR-0012](../adr/0012-find-retrieval-via-hybrid-embedding-search.md).

## Overview

Context Kernel's type system is deliberately thin. Types live in a small number of files, each at a specific altitude: cross-module domain primitives in `context_kernel/types.py`, graph protocol types in `context_kernel/graph/protocol.py`, handler intermediates in `context_kernel/ingester/handlers.py`, materializer types split across `context_kernel/materializer/headers.py` and `context_kernel/materializer/pinned.py`, and configuration types in `context_kernel/config_store.py`.

Every type is either a `NewType` (zero-cost wrapper for type safety) or a `frozen=True` dataclass (immutable value object). No mutable data structures cross module boundaries. This is not accidental -- it implements THEORY.md invariant 4 (content-addressed, immutable derived artifacts) at the type level.

## Cross-module domain primitives

### GraphCommit

`NewType("GraphCommit", str)` in `types.py`. An opaque SHA-256 hash identifying a Graph state-in-time. Derived from source file content (path + content hash pairs, sorted and hashed), not from graph-internal state -- see [ADR-0008](../adr/0008-content-derived-graph-commit.md). The same source files always produce the same GraphCommit, which is what makes the ingestion pass idempotent.

Produced by the Ingester before invoking LightRAG. Passed to `KnowledgeStore.upsert()` as input (the Graph stores it, does not derive it). Embedded by the Materializer into every freshness header. Read by the FreshnessGate to determine staleness.

Why `NewType`, not `str`: prevents accidental mixing with other hex strings (Sha256, arbitrary hashes). No runtime overhead -- Python treats it as a plain `str` at execution time. The type checker enforces the distinction.

### Sha256

`NewType("Sha256", str)` in `types.py`. A 64-character hex digest used as a content-addressed blob filename. Written by the Ingester to `.context-kernel/embeddings/<sha256>.bin` and `.context-kernel/summaries/<sha256>.md`. Read by the Materializer and OrientationServer for summary retrieval. Also used as the `source_tree_hash` in freshness headers.

Distinct from GraphCommit by intent: Sha256 addresses a single blob; GraphCommit addresses an entire graph state.

### ScopePath

`NewType("ScopePath", Path)` in `types.py`. A portfolio-root-relative directory path; the unit of materialization. Each ScopePath maps to one `AGENTS.md` file in the materialized tree. Today, scope is coterminous with directory (THEORY.md open question 2).

Used by nearly every module: the Ingester groups entities by scope, the Graph stores per-scope summaries and entity mappings, the Materializer renders one file per scope, and the OrientationServer accepts scope as a filter on `overview` and `find`.

### ViewSpec

`@dataclass(frozen=True)` in `types.py`. A configured `[[materializer.views]]` entry describing one cross-cutting view. Fields: `name` (view filename), `kind` (`"index"` or `"by-topic"` in v1), `params` (kind-specific configuration, e.g. topic tag for by-topic views).

ViewSpec is the system's expressive surface -- the mechanism an agentic engineer uses to declare "I want a materialized file that aggregates X across scopes." Loaded from `.context-kernel/config.toml` by the ConfigStore; consumed by the Materializer's view-rendering pipeline. A view is a `(ViewSpec, graph_state) -> file` projection.

Why dataclass over NamedTuple: `frozen=True` gives the same immutability guarantee but allows default values and is consistent with every other type in the system.

## Graph protocol types

Defined in `context_kernel/graph/protocol.py`. These are the shapes the `KnowledgeStore` protocol traffics in -- they define the contract between the Graph and every module that reads or writes it.

### Entity

Frozen dataclass. A LightRAG-extracted entity: `id`, `name`, `kind`, `description`. The `id` is a deterministic SHA-256 of `(project_name:name:kind:source_file)`, derived by the Ingester (not by the Graph backend). Entity IDs are stable within one GraphCommit but may change across re-ingests if the entity's name, kind, or source file changes.

Produced by the Ingester (via `_resolve_raw_entities()`). Stored in the Graph. Read by the Materializer for AGENTS.md rendering, by cross-cutting views for by-topic filtering, and by the OrientationServer for `find` results.

### Relationship

Frozen dataclass. A directed edge: `source_id`, `target_id`, `kind`, `description`. Kinds include `imports`, `inherits`, `implements` (from StructuredHandlers) and the [ADR-0013](../adr/0013-markdown-entity-taxonomy.md) taxonomy kinds (`implements`, `governed-by`, `motivates`, `supersedes`, `addresses`) from ChunkHandlers.

Cross-scope relationships -- where endpoint Entities have source files in different scopes -- are the bridge that lets a scope's AGENTS.md name its dependencies elsewhere in the portfolio. Derived via source-ID traversal per [ADR-0009](../adr/0009-cross-scope-relationships-via-source-id.md).

### Neighbor

Frozen dataclass. One step out from a starting entity: pairs an `Entity` with the `Relationship` that connects them. Returned by `KnowledgeStore.get_neighbors()`. Used by the Materializer when rendering cross-scope dependency sections in AGENTS.md.

### Summary

Frozen dataclass. A per-scope summary derived from the graph: `scope` (ScopePath), `digest` (Sha256), `markdown` (the summary text). Produced by the Ingester during per-scope summary generation ([ADR-0007](../adr/0007-per-scope-summaries-at-ingest.md)). Also written as a content-addressed blob to `.context-kernel/summaries/<digest>.md`. Forms half of the hybrid corpus (the other half being entity descriptions).

### EmbeddedChunk

Frozen dataclass. Write-path type: a text chunk paired with its embedding bytes, ready for vector storage. Fields: `id`, `embedding` (raw float32 bytes), `chunk_text`, `source_path`, `kind` (`"entity"` or `"summary"`), `scope`.

Produced by the Ingester's embedding pass (entity descriptions in `"passage"` mode per asymmetric prompting). Passed to `KnowledgeStore.upsert()`. Never read back as EmbeddedChunk -- the read-path equivalent is SearchResult. This asymmetry (write-path type vs. read-path type) keeps the vector storage internals hidden behind the KnowledgeStore protocol.

### SearchResult

Frozen dataclass. Read-path type: a ranked result from vector similarity search. Fields: `chunk_text`, `source_path`, `score`, `kind` (`"entity"` or `"summary"`), `scope`.

Returned by `KnowledgeStore.search_similar()`. Consumed by the OrientationServer's `find` tool ([ADR-0012](../adr/0012-find-retrieval-via-hybrid-embedding-search.md)). The `kind` field lets `find` distinguish entity-level results (fine-grained: individual classes, functions) from scope-level results (coarse orientation: what a directory does).

### KnowledgeStore protocol

The Parnas seam hiding the graph backend. Defines the full read/write shape: `graph_commit()`, `get_entity()`, `get_neighbors()`, `get_summary()`, `get_embedding()`, `search_similar()`, `list_summaries()`, `list_entities_by_scope()`, and `upsert()`. Only the Ingester calls `upsert()`; all other modules use the read methods.

The protocol does not expose a generic graph query language (no Cypher/Gremlin/SQL) -- the API is shape-specific by design ([ARCHITECTURE.md](../../ARCHITECTURE.md) §8). Adding new query shapes is a code change.

## Handler intermediates

### RawEntity and RawRelationship

Frozen dataclasses in `context_kernel/ingester/handlers.py`. The boundary types between handlers and the ingest loop. RawEntity has `name`, `kind`, `description` -- no `id`. RawRelationship has `source_name`, `target_name`, `kind`, `description` -- endpoint references are by name, not by graph ID.

This is the clean separation mandated by [ADR-0011](../adr/0011-two-handler-protocols.md): handlers know how to parse source files; the Ingester knows how to derive graph IDs. StructuredHandlers produce RawEntity/RawRelationship directly from AST analysis. ChunkHandlers produce text chunks that the Summarizer converts to RawEntity/RawRelationship via LLM extraction.

The Ingester's `_resolve_raw_entities()` converts Raw types to final Entity/Relationship by computing deterministic IDs and resolving name-based relationship endpoints to graph IDs. Unresolved names get synthetic IDs.

## Materializer types

### FreshnessHeader

Frozen dataclass in `context_kernel/materializer/headers.py`. Fields: `graph_commit` (GraphCommit), `source_tree_hash` (Sha256), `materialized_at` (datetime). Rendered as an HTML comment block at the top of every materialized file. Parsed back by the FreshnessGate to determine staleness.

The header's lifecycle: the Materializer writes it during `ck materialize`; the FreshnessGate (pre-commit hook) reads it during `ck ingest && ck materialize` and compares against the current GraphCommit and source-tree hash. If they match, the file is fresh and not rewritten. Implements THEORY.md invariant 2.

The `render()` function produces the HTML comment; `parse()` recovers the header from a materialized file (returns `None` if missing or malformed).

### PinnedBlock

Frozen dataclass in `context_kernel/materializer/pinned.py`. Fields: `label` (optional string identifier) and `content` (the preserved text). Represents a `<!-- pinned -->` / `<!-- pinned:label -->` wrapped section in a materialized file whose contents survive regeneration.

Pinned blocks are the highest-quality data in the system -- deliberately authored human context. The `extract()` function parses all pinned blocks from an existing materialized file (handling duplicate labels, unpaired tags, and malformed blocks with warnings). The `merge()` function appends preserved blocks to freshly rendered output. Labels enable dedup: duplicate labels keep the last occurrence.

Not supported in cross-cutting views -- views are pure projections with no side inputs.

## Configuration types

Defined in `context_kernel/config_store.py`. All frozen dataclasses. Loaded from `.context-kernel/config.toml` at the start of every `ck` invocation (no daemon means no reload problem).

### IngesterConfig

Controls the ingestion pass: `summarizer_model`, `summarizer_endpoint` (for the LLM-based entity extractor), `embedder_model`, `embedder_endpoint`, `embedder_dim` (vector dimensionality), `storage_backend` (LightRAG adapter choice), `summary_target_tokens`. Every field has a sensible default; zero config is needed to run against local models.

### MaterializerConfig

Controls materialization: `views` (list of ViewSpec entries defining cross-cutting views) and `gap_detection_threshold` (entity count below which a scope is considered too sparse for a gap detection recommendation per [ADR-0014](../adr/0014-reference-docs-as-authored-root-nodes.md)).

### OrientationConfig

Controls the MCP surface: `default_max_tokens` (token budget for `overview` and `find` responses). A single knob because the OrientationServer is deliberately narrow.

### Config

Top-level aggregate: `ingester` (IngesterConfig), `materializer` (MaterializerConfig), `orientation` (OrientationConfig), `portfolio_root` (resolved absolute Path), `projects` (list of ProjectSpec for cross-project ingestion). The `load()` function reads TOML, applies defaults, validates project paths, and returns a frozen Config.

### ProjectSpec

A single project within the portfolio: `path` (portfolio-root-relative Path). The `name` property returns the directory name. Validated at load time: must be relative, must match `[a-zA-Z0-9_][a-zA-Z0-9_.\-]*`, must not duplicate another project's name, must exist on disk.

## Type flow across module boundaries

Types are the wiring diagram of the system. The flow follows the architecture's pipeline:

**Ingester** reads source files and produces RawEntity/RawRelationship (from handlers), converts them to Entity/Relationship (with graph IDs), generates Summary per scope, optionally creates EmbeddedChunk per entity and summary, computes a GraphCommit, and calls `KnowledgeStore.upsert()` with all of them.

**Graph** (KnowledgeStore) stores Entity, Relationship, Summary, and EmbeddedChunk. Returns Entity, Neighbor, Summary, and SearchResult through its read API. Returns the current GraphCommit. The Graph never creates types -- it stores what the Ingester provides and returns what readers request.

**Materializer** reads Entity (via `list_entities_by_scope()`), Summary (via `get_summary()`), and Neighbor (via `get_neighbors()`) from the Graph. It reads ViewSpec from Config. It reads FreshnessHeader from existing files and PinnedBlock from existing AGENTS.md. It writes new FreshnessHeader into every output file and merges PinnedBlock back into rendered output.

**OrientationServer** reads SearchResult (via `search_similar()`) from the Graph. The query-time Embedder produces the query embedding; the Graph returns ranked SearchResult objects. The server formats them as markdown with source-path citations.

**FreshnessGate** reads FreshnessHeader from materialized files and GraphCommit from the Graph. Compares them. If stale, triggers the Materializer.

## Design rationale

### NewType for GraphCommit, Sha256, ScopePath

All three are semantically distinct strings (or Paths) that could be accidentally mixed. `NewType` provides type-checker enforcement with zero runtime cost -- Python treats the values as plain `str` or `Path` at execution time. No wrapper class, no `__init__`, no attribute access overhead. The alternative (wrapper dataclasses) would add allocation overhead on every instance for no runtime benefit.

GraphCommit and Sha256 are both hex strings but serve different purposes: GraphCommit identifies a graph state-in-time; Sha256 identifies a single content-addressed blob. Without `NewType`, passing a blob hash where a graph commit is expected would be a silent type error.

### Frozen dataclasses everywhere

Every dataclass in the type system uses `frozen=True`. This serves three purposes:

1. **Content-addressability.** Frozen objects can be hashed, which means they can participate in content-addressing schemes (invariant 4). A mutable Entity could change after its ID was computed, breaking the ID-to-content contract.

2. **Safe sharing across module boundaries.** When the Ingester passes an Entity to the Graph, neither side worries about the other mutating it. No defensive copies needed.

3. **Clarity of data flow.** Immutable types make it obvious that types flow in one direction through the pipeline. An Entity is created by the Ingester and consumed (never modified) by the Graph, Materializer, and OrientationServer. If mutation were needed, you would create a new instance -- making the transformation explicit.

### Write-path vs. read-path types

EmbeddedChunk and SearchResult illustrate a deliberate asymmetry. EmbeddedChunk carries raw embedding bytes (the write payload for vector storage). SearchResult carries a relevance score (the read response from vector search). They share `chunk_text`, `source_path`, `kind`, and `scope`, but they are separate types because they serve different consumers at different points in the pipeline. Collapsing them into one type would leak vector storage internals into the read interface.

## Relationships to other subsystems

- **Ingester** -- the primary producer of most types. Creates Entity, Relationship, Summary, EmbeddedChunk, computes GraphCommit. Consumes RawEntity/RawRelationship from handlers. See [docs/reference/ingester.md](./ingester.md).
- **Graph** -- stores and returns Entity, Relationship, Summary, EmbeddedChunk, SearchResult, GraphCommit through the KnowledgeStore protocol.
- **Materializer** -- consumes Entity, Summary, Neighbor, FreshnessHeader, PinnedBlock, ViewSpec, GraphCommit. Produces FreshnessHeader, merges PinnedBlock.
- **OrientationServer** -- consumes SearchResult from the Graph's `search_similar()` method.
- **FreshnessGate** -- consumes FreshnessHeader and GraphCommit for staleness comparison.
- **ConfigStore** -- produces Config, IngesterConfig, MaterializerConfig, OrientationConfig, ProjectSpec, ViewSpec from `.context-kernel/config.toml`.
