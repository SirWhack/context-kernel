<!-- context-kernel-freshness
graph: ce4c30de6021574f8be593ca3ef2c62ccfde5e39118e774477c1d6d76f0f9abe
source-tree: 07d89a902f06c1afefd23a005b2f19b189e1e6b218a0e856df5a5529b585373e
materialized: 2026-06-01T01:08:19Z
-->

This scope handles the **reference documentation** for the model-time subsystem of Context Kernel. It defines the public contracts, domain types, and architectural invariants that govern how the system ingests source code, builds a knowledge graph, and materializes orientation files like AGENTS.md and CLAUDE.md. The scope's primary responsibility is to document the interfaces and design decisions that other subsystems depend on, serving as the authoritative specification for the model-time pipeline.

The key interfaces are defined in `context_kernel/graph/protocol.py`, which exposes the `KnowledgeStore` protocol — a backend-agnostic shape with nine read methods (`get_entity`, `get_neighbors`, `get_summary`, `search_similar`, etc.) and a single write method (`upsert`) restricted to the Ingester. Domain primitives live in `context_kernel/types.py`, including `ViewSpec`, `GraphCommit`, `Sha256`, and `ScopePath`. The `ConfigStore` in `context_kernel/config_store.py` loads `.context-kernel/config.toml` at startup, providing `ProjectSpec`, `IngesterConfig`, `MaterializerConfig`, and `OrientationConfig` dataclasses. The `FreshnessGate` in `context_kernel/freshness_gate.py` enforces invariant 2 ("no stale serve") by raising `StaleReadError` when materialized files are out of date.

Internally, the scope documents several design patterns. The `KnowledgeStore` protocol hides the LightRAG backend behind a thin seam, with `search_similar()` performing hybrid embedding search combining vector similarity and keyword matching. The Materializer is the sole writer to the materialized tree, producing files as pure functions of `(scope, graph_commit, view_spec)` with no side state. The `FreshnessHeader` in `context_kernel/materializer/headers.py` tracks staleness via graph commit hash, source tree hash, and materialization timestamp. Handler classes like `PythonHandler`, `TypeScriptHandler`, and `MarkdownHandler` in `context_kernel/ingester/handlers.py` separate LLM-dependent chunking from deterministic code extraction.

This scope depends on `context_kernel.scoring.ScoringConfig` and `context_kernel.types.ViewSpec` from sibling modules, and imports `KnowledgeStore` from the graph protocol. It connects to the change detection system via `source_tree_hash()` and to the materializer's header parsing. The reference docs themselves are authored (not auto-generated) and serve as root nodes for subsystem understanding, filling gaps between graph-derived summaries and operational narrative.

## Recommended documentation

This scope has 35 code entities across 1 files but no reference documentation. To create one: `/init-reference reference`

