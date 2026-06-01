<!-- context-kernel-freshness
graph: ce4c30de6021574f8be593ca3ef2c62ccfde5e39118e774477c1d6d76f0f9abe
source-tree: bd59ed778ed2af11baf0c777de382b1f8e967fc058c0c7ae82792a2ebb8b3bd9
materialized: 2026-06-01T01:08:20Z
-->

The test suite for the context_kernel validates the entire ingestion, materialization, and orientation pipeline against real and mocked backends. It exercises the core data flow: source files are parsed by language-specific handlers (PythonHandler, TypeScriptHandler, MarkdownHandler, BicepHandler), chunked, summarized via LLM (with a _FakeSummarizer providing canned entities for deterministic tests), and persisted as entities, relationships, and embeddings. The tests then verify that the materializer correctly renders views from this graph, that the orientation server can assemble and rank results, and that change detection and drift scoring work against real git repositories.

Key test modules mirror the production architecture. test_ingester.py (1414 LOC) is the largest, covering handler support detection, extraction, summarizer parsing, change detection, blob storage, project namespacing, logging, and contradiction detection — all using the _FakeSummarizer mock to avoid LLM calls. test_materializer.py (772 LOC) tests FreshnessHeader round-tripping, PinnedBlock extraction and merging, template rendering (agents.md, claude.md), and full materialize_view integration. test_drift.py (265 LOC) creates temporary git repos to test commit_of, churn, size, and the edge_drift composition, then verifies that ingest scoring passes correctly. test_scoring.py (346 LOC) is a pure unit test suite for confidence, relevance, proximity, centrality, and drift formulas, using a simple Rel namedtuple.

The test infrastructure relies on conftest.py, which provides a session-scoped embedder fixture backed by a real llama-server process, and resets the context_kernel logger between tests to prevent state leakage. The tests import heavily from the production codebase — graph protocols (Entity, Relationship, Summary, SearchResult, EmbeddedChunk), ingester handlers and blobs, change detection, materializer headers and templates, orientation server tools, and config types — but avoid mocking the graph store itself, instead testing against in-memory or temporary file-based implementations. This design gives high confidence that the integration between components works correctly while keeping test execution fast and deterministic.

## Recommended documentation

This scope has 259 code entities across 1 files but no reference documentation. To create one: `/init-reference tests`

