<!-- context-kernel-freshness
graph: ce4c30de6021574f8be593ca3ef2c62ccfde5e39118e774477c1d6d76f0f9abe
source-tree: dfdf933cfdc90e1f02559f53979563ec3e2518e46a501adc0bf9af7bd98470f0
materialized: 2026-06-01T01:08:20Z
-->

This scope owns the **documentation materialization pipeline** — the read-side of Context Kernel that transforms a knowledge graph into human-readable markdown files. Its primary responsibility is enforcing **invariant 2 ("no stale serve")** via the `FreshnessGate`, which intercepts every read of a materialized scope file and raises `StaleReadError` if regeneration itself fails. The materializer is the sole writer of `AGENTS.md`, `CLAUDE.md` bridge files, and cross-cutting view files under `.context-kernel/views/`, and it guarantees idempotent regeneration so that hand-edits survive only inside `<!-- pinned -->` blocks.

The public API surface centers on three key interfaces. The `materialize_view` function in `materializer/__init__.py` accepts a `ViewSpec`, `KnowledgeStore`, tree root, and config, returning the list of paths written. The `render_view` function in `materializer/views.py` produces the markdown string for a single view specification. The `FreshnessGate.check` function validates that a scope's materialized content matches its current graph commit before serving it. The `PinnedBlock` class, along with `extract` and `merge` functions in `materializer/pinned.py`, handles the only mechanism by which operator edits survive regeneration — extracting `<!-- pinned -->` blocks before overwriting and re-inserting them afterward.

Internally, the materializer uses a **write-if-changed** strategy (`_write_if_changed`) to avoid unnecessary filesystem churn. It produces two kinds of cross-cutting views: an **index view** listing all scopes with their Graph-derived summaries, and a **by-topic view** grouping entities by configured tags with case-insensitive matching. The `OperationalJournal` provides an append-only log at `.context-kernel/log.md` for tracking materialization events with scope, graph_commit, duration_ms, and files_written. The `FreshnessGate` logs hits and misses with scope and graph_commit identifiers, and the stale/current commit comparison.

This scope depends on the `KnowledgeStore` protocol from `context_kernel/graph/protocol.py` for reading graph data, the `source_tree_hash` function from `context_kernel/change_detection` for staleness detection, and the `parse` function from `context_kernel/materializer/headers` for freshness header format. It also imports from `ConfigStore` for materializer configuration including view specifications and summary target token budgets. The `MaterializationError` class provides typed error context with scope and graph_commit information for failure reporting.

## Recommended documentation

This scope has 21 code entities across 1 files but no reference documentation. To create one: `/init-reference slices`

