<!-- context-kernel-freshness
graph: ce4c30de6021574f8be593ca3ef2c62ccfde5e39118e774477c1d6d76f0f9abe
source-tree: 1ae8e300931d0c6e98fd48b16768018db97839af34505ce21072402c6a795e38
materialized: 2026-06-01T01:08:19Z
-->

The ingester is the sole graph writer for the context kernel — it transforms raw source files into a structured, deduplicated knowledge graph of entities, relationships, embeddings, and summaries. Its core responsibility is to walk a project's source tree, parse every file through format-specific handlers, merge duplicate logical concepts (e.g., a class definition and its docstring) into canonical nodes, compute embeddings and LLM-generated summaries, and write everything into the `KnowledgeStore` protocol. The public entry points are `ingest()` and `ingest_portfolio()`, both exported from `__init__.py`; they accept a `KnowledgeStore`, source root, blob root, and configuration, and raise `IngestionError` with source-file context on failure.

The ingestion pipeline is organized into several cooperating subsystems. Format-specific parsing lives in `handlers.py`, which defines two protocols: `ChunkHandler` (for markdown-like files that split on headings) and `StructuredHandler` (for code files that yield entities and relationships). Concrete implementations include `PythonHandler` (using `ast`), `TypeScriptHandler` and `RustHandler` (using tree-sitter), plus handlers for Terraform, YAML, Bicep, HTML, GraphQL, and PDF. Each handler exposes `supports(path)` and either `chunks()` or `extract()`. After raw extraction, `entity_resolver.py` runs as a pure function — it takes `ExtractedEntity` and `ExtractedRelationship` dataclasses, normalizes names, merges duplicates into `CanonicalEntity` objects, and re-resolves all relationship endpoints to canonical IDs, dropping unresolvable ones. The `semantic_linker.py` adds a fuzzy recall layer: it uses embedding-assisted k-NN to create `related` edges between doc and code nodes that name-based extraction missed, gated by cosine threshold and per-node caps.

Supporting infrastructure includes the `Summarizer` protocol (hidden behind a Parnas-secret in `summarizer.py`), with a concrete `LLMSummarizer` that calls an OpenAI-compatible endpoint and caches results content-addressed per chunk. The `concepts.py` module grounds entity concepts against a curated ontology using `prefLabel`/`altLabel` aliases. Blob storage (`blobs.py`) writes content-addressed embeddings and summaries under `.context-kernel/{embeddings,summaries}/`. The ingester depends on `context_kernel.graph.protocol` for the `KnowledgeStore`, `Entity`, `Relationship`, `EmbeddedChunk`, and `Summary` protocols, on `context_kernel.change_detection` for file walking, and on `context_kernel.scoring` for relevance scoring. It also imports from `context_kernel.source_kinds` to distinguish code from documentation paths, and uses `httpx` (via `_http`) for LLM and embedding API calls.

## Recommended documentation

This scope has 144 code entities across 1 files but no reference documentation. To create one: `/init-reference ingester`

