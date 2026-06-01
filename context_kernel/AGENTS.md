<!-- context-kernel-freshness
graph: ce4c30de6021574f8be593ca3ef2c62ccfde5e39118e774477c1d6d76f0f9abe
source-tree: 05ab1c1f9ae1dd06201d89cdc0f168dd20842c0d47d3396f58d8bdfa8f7dfd0f
materialized: 2026-06-01T01:08:19Z
-->

The context_kernel scope is the operational backbone of the model-time system, responsible for orchestrating the lifecycle of knowledge graph construction, freshness enforcement, and materialization. It acts as the central coordinator that ingests source code into a structured knowledge graph, detects changes to determine what needs re-ingestion, and produces formatted views for LLM consumption. The scope enforces critical invariants, most notably that no stale data is ever served (invariant 2) and that unchanged source files are never re-processed (invariant 4).

The public API surface is primarily accessed through the `agent_cli.py` module, which provides the `ck` command-line entrypoint via its `main()` function. This dispatches to four subcommands: `ingest`, `materialize`, `check`, and `mcp`. Configuration is loaded by `config_store.py`, which parses `.context-kernel/config.toml` into typed dataclasses (`Config`, `ProjectSpec`, `IngesterConfig`, `MaterializerConfig`, `OrientationConfig`). The `freshness_gate.py` module enforces read-boundary integrity by raising `StaleReadError` when regeneration fails, while `change_detection.py` determines which files need re-ingestion through `source_tree_hash()`, `changed_since()`, and git-aware functions like `commit_of()`, `churn()`, and `size()`.

Internally, the scope is organized around several key modules with clear separation of concerns. `scoring.py` is a pure, I/O-free module that centralizes all confidence and relevance calculations, implementing ADR-0015 through ADR-0021 with functions like `confidence()`, `authority()`, `edge_weight()`, and `node_drift()`. `source_kinds.py` provides shared classification helpers (`is_code_path()`, `is_ops_path()`) that ensure consistency across ingester, scoring, and query-time source selection. `types.py` defines cross-module domain primitives (`ViewSpec`, `GraphCommit`, `Sha256`, `ScopePath`) with no behavior. The `operational_journal.py` module maintains an append-only log at `.context-kernel/log.md` via `JournalEntry` and `append()`, while `logging.py` provides structured logging through `configure()` and `invocation_id()`.

The scope depends on several internal modules for its operation. It imports from `context_kernel.graph.protocol.KnowledgeStore` for graph storage, `context_kernel.materializer.headers.parse` for materialization, and `context_kernel.scoring.ScoringConfig` for configuration resolution. External dependencies include standard library modules (`argparse`, `hashlib`, `subprocess`, `tomllib`, `pathlib`, `dataclasses`) and `uuid` for generating unique identifiers. The design follows a modular architecture where each module has a single, well-defined responsibility, with `scoring.py` serving as the pure computation core that other modules call rather than inlining scoring logic themselves.

## Recommended documentation

This scope has 67 code entities across 1 files but no reference documentation. To create one: `/init-reference context_kernel`

