# Context Kernel — Design Doc (v0)

Status: draft, pre-implementation. Last revised 2026-05-23.

## Thesis

A coding agent (Claude Code, Cursor, etc.) spawned at a portfolio root needs *curated, scope-appropriate context* to work well across multiple projects. Today the agent compensates by grepping aggressively and reading too much. The Context Kernel produces and maintains that context as a hierarchy of LLM-summarized, entity-graph-linked **plain files** the agent reads with the tools it already has (`Read`, `Grep`, `Glob`).

A narrow **MCP server** sits alongside the file tree as a discovery/orientation surface — two read-only tools that point the agent at the right materialized files for a given question. The MCP server is a pure read-through over the materialized tree; it has no independent state and cannot mutate anything.

Primary consumer: the agent. Secondary consumer: the human (via Obsidian on the same files).

## Design principles (load-bearing)

These are not aesthetic preferences — each maps to a concrete decision below.

- **The filesystem is the agent's primary interface** (Unix / Plan 9 lineage). Every coding agent already speaks `Read`/`Grep`/`Glob`. The agent's normal working loop is reading materialized files; MCP is a narrow orientation aid, not a peer interface or replacement.
- **No stateful service.** Where MCP exists, it is a *pure function* of the on-disk materialized tree. It holds no independent index, cache, or session state. Restart it and nothing is lost; remove it and the file tree still answers every question (slower).
- **Deep modules** (Ousterhout): one thin interface, large hidden capability. The interface is the `AGENTS.md` tree on disk (plus two thin MCP tools that read from it); the entire pipeline (graph, summaries, embeddings, regeneration) hides behind it.
- **Information hiding** (Parnas): every module hides a decision likely to change. Backend, model, materialization policy, MCP transport are all hidden.
- **Essential vs. accidental complexity** (Moseley & Marks): the essential problem is *right-scoped knowledge for the agent*; everything else is implementation that must be hide-able. Mutable state is minimized.
- **Define errors out of existence** (Ousterhout): stale context is not detected via a check someone has to remember to run — regeneration is a *precondition* of the read, enforced by the harness hook. The MCP server invokes the same check before returning any chunk.
- **Work belongs in materialization, not at query time.** Both the file reads and the MCP calls return *pre-materialized* content. MCP does no on-the-fly summarization, no live LLM calls, no graph traversal at request time. If a capability seems to require runtime synthesis, the answer is to materialize a new view ahead of time.

## The deep module: the `AGENTS.md` tree

The agent's primary read interface is the **tree of `AGENTS.md` files** on disk, accessed via the agent's existing `Read`/`Grep`/`Glob` tools. The files are plain markdown. Behind them lives an entity graph, a hierarchical summary tree, content-addressed embeddings, and a regeneration pipeline. None of that surfaces in the interface.

Contract:

- The agent reads the `AGENTS.md` at its current working scope. That is the normal access pattern.
- Each `AGENTS.md` is a **materialized view**, never a source of truth. The graph is the source of truth.
- Each `AGENTS.md` ends with a `## See also` section: a small set of links to *other* materialized files (sibling scopes, cross-cutting views, raw sources) the agent can `Read` if the current scope doesn't answer the question. The graph becomes navigable as a filesystem, not queryable as an API.
- Hand edits land only inside `<!-- pinned -->` blocks, which become *inputs* to the next regeneration. Free-form edits outside those blocks are overwritten.
- Every file carries a freshness header (see Staleness invariant).

## The MCP server: orientation surface

A narrow stdio MCP server exposes two read-only tools. Both are pure functions of the on-disk materialized tree — they read the same files the agent could read directly, but save the agent from having to know the tree layout to answer "what is this?" or "where is X discussed?"

**Tools:**

1. `overview(scope_path, max_tokens=2000) → markdown`
   Hierarchical context for `scope_path`: the top-of-tree summary at that scope, key entities, and file-path pointers to deeper materialized views. The "I just spawned in this repo — what is this?" call.

2. `find(query, scope_path=".", max_tokens=2000) → markdown`
   Semantic lookup over materialized summaries (embeddings live in `.context-kernel/embeddings/`, content-addressed). Returns the most relevant chunks plus the source file paths they came from. Replaces blind grepping when the agent has a question that doesn't map to an obvious file.

**Both tools return markdown that includes the file paths they sourced from**, so the agent can follow up with `Read` for full depth. MCP points; files deliver.

Constraints (enforced by the implementation, not just by convention):

- No write tools. Mutation goes through the `ck` operator CLI; the agent cannot invoke it via MCP.
- No tool may return synthesized text not derivable from the on-disk materialized tree. If MCP can answer it, a file could too — the difference is whether the agent has to navigate to find it.
- Before returning, the server invokes the same `ck check` staleness gate as the file hook. The MCP server cannot return stale chunks.
- No long-running daemon. Stdio transport, spawned per session.

## How cross-cutting questions are answered

"What other projects touch auth?" has two equivalent paths, both backed by **pre-materialized views**:

1. Agent reads `.context-kernel/views/by-topic/auth.md` directly (knows the path from the root `AGENTS.md`'s `## See also`).
2. Agent calls `find("auth", scope_path=".")` and gets back chunks pointing at the same file.

The materialized views are the source either way:

```
.context-kernel/views/
├── by-topic/
│   ├── auth.md              [list of every scope tagged auth + 1-line summaries]
│   ├── observability.md
│   └── ...
├── by-entity/
│   └── <entity-id>.md       [where an entity appears across the portfolio]
└── recent-changes.md        [rolling journal of what's changed and where]
```

These views are generated by the `ck materialize` pass — same pure function, same content addressing, same freshness header. The set of views is **configurable, not hard-coded**. Each view is a `(graph_query, template) → file` spec in `.context-kernel/config.toml`. Adding a view is a config change, not a code change.

This is where the system's expressive power lives. The MCP `find` tool gets more useful as more views exist — but never *requires* a view to exist, because it can fall back to semantic lookup over the per-scope summary chunks.

## The secrets (Parnas list)

What changes, and what hides it:

| Likely to change | Hidden behind |
|---|---|
| Graph backend (fast-graphrag → LightRAG → other) | `KnowledgeStore` protocol |
| Summarization model (Qwen3-14B → 32B → cloud) | `Summarizer` interface; prompts in config, not code |
| Embedding model | `Embedder` interface |
| Materialization policy (when/how to regenerate) | `Materializer`, single owner |
| Entity resolution / cross-project merge rules | `EntityResolver` — explicit human reviewer in the loop |
| The set of cross-cutting views | `views = [...]` in config; adding a view is config-only |
| MCP transport (stdio v1, maybe streamable HTTP later) | Tool surface stays the same; transport is a launcher concern |

What does **not** change without a major version bump (these are invariants on **Context Kernel's interface to the consuming agent** — not blanket statements about your stack; your editor is free to use other MCP plugins, agent teams, or any other capability without conflict):

- The agent's primary read surface is files (`Read`/`Grep`/`Glob` over the `AGENTS.md` tree and `.context-kernel/views/`).
- The MCP server, where present, is read-only and a pure function of the on-disk materialized tree. No write tools. No independent state. No runtime synthesis.
- Materialized files are never authoritative; the graph is.
- Every materialized file carries a verifiable freshness header.

## Data model

```
~/Code/<portfolio-root>/
├── .context-kernel/                    [opaque to humans and agents]
│   ├── graph/                          [the one mutable surface — disciplined]
│   ├── embeddings/<sha256>.bin         [content-addressed, immutable]
│   ├── summaries/<sha256>.md           [content-addressed, immutable]
│   ├── views/                          [materialized cross-cutting views]
│   ├── log.md                          [append-only journal]
│   └── config.toml
├── AGENTS.md                           [materialized, public, top-of-tree]
├── obsidian-vault/                     [symlinks into materialized tree — optional human view]
├── project-a/
│   ├── AGENTS.md                       [materialized, scope = project-a/]
│   └── src/auth/
│       └── AGENTS.md                   [materialized, scope = project-a/src/auth/]
└── papers/raptor.pdf                   [raw source]
```

**Mutable state is concentrated in one place** (the graph). Everything derivable is content-addressed and immutable: re-deriving is cheap, GC is a sweep, no synchronization problem.

## The staleness invariant

Every materialized `AGENTS.md` starts with:

```
<!-- context-kernel
     graph: abc1234
     source-tree: def5678
     generated: 2026-05-23T14:22:00Z
-->
```

Before any read of a materialized file — whether via the agent's `Read` tool or via an MCP call — a freshness check runs:

- **Direct file read**: `PreToolUse` hook invokes `ck check <path>`. Mismatch → run `ck materialize <scope>` first, then allow the read.
- **MCP call**: server invokes the same `ck check` on every file it's about to return chunks from. Mismatch → regenerate before returning.

The agent literally cannot read or receive a stale chunk. Drift is not a class of bug we have to remember to handle.

Trigger model: **pull-based**, JIT regeneration on read. No daemon, no file watcher. The first read after a large source change pays the regeneration cost; subsequent reads are free.

## The v1 surface

`ck` is an **operator CLI**, never invoked by the agent. The agent's surface is files (primary) plus the MCP server's two tools (orientation).

Operator commands:

- `ck ingest [path]` — read sources (code + markdown + PDFs) within `path`, update the graph, write content-addressed embeddings and summaries. Idempotent. Incremental (via fast-graphrag's upsert algorithm).
- `ck materialize [scope]` — regenerate the materialized tree (`AGENTS.md` at `scope` + ancestors, plus any affected views) from the current graph state. Pure function of `(scope, graph_commit, view_spec)`.
- `ck check [path]` — verify the freshness header on `<path>/AGENTS.md` (or any materialized file). Exit non-zero if stale. Optional `--fix` to materialize in place.
- `ck mcp` — run the stdio MCP server. Invoked by the agent harness's MCP launcher, not interactively.

Agent-facing surfaces:

- The `AGENTS.md` tree and `.context-kernel/views/`, read with `Read`/`Grep`/`Glob`.
- The MCP server's `overview` and `find` tools, registered with the harness.

Hook: `PreToolUse` on `Read` of any `**/AGENTS.md` or `.context-kernel/views/**`, runs `ck check --fix`. From the agent's perspective, files are simply always fresh. The hook is harness machinery; it is not part of the agent's interface.

## Non-goals (by design, not deferral)

These are **permanent architectural commitments**, not v1 simplifications. They apply to *Context Kernel's interface to the consuming agent*. They say nothing about the rest of the agent's environment, which may use other MCP plugins, agent teams, remote control, or any other capability without conflict.

- **No mutating MCP tools.** The agent cannot change Context Kernel state via MCP. All mutation goes through the `ck` operator CLI.
- **No stateful MCP server.** The MCP server holds no independent index, cache, or session state. It is a pure read-through over the on-disk materialized tree.
- **No runtime synthesis from MCP.** Tools return pre-materialized content only. No live LLM calls, no on-the-fly graph traversal in response to a query. Work happens in materialization, ahead of time.
- **No hand-edits as source of truth.** Free-form edits outside `<!-- pinned -->` blocks are overwritten without warning. The graph is authoritative.

Deferred (may arrive later):

- **Obsidian plugin** — the vault is a symlink farm; plugin polish is product work, not thesis work.
- **Cross-project entity merging** — per-project namespaces only in v1. Cross-project linking is v2, gated on observing natural seams.
- **Cloud LLM fallback** — local-only on the 7900 XTX. Add a seam, but don't fill it.
- **Push-based / watcher regeneration** — pull-based JIT is simpler and "errors out of existence" is cleaner. Revisit if first-read latency proves intolerable.
- **HTTP MCP transport** — stdio is enough for one editor at a time. Streamable HTTP unlocks multi-editor / remote scenarios; same tool surface.
- **Eval harness** — needed before claiming the system works; not needed before the system exists. v1.5.

## V1 deliverable

Demoable in 90 seconds:

1. `cd ~/Code/model-time` (the dogfood project).
2. `ck ingest .` populates `.context-kernel/`.
3. `ck materialize .` writes `AGENTS.md` at root + every relevant subdirectory + the starter views.
4. Spawn Claude Code in the root (MCP server auto-launched by the harness).
5. Ask "what is this codebase?" → agent calls `overview(".")`, gets the curated answer in one tool call.
6. Ask a cross-cutting question ("which scopes deal with summarization?") → agent calls `find(...)`, gets pointers, then `Read`s the named files.
7. Edit a source file, ask again, show the agent transparently gets a freshly-regenerated answer (freshness gate triggered on both file read and MCP call).

## Open questions for v1

- **Which views ship in v1.** The view system is the expressive surface that complements MCP. v1 needs a small starter set — likely `by-topic/<tag>.md`, `recent-changes.md`, and `index.md` (catalog of every materialized file). Anything more is config the user adds.
- **Scope of "scope"**: directory-based is the obvious mapping, but a `src/auth/` directory and a `docs/auth-design.md` are the same logical scope. Likely need a `scope.toml` mechanism per directory to override. Defer until concrete pain.
- **Pinned-block syntax and merge semantics**: how exactly does `<!-- pinned -->` content flow into the next regeneration prompt? Needs prototyping. What happens on unpinned edits — silent overwrite or refuse-and-prompt?
- **First-read latency budget**: if regenerating a deep subtree on the agent's first read takes 60+ seconds, the pull-based decision is wrong. Need to measure on a real project in the first 3 days of v1 work.
- **What's in an `AGENTS.md` vs. linked to from one**: token budget per file. Probably ~2k tokens of summary + a `## See also` section pointing to deeper scopes / views / raw sources. Tune with data.
- **MCP tool prompts and response shape**: how the two tools describe themselves to the agent in the MCP manifest, and what the markdown response looks like (headings, citations, token budget). Needs prototyping with a real agent in the loop.
- **Harness portability**: the PreToolUse hook works for Claude Code; the MCP server works for any MCP-speaking agent. Cursor's hook model is different; CI agents have neither. If non-Claude-Code support matters in v1, fallback for freshness is a git pre-commit hook that runs `ck materialize` — slower, but works anywhere.
