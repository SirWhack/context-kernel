# Materializer — Reference

How the materialization pass works today. Operational reference for agents and engineers working in `context_kernel/materializer/`.

Contract: [ARCHITECTURE.md](../../ARCHITECTURE.md) §2.3.
Decisions: [ADR-0002](../adr/0002-materialize-agents-md-with-claude-code-bridge.md), [ADR-0010](../adr/0010-pre-commit-hook-regeneration.md), [ADR-0014](../adr/0014-reference-docs-as-authored-root-nodes.md).

## Overview

The Materializer is the sole writer to the materialized tree (THEORY.md invariant 1). It projects the current Graph state into per-scope `AGENTS.md` files and configured cross-cutting views under `.context-kernel/views/`. Every output is a pure function of `(scope, graph_commit, view_spec)` — no side state, no runtime synthesis. Invoked as `ck materialize`.

Two entry points: `materialize()` writes `AGENTS.md` + `CLAUDE.md` bridge for a single scope. `materialize_view()` writes one cross-cutting view file. Both are idempotent — re-running on unchanged Graph state writes nothing.

## The materialize() pipeline

The per-scope pipeline runs these steps in order:

1. **Freshness check** — parse the existing `AGENTS.md` freshness header and compare `graph_commit` + `source_tree_hash` against current values. If both match, skip regeneration (only ensure the `CLAUDE.md` bridge exists).
2. **Pinned block extraction** — extract all `<!-- pinned -->` blocks from the existing `AGENTS.md` before overwriting. Warnings are logged for malformed or duplicate blocks.
3. **Summary retrieval** — call `store.get_summary(scope)` to get the Graph-derived per-scope summary.
4. **Gap detection / reference pointer** — check for an existing reference doc at `docs/reference/<scope-leaf>.md`. If found, render a pointer section. If absent, check code-entity density and render a gap recommendation if above threshold.
5. **Rendering** — assemble the freshness header, summary, and reference/gap sections into the `AGENTS.md` markdown via `render_agents_md()`.
6. **Pinned block merge** — append extracted pinned blocks back onto the freshly rendered output.
7. **Write-if-changed** — write `AGENTS.md` and `CLAUDE.md` bridge only if content differs from what is on disk.

The pipeline returns a list of `Path` objects for every file actually written. This list is consumed by the pre-commit hook ([ADR-0010](../adr/0010-pre-commit-hook-regeneration.md)) to stage changed files.

## Freshness header

Every materialized file starts with a freshness header — an HTML comment block that the FreshnessGate and the Materializer itself parse to decide whether regeneration is needed. Implements THEORY.md invariant 2.

### Format

```
<!-- context-kernel-freshness
graph: <hex-digest>
source-tree: <hex-digest>
materialized: <ISO-8601 UTC timestamp>
-->
```

Three fields: `graph` is the GraphCommit hash (current Graph state identity, per [ADR-0008](../adr/0008-content-derived-graph-commit.md)). `source-tree` is the SHA-256 over the scope's sorted `(relative-path, file-content-hash)` pairs (computed by `source_tree_hash()` in the Ingester's `change_detection.py`). `materialized` is the UTC timestamp of the last materialization.

### Round-trip parse/render

`headers.py` exposes `FreshnessHeader` (a frozen dataclass), `render(header) -> str`, and `parse(text) -> FreshnessHeader | None`. Parse returns `None` for missing or malformed headers — the Materializer treats this as "stale, regenerate." The regex is anchored to the sentinel string `context-kernel-freshness` and tolerates whitespace variation.

### Freshness comparison

The Materializer compares both `graph_commit` and `source_tree_hash`. Both must match for the scope to be considered fresh. `graph_commit` catches Graph-level changes (new entities, updated summaries). `source_tree_hash` catches source-level changes that might not yet be reflected in the Graph (e.g., if ingest ran but the scope had a config change not captured by the Ingester).

## CLAUDE.md bridge pattern

Per [ADR-0002](../adr/0002-materialize-agents-md-with-claude-code-bridge.md), each scope gets a thin `CLAUDE.md` file containing a single line: `@AGENTS.md`. This exploits Claude Code's directory-walking auto-load: when the agent is spawned at any scope, it automatically picks up the `CLAUDE.md` bridge, which imports the canonical `AGENTS.md` content into the system prompt.

The canonical content lives in `AGENTS.md` so it remains readable by any coding agent (Cursor, Aider, Codex), not just Claude Code. The bridge is the only Claude-Code-specific artifact. If another agent adopts a different auto-load filename, the same bridge pattern applies — one import file per supported agent, all pointing at the single-sourced `AGENTS.md`.

`render_claude_md_bridge()` returns `"@AGENTS.md\n"`. The bridge file is always written alongside `AGENTS.md` and is subject to the same write-if-changed idempotency.

## Pinned block semantics

Pinned blocks are the only place hand-edits survive regeneration. They are `<!-- pinned -->` / `<!-- /pinned -->` delimited sections inside per-scope `AGENTS.md` files. The Materializer extracts them before regeneration and merges them back afterward.

### Labels

Blocks can be optionally labeled: `<!-- pinned:label -->`. Labels serve two purposes: identity for dedup, and future positional anchoring. The label must match `\w[\w-]*` (word characters and hyphens).

### Extract behavior

`extract(existing) -> (list[PinnedBlock], list[str])` returns blocks and warnings:

- **Labeled blocks** are deduped: if two blocks share a label, the last one wins and earlier duplicates are discarded with a warning.
- **Unlabeled blocks** are all preserved — no dedup, order maintained.
- **Unpaired tags** (an opening `<!-- pinned -->` without a matching `<!-- /pinned -->`) generate a warning and the content is lost.
- Content within blocks is normalized: leading/trailing blank lines are stripped, internal structure is preserved.

### Merge behavior

`merge(rendered, pinned_blocks) -> str` appends all pinned blocks at the end of the freshly rendered output, each wrapped in its original `<!-- pinned -->` / `<!-- /pinned -->` delimiters. Labeled blocks get `<!-- pinned:label -->` tags. Blocks are separated by blank lines.

### Scope restriction

Pinned blocks are only supported in per-scope `AGENTS.md` files. Cross-cutting views are pure projections with no side inputs — no pinned blocks.

## Cross-cutting views

Views are materialized files under `.context-kernel/views/` that aggregate information across multiple scopes. Configured via `[[materializer.views]]` entries in `.context-kernel/config.toml`. Each view is rendered as a pure function of `(ViewSpec, graph_state)`.

### materialize_view() pipeline

1. **Determine output path** — `index` views write to `.context-kernel/views/<name>.md`. `by-topic` views write to `.context-kernel/views/by-topic/<tag>.md`.
2. **Freshness check** — compare the existing file's `graph_commit` against the current value. Views use a sentinel `source_tree_hash` (64 zeroes) because they aggregate across scopes and have no single source tree.
3. **Render** — dispatch to `render_view(spec, store)` which routes by `spec.kind`.
4. **Write-if-changed** — same idempotency as per-scope files.

### Index view

`_render_index(store)` lists all scopes with their Graph-derived summaries, sorted by scope path. Each scope gets an H2 heading, the summary markdown, and a pointer arrow to its `AGENTS.md`. If no scopes are materialized, renders a "No scopes materialized yet" placeholder.

### By-topic view

`_render_by_topic(store, tag)` groups entities and summaries matching a configured tag (case-insensitive substring match). For each matching scope: if entities match, they are listed with name, kind, and description. If only the scope summary matches, the summary is shown as a fallback. Output is sorted by scope path. If nothing matches, renders a "No matches found" placeholder.

The tag is taken from `spec.params["tag"]` in the ViewSpec configuration.

## Gap detection and reference pointers

Per [ADR-0014](../adr/0014-reference-docs-as-authored-root-nodes.md), the Materializer detects documentation gaps and renders pointers to existing reference docs.

### Reference pointer

`find_reference_doc(scope, tree_root)` checks whether `docs/reference/<scope-leaf>.md` exists. If found, `render_reference_pointer()` adds a "Reference documentation" section to `AGENTS.md` with a relative link to the reference doc. This creates the two-layer entry point described in ADR-0014: AGENTS.md is the index card, the reference doc is the chapter.

### Gap recommendation

When no reference doc exists, `detect_documentation_gap()` counts code entities (kind in `{module, class, function}`) for the scope. If the count exceeds `gap_detection_threshold` (default: 10), a "Recommended documentation" section is rendered advising the operator to run `/init-reference <subsystem>`. The recommendation surfaces through the same channel the agent already reads (CLAUDE.md bridge imports AGENTS.md), closing the loop: the kernel identifies its own documentation gaps.

## Write-if-changed idempotency

`_write_if_changed(path, content)` compares the proposed content against the file already on disk. If identical, no write occurs and the function returns `False`. This is what makes `ck materialize` safe to run on every commit via the pre-commit hook — unchanged scopes cost only the comparison, not a filesystem write. Parent directories are created on demand via `mkdir(parents=True, exist_ok=True)`.

## Configuration

All materializer config lives in `MaterializerConfig` (loaded from `.context-kernel/config.toml` `[materializer]` section):

| Key | Default | Purpose |
|---|---|---|
| `views` | `[]` (empty list) | List of ViewSpec entries to materialize |
| `gap_detection_threshold` | `10` | Minimum code-entity count to trigger a gap recommendation |

Each view entry in config.toml:

```toml
[[materializer.views]]
name = "index"
kind = "index"
params = {}

[[materializer.views]]
name = "testing"
kind = "by-topic"
params = { tag = "test" }
```

## Interfaces

### What the Materializer reads from the Graph

The Materializer consumes these KnowledgeStore protocol methods:

- `graph_commit() -> GraphCommit` — current Graph state hash; embedded in every freshness header. Compared against existing headers to decide whether regeneration is needed.
- `get_summary(scope) -> Summary | None` — the per-scope summary for rendering into `AGENTS.md`. Produced by the Ingester at ingest time (per [ADR-0007](../adr/0007-per-scope-summaries-at-ingest.md)).
- `list_summaries() -> list[Summary]` — all scope summaries; used by the index view and by-topic view.
- `list_entities_by_scope() -> dict[ScopePath, list[Entity]]` — scope-to-entity mapping; used by gap detection and by-topic view filtering.

The Materializer never calls `upsert()`, `get_entity()`, `get_neighbors()`, `get_embedding()`, or `search_similar()`. It is a read-only consumer of the Graph.

### What the Materializer reads from the Ingester

`source_tree_hash(scope_dir, tree_root)` from `context_kernel.ingester.change_detection` — the deterministic SHA-256 over a scope's source files. Used in the freshness check alongside `graph_commit`. This is a function call, not Graph state — the Materializer computes it directly from the filesystem.

### Error surface

`MaterializationError(message, scope, graph_commit)` carries scope and Graph context for structured error reporting. Raised when rendering or writing fails. The AgentCLI surfaces this as an exit code with a human-readable message.

## Relationships to other subsystems

- **Graph** — the Materializer is a read-only consumer. Calls `graph_commit()`, `get_summary()`, `list_summaries()`, and `list_entities_by_scope()`. Never writes. See [docs/reference/graph.md](./graph.md).
- **Ingester** — produces the Graph state the Materializer projects. The Materializer also imports `source_tree_hash()` from the Ingester's change detection module for freshness comparison. See [docs/reference/ingester.md](./ingester.md).
- **FreshnessGate** — triggers the Materializer via the pre-commit hook (`ck ingest && ck materialize --all`). The FreshnessGate parses the same freshness headers the Materializer writes. See ARCHITECTURE.md §2.4.
- **AgentCLI** — dispatches `ck materialize` to the Materializer; prints written paths to stdout for the pre-commit hook to stage. See ARCHITECTURE.md §2.6.
- **ConfigStore** — provides `MaterializerConfig` with the views list and gap detection threshold. Loaded at the start of every `ck` invocation. See ARCHITECTURE.md §3.1.
- **Types** — consumes `GraphCommit`, `Sha256`, `ScopePath`, and `ViewSpec` from `context_kernel.types`. Consumes `Entity`, `Summary` from `context_kernel.graph.protocol`.

## Current limitations

- **No positional anchoring for pinned blocks.** Pinned blocks are always appended at the end of the rendered output. Future work could use labels to place blocks at specific positions within the generated content.
- **Views use a sentinel source_tree_hash.** Cross-cutting views set `source_tree_hash` to 64 zeroes because they aggregate across scopes. This means view freshness is checked only against `graph_commit`, not against individual scope source trees.
- **By-topic matching is substring-only.** `_match()` does case-insensitive substring search. No regex, no semantic matching, no tag taxonomy. A tag of "test" matches "testing", "contest", and "latest". Acceptable for v1; may need refinement as view usage grows.
- **No view-level pinned blocks.** Views are pure projections. There is no mechanism for hand-authored content to survive view regeneration. If this is needed, it would require extending the pinned block semantics to view files.
- **Gap detection counts entities, not complexity.** The threshold is a simple count of code entities (module, class, function). A scope with 15 trivial helper functions triggers the same recommendation as a scope with 15 deeply interacting classes. No weighting by relationship density or entity depth.
- **CLAUDE.md bridge is Claude-Code-only.** No bridge files are generated for other coding agents. When Cursor or another agent gains auto-load behavior, the bridge pattern would need a new renderer per agent (per ADR-0002).
- **No parallel scope materialization.** `materialize()` processes one scope at a time. The caller (AgentCLI) iterates scopes sequentially. On large portfolios, this could become a bottleneck — though the write-if-changed optimization means only changed scopes incur real work.
