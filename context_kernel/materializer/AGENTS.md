<!-- context-kernel-freshness
graph: 4828895ec2ab8c46292fc502e3c028e8b68915c679ff81f463cf9148983976a0
source-tree: 42b72f27a422065bf0e956386035b71d97263983af6bc23509961a754468901e
materialized: 2026-05-27T21:35:43Z
-->

The materializer is the sole writer to the materialized tree — it transforms the in-memory knowledge graph into the on-disk AGENTS.md and CLAUDE.md files that agents and engineers read. Its core responsibility is enforcing invariant 1 from ARCHITECTURE.md §2.3: the materialized tree must always be a deterministic, up-to-date reflection of the graph at a given commit. The public entry points are `materialize()` (writes AGENTS.md + CLAUDE.md bridge for a single scope) and `materialize_view()` (writes cross-cutting views under `.context-kernel/views/`). Both accept a `KnowledgeStore` protocol, a `ScopePath` or `ViewSpec`, a tree root path, and a `MaterializerConfig`, and return the list of file paths written.

Internally, the materializer is organized into several focused submodules. `templates.py` provides `render_agents_md()` and `render_claude_md_bridge()` which produce the canonical markdown content, prepending a `FreshnessHeader` (from `headers.py`) that encodes the graph commit hash, source tree hash, and timestamp — this implements invariant 2 and enables staleness detection. `pinned.py` handles the `<!-- pinned -->` block mechanism, the only place hand-edits survive regeneration: `extract()` pulls pinned blocks from an existing file, and `merge()` re-inserts them into freshly rendered output. `reference_docs.py` provides `find_reference_doc()`, `detect_documentation_gap()`, and rendering helpers for linking to or recommending reference documentation per ADR-0014. `views.py` implements `render_view()` which dispatches to `_render_index()` or `_render_by_topic()` based on the `ViewSpec`. All write operations go through the private `_write_if_changed()` helper, which avoids unnecessary disk I/O by comparing content before writing.

The materializer depends on the `context_kernel.graph.protocol` for the `KnowledgeStore` and `Entity` types, and on `context_kernel.types` for `ScopePath`, `Sha256`, `GraphCommit`, and `ViewSpec`. It also imports `source_tree_hash` from the ingester's change detection module. Errors are reported via `MaterializationError`, a custom exception that carries the failing scope and graph commit for diagnostic context. The overall design follows a functional pipeline pattern: each submodule is a collection of pure-ish functions that transform data, with the `__init__.py` module orchestrating the full materialization flow.

## Recommended documentation

This scope has 31 code entities across 1 files but no reference documentation. To create one: `/init-reference materializer`

