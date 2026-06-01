<!-- context-kernel-freshness
graph: ce4c30de6021574f8be593ca3ef2c62ccfde5e39118e774477c1d6d76f0f9abe
source-tree: 3ebc2db5c9b84f661278f6256b5405a5f30938741706acbc62233fc4e037fac5
materialized: 2026-06-01T01:08:18Z
-->

This scope implements the Context Kernel’s core knowledge graph — the single source of truth from which all materialized documentation (AGENTS.md files and views) is derived. It owns the full lifecycle: ingesting source files into entities and relationships, resolving those entities into canonical nodes, storing them in a graph backend, and projecting the graph back into markdown files that coding agents read via Read/Grep/Glob. The scope enforces the system’s central invariants: no stale serves (freshness gate), idempotent regeneration, and content-addressed no-ops on unchanged source.

The public API surface centers on the `ck` CLI (`context_kernel/agent_cli.py`), which dispatches to sub-commands: `init`, `ingest`, `materialize`, `check`, and `mcp`. The ingester pipeline (`entity_resolver.py`) runs after raw entity collection, collapsing code definitions, docs, and ADRs into canonical nodes via `normalize()` and `resolve()` — pure functions with no I/O. The `KnowledgeStore` protocol (defined in `context_kernel/graph/protocol.py`) abstracts the graph backend behind read methods (`get_entity()`, `get_neighbors()`, `search_similar()`) and a single write method (`upsert()`) called only by the ingester. `ConfigStore` loads `.context-kernel/config.toml` at every invocation, exposing `ProjectSpec`, `IngesterConfig`, `MaterializerConfig`, and `OrientationConfig` dataclasses.

Internally, the scope is organized around several key modules. `change_detection.py` is the sole git-I/O layer, providing `source_tree_hash()`, `changed_since()`, `commit_of()`, `churn()`, and `size()` — all returning safe defaults on failure so drift falls to zero rather than raising. `freshness_gate.py` enforces the “no stale serve” invariant by raising `StaleReadError` when a read crosses a commit boundary. `operational_journal.py` maintains an append-only `.context-kernel/log.md` for audit. The materializer (described in the scope’s docstring) renders `(scope, graph_commit, view_spec)` into markdown, defining the freshness header format and pinned-block merge semantics. `scoring.py` provides a single `confidence()` function combining authority and node drift.

The scope depends on LightRAG as the v1 graph backend, wrapped behind the `KnowledgeStore` protocol to allow future backend swaps. It imports from `context_kernel.source_kinds` for code path detection, `context_kernel.types` for core types like `GraphCommit`, `Sha256`, and `ScopePath`, and `context_kernel.scoring` for confidence calculations. The embedding and summarization models are abstracted behind interfaces, hiding changes between Qwen3 variants or cloud models. All materialized files are derived from the graph and version-controlled alongside source, with regeneration triggered by a git pre-commit hook — no background processes, no runtime freshness gate.

## Recommended documentation

This scope has 15 code entities across 1 files but no reference documentation. To create one: `/init-reference model-time`

<!-- pinned -->
# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Run all tests (248 tests, ~6s)
PYTHONPATH=. .venv/bin/python3 -m pytest tests/ -x -q

# Run a single test file
PYTHONPATH=. .venv/bin/python3 -m pytest tests/test_ingester.py -x -q

# Run a single test by name
PYTHONPATH=. .venv/bin/python3 -m pytest tests/test_materializer.py -k "test_lists_all_scopes" -x -q

# Full pipeline (requires env vars — see below)
source .env && export DEEPSEEK_API_KEY CF_USER CF_WORKER_AI_TOKEN
.venv/bin/ck ingest --portfolio /home/swynn/Code
.venv/bin/ck materialize --all --config /home/swynn/Code/.context-kernel/config.toml

# Check freshness of a materialized file
.venv/bin/ck check context_kernel/AGENTS.md

# Start MCP server (stdio)
.venv/bin/ck mcp --config /home/swynn/Code/.context-kernel/config.toml
```

No linter or formatter is configured. No build step — pure Python with `pip install -e .` into `.venv/`.

## Architecture

The system is a four-phase pipeline: **Ingest → Graph → Materialize → Serve**.

**Ingester** (`context_kernel/ingester/`) reads source files and produces entities + relationships. It has two handler types: `StructuredHandler` (Python AST, TypeScript tree-sitter — instant, no LLM) and `ChunkHandler` (markdown — sends chunks to `Summarizer` for entity extraction via LLM). The `Summarizer` and `Embedder` are protocol interfaces hiding the model choice; concrete implementations (`LLMSummarizer`, `HttpEmbedder`) call OpenAI-compatible endpoints. The summarizer has a content-addressed disk cache (`sha256(version:model:text)`) — unchanged chunks skip the LLM.

**Graph** (`context_kernel/graph/`) is the sole mutable state. `KnowledgeStore` is the protocol; `LightRAGStore` is the only production implementation (JSON files + NetworkX on disk, brute-force cosine similarity). All derived blobs (embeddings, summaries) are content-addressed at `<sha256>.{bin,md}`.

**Materializer** (`context_kernel/materializer/`) is a pure function of `(scope, graph_commit, view_spec) → markdown`. It is the **only** writer to `AGENTS.md` / `CLAUDE.md` bridge files. It preserves `<!-- pinned -->` blocks through regeneration. It renders cross-cutting views (index, by-topic) under `.context-kernel/views/`.

**OrientationServer** (`context_kernel/orientation_server/`) is a stateless MCP server with two tools: `overview` (read scope's AGENTS.md) and `find` (embedding similarity search). No LLM calls, no graph traversal at query time.

### Key invariants

1. The graph is the source of truth — materialized files are always derived, never edited in place (except pinned blocks).
2. A pre-commit hook runs `ck ingest && ck materialize --all` before every commit — materialized files travel with the code.
3. The MCP server does no runtime synthesis — everything is pre-materialized.
4. Derived artifacts are content-addressed and immutable.

### Data flow on `ck ingest`

Phase 1 (structured handlers) → Phase 2 (chunk handlers, parallelized per-chunk via ThreadPoolExecutor) → Phase 3 (embed all entities) → Phase 4 (scope summaries, parallelized). All phases write to a shared `LLMMetrics` accumulator for cost/token tracking.

### Configuration

- `.context-kernel/config.toml` — model choices, endpoints, parallel_requests, view specs, project list
- `.env` — API keys (`DEEPSEEK_API_KEY`, `CF_USER`, `CF_WORKER_AI_TOKEN`). Never committed.
- Env vars in endpoint URLs are expanded via `os.path.expandvars()` (e.g., `$CF_USER` in the Cloudflare URL)
- `CK_LOG_FORMAT` / `CK_LOG_LEVEL` for logging; `CK_CONFIG_PATH` to override config location

### Test conventions

Tests use `_FakeSummarizer` and `_FakeStore` — no LLM or network calls in the test suite. The `conftest.py` has an optional `llama_server` fixture for integration tests against the local embedder (only runs if the model file exists). All tests run with `PYTHONPATH=.` from the repo root.

## Document hierarchy

Read these in order when starting a new session:

1. **THEORY.md** — thesis, invariants, non-goals, open questions. The trunk.
2. **CONTEXT.md** — glossary of domain terms.
3. **ARCHITECTURE.md** — module model, tenets, data classes, deferred mechanisms.
4. **PLAN.md** — 13-slice build sequence with status. S10 (v1 demo) is complete.
5. **docs/adr/** — 16 decision records. Key ones: ADR-0002 (AGENTS.md bridge), ADR-0010 (pre-commit hook), ADR-0015 (confidence scoring), ADR-0016 (contextual extraction).

THEORY.md and ARCHITECTURE.md are load-bearing — if a change would violate an invariant or tenet, stop and discuss before proceeding.

## Portfolio context

This repo (`model-time`) is one project in a portfolio rooted at `~/Code/`. The portfolio config lives at `~/Code/.context-kernel/config.toml` and lists three projects: `model-time`, `evergreenlabs`, `evergreenlabs-bot`. The `ck` CLI operates at the portfolio level — `--portfolio ~/Code/` ingests all declared projects into a shared graph.
<!-- /pinned -->
