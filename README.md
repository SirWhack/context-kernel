# Context Kernel

A curated-context layer that sits between a portfolio of projects and the coding agents working over it. **In planning / pre-implementation** — no code yet; the documentation is the working theory.

## The thesis

> As an agentic engineer building a portfolio of projects, context at one altitude doesn't compose into context at another — from cross-project patterns down to an individual Python file — so the agents I use are limited in the context they hold. Therefore I am building a Context Kernel, shaped like a knowledge graph as the source of truth with markdown views the agent walks, because graphs relate the data together from both ends of the altitude tree.

From [`THEORY.md`](./THEORY.md). The full theory document covers the shape (with a C4 system-context diagram), the four invariants, the non-goals, and the open questions that v1 must resolve through measurement.

## Shape

```
~/Code/<portfolio-root>/
├── .context-kernel/              ← opaque pipeline: graph, embeddings, summaries, views, log
├── AGENTS.md                     ← materialized, top-of-tree
├── CLAUDE.md                     ← @AGENTS.md bridge (per ADR-0002)
├── project-a/
│   ├── AGENTS.md                 ← materialized at scope
│   └── src/auth/AGENTS.md
└── project-b/
    └── ...
```

A **knowledge graph** is the source of truth. An **ingestion pass** derives it from the portfolio's code and docs. A **materialization pass** projects the graph into a tree of markdown files (`AGENTS.md` at every scope plus cross-cutting views under `.context-kernel/views/`) that agents read with `Read` / `Grep` / `Glob` — the tools every coding agent already speaks. A narrow read-only **MCP server** (`overview`, `find`) points agents at the right materialized files for orientation queries. A **freshness gate** before every read guarantees the agent cannot receive a stale chunk.

## Operator surface

`ck` is the operator CLI — never invoked by the agent directly in v1, only via Bash:

```
ck ingest [path]       # read sources, update the graph, write content-addressed blobs
ck materialize [scope] # project the graph into the markdown tree
ck check [path]        # verify a materialized file's freshness header
ck mcp                 # stdio MCP server with overview / find tools
```

## Status

| Area | State |
|---|---|
| Thesis ([`THEORY.md`](./THEORY.md)) | Accepted; falsifiability test is the v1 dogfood demo |
| Architecture ([`ARCHITECTURE.md`](./ARCHITECTURE.md)) | Settled — 8 modules (6 §2 + 2 §3), 6 deferred mechanisms |
| Plan ([`PLAN.md`](./PLAN.md)) | 13-slice v1 build sequence; tracer bullet ready to pick up |
| Decisions ([`docs/adr/`](./docs/adr/)) | 6 ADRs (Naur docs, `AGENTS.md` bridge, pull-based JIT, LightRAG, agent-as-operator, files-as-primary) |
| Code | None yet |

## Reading order

For a new collaborator or fresh agent session:

1. [`THEORY.md`](./THEORY.md) — thesis, shape, invariants, non-goals, open questions
2. [`CONTEXT.md`](./CONTEXT.md) — glossary of domain terms (Portfolio, Altitude, Scope, Materialized file, Freshness gate, etc.)
3. [`ARCHITECTURE.md`](./ARCHITECTURE.md) — module model, settled tradeoffs, deferred mechanisms, data classes
4. [`docs/adr/`](./docs/adr/) — recorded decisions with reasoning
5. [`PLAN.md`](./PLAN.md) — the 13-slice v1 build sequence
6. [`CLAUDE.md`](./CLAUDE.md) — operating rules for any agent working in this repo
7. [`docs/design.md`](./docs/design.md) — pre-Naur design notes; most content has migrated to `THEORY.md` and ADRs but it remains the most concrete reference for the v1 surface

## Naur-aligned documentation

This repo uses a documentation structure informed by Peter Naur's *Programming as Theory Building* (1985). The theory comes first; the code is a translation of it. The discipline is enforced by [`CLAUDE.md`](./CLAUDE.md) and a set of `/grill-*` skills that interrogate the engineer through each document. There is intentionally no overlap between documents: `THEORY.md` names concepts; `CONTEXT.md` defines them; ADRs record the decisions; `ARCHITECTURE.md` describes how the system is structured; `PLAN.md` sequences what to build.

## Hardware target

Local-only on a 7900 XTX (24GB) under ROCm/WSL2. No cloud LLM fallback in v1, though the `Summarizer` and `Embedder` seams are in place for one later.

## License

[MIT](./LICENSE) © Sam Wynn
