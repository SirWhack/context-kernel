# Plan — Context Kernel

The v1 build sequence for Context Kernel. The thesis in [THEORY.md](./THEORY.md) is accepted; scope is cut by [ARCHITECTURE.md](./ARCHITECTURE.md). This file sequences the build — it does not relitigate scope.

Produced by `/grill-build-plan` on 2026-05-23.

> **Discipline.** If a slice grows to add a module not in [ARCHITECTURE.md](./ARCHITECTURE.md) §2 or drop one that is, that's an architecture change — stop and return to `/grill-architecture` before continuing. Do not paper over.

## v1 Release

### Demo

On the 7900 XTX, Sam runs `ck ingest && ck materialize` against a portfolio root containing **two real projects** (likely `~/Code/model-time/` itself plus one other) — source code, markdown docs, and at least one PDF among them. He then opens Claude Code at the portfolio root. The agent loads the materialized `AGENTS.md` tree (each scope's `CLAUDE.md` `@AGENTS.md` bridge auto-imports it per [ADR-0002](./docs/adr/0002-materialize-agents-md-with-claude-code-bridge.md)), and answers a cross-project orientation question via the MCP `find` tool — the response cites materialized scopes from **both** projects with file-path pointers the agent follows for full depth. Sam then edits `THEORY.md` in one of the projects; on the agent's next read of that scope's `AGENTS.md`, the `PreToolUse` FreshnessGate hook silently triggers re-materialization before the read returns, and `.context-kernel/log.md` records the regen chain. First-read latency on a cold scope of ~50–200 files stays under the 60s threshold (per `THEORY.md` open question 3 and `ARCHITECTURE.md` §7).

### Scope

**In v1** (from [ARCHITECTURE.md](./ARCHITECTURE.md) §2 + §3):

- §2 modules: Graph, Ingester, Materializer, FreshnessGate, OrientationServer, AgentCLI
- §3 supporting: ConfigStore, OperationalJournal

**Deferred** (from [ARCHITECTURE.md](./ARCHITECTURE.md) §6): EntityResolver, CloudFallback, HTTPMCPTransport, PushBasedRegeneration, EvalHarness, MCPWriteTools

**Out of scope** (from [ARCHITECTURE.md](./ARCHITECTURE.md) §8): multi-user/tenant, cross-host distribution, real-time collaboration, generic graph query API, kernel-side source editing, schema migration tooling, backup/DR, per-file access control

### Build sequence

Each slice is a `/grill-with-docs` candidate before building. The tracer bullet (S1) proves contracts end-to-end; subsequent slices deepen, wire, or harden. v1 release is **S10 — Cross-project dogfood demo**; S11–S13 are post-demo polish that still touches §2/§3-owned responsibilities and therefore live inside v1.

1. **Walking skeleton: ingest → materialize → check → mcp** — End-to-end against one small markdown-only project (~50 files). Real Graph (LightRAG + NetworkX storage), real Ingester (markdown only), real Materializer (`AGENTS.md` + `CLAUDE.md` bridge only — no cross-cutting views), real FreshnessGate via `ck check` and MCP-internal check, real `overview`, **stubbed `find`** (canned), all four `ck` subcommands wired, minimal `ConfigStore` defaults, basic `OperationalJournal` append. **Exit criterion includes a recorded first-read latency number against a stale ~50-file scope on the 7900 XTX.** If > 60s, stop and return to `/grill-architecture` — ADR-0003 is wrong. Modules: all 8. Depends: —.

2. **Wire FreshnessGate `PreToolUse` hook** — Hook script invoked by Claude Code's `PreToolUse` for `Read` calls into the materialized tree; calls into the same gate logic used by `ck check`. Modules: FreshnessGate, AgentCLI. Depth: hook integration becomes live. Depends: S1.

3. **Deepen Ingester: Python AST handler** — Replace markdown-only stub with real Python source parsing: module, class, function entities with scope-relative paths and signatures. Modules: Ingester. Depth: markdown → markdown + Python. Depends: S1.

4. **Deepen Ingester: TypeScript/JS handler** — TS/JS source parsing alongside Python. Modules: Ingester. Depth: + TypeScript/JS. Depends: S3.

5. **Deepen OrientationServer `find`** — Real embedding-similarity lookup over pre-materialized summary chunks, with response token-budget enforcement and file-path citations. Materializer extends its output to emit chunk-addressable summary records `find` can target. Modules: OrientationServer, Materializer. Depth: stub `find` → real. Depends: S1.

6. **Deepen Materializer: cross-cutting views** — Render the configured `[[view]]` entries: at minimum `by-topic/<tag>.md`, `recent-changes.md`, `index.md`. Modules: Materializer, ConfigStore. Depth: `AGENTS.md`-only → + cross-cutting views. Depends: S1.

7. **Harden Materializer: pinned-block merge** — `<!-- pinned -->` block contents survive regeneration and flow into the next materialization prompt as input (per `ARCHITECTURE.md` §2.3 ownership and §4 data-class rules). Modules: Materializer. Depends: S1.

8. **Harden observability + OperationalJournal** — Structured log lines (JSON or human via `CK_LOG_FORMAT`); freshness check hit/miss recorded; per-regen elapsed time and source-file count; UUID propagation across `ck` invocation → freshness trigger → regen chain. Content-address hashes only (per invariant 4 — bounded volume). Modules: OperationalJournal, all callers. Depends: S1.

9. **Wire cross-project ingest** — Portfolio root with multiple projects; per-project entity namespaces (no merging per non-goal 2). `ConfigStore` learns the portfolio shape. Modules: Ingester, ConfigStore. Depth: single-project → portfolio. Depends: S3.

10. **Cross-project dogfood demo (v1 release)** — Two-project portfolio (≥1 Python project, ≥1 TS/JS project). Full pipeline runs; agent answers a cross-project question via MCP `find` citing both projects; freshness hook fires on a hand-edit; first-read latency from S1 holds at portfolio scale. The demo paragraph above passes end-to-end. Modules: all 8 end-to-end. Depends: S2, S4, S5, S6, S9.

11. **Deepen Ingester: PDF handler** — PDF text extraction integrated into the existing handler set; content-addressing applies as for markdown/code. Modules: Ingester. Depth: + PDF. Depends: S3.

12. **Harden error model** — `IngestionError`, `MaterializationError`, `StaleReadError`; structured exit codes in AgentCLI; MCP error contract for OrientationServer (no Python exceptions cross the boundary). Per `ARCHITECTURE.md` §5 Error model. Modules: AgentCLI, Ingester, Materializer, FreshnessGate, OrientationServer. Depends: S3, S2.

13. **Deepen content-addressed blob GC** — Reachability sweep over `.context-kernel/embeddings/` and `.context-kernel/summaries/` keyed by current graph entity set. Modules: Ingester, Graph. Depends: S3.

## Post-v1 backlog

To be filled by `/grill-backlog` after v1 ships (or partway, once priorities stabilize). Candidate seeds from the deferred §6 mechanisms and from open questions:

- **EntityResolver** — cross-project entity unification (only if view-based surfacing proves insufficient; future ADR closes `THEORY.md` open question 1)
- **CloudFallback** — fill the `Summarizer`/`Embedder` seams with cloud routes (requires secrets-handling design)
- **HTTPMCPTransport** — replace stdio for multi-editor / remote scenarios
- **EvalHarness** (`ck eval`) — automated benchmark of "did the agent get a better answer because Context Kernel was in the loop"
- **MCPWriteTools** — additive write surface on the MCP server, obeying invariant 1 (graph-first, then materialize)
- **Per-directory scope overrides** (`scope.toml`) — closes `THEORY.md` open question 2 if scope ≠ directory in practice
- **Additional language handlers** beyond Python + TS/JS as portfolio composition demands

## Status

- **MVP:** Not applicable — thesis accepted, build-mode. v1 release at S10.
- **Last reviewed:** 2026-05-24
- **Slices completed:** 1 of 13. S0 GO — see [spike/results.md](./spike/results.md).
- **Active specs:** [S1 — Walking skeleton](./docs/slices/S1.md) (phase-1 implementation ready; phase-2 LightRAG-dependent modules now unblocked by S0).
- **S0 winner:** Qwen3-30B-A3B-Instruct-2507 Q4_K_M (94 tok/s, 2 format warnings, 38.3% cross-scope density, 9.9s first-read latency). Qwen3.6-MTP is the speed option. See [docs/slices/S0.md](./docs/slices/S0.md).
- **Code:** `/scaffold-modules` output landed (`context_kernel/` + `tests/` + `pyproject.toml`); no implementation bodies yet.
