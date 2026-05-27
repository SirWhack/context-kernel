<!-- context-kernel-freshness
graph: 4828895ec2ab8c46292fc502e3c028e8b68915c679ff81f463cf9148983976a0
source-tree: 8bbe90898d9232e845b24fcd934eef0baf9d38c3481009b4fef1bbb12a433805
materialized: 2026-05-27T21:18:16Z
-->
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

This scope implements the Context Kernel's model-time subsystem, which governs how source documents are ingested into a knowledge graph and materialized into developer-facing documentation. It enforces the core invariant that materialized files (AGENTS.md, CLAUDE.md bridges, and cross-cutting views) are always in sync with their source code at commit boundaries. The scope owns the entire pipeline from source file to readable summary, including the freshness guarantees that make stale reads structurally impossible.

The public API surface consists of two main interfaces. The **Ingester** reads portfolio source files and writes to the **Graph** knowledge store, owning summarization model choice, embedding model choice, entity-extraction prompt templates, and source-format handlers. The **Materializer** reads from the Graph and writes the materialized tree — AGENTS.md per scope, CLAUDE.md bridge files with `@AGENTS.md` imports, and configured views under `.context-kernel/views/`. Both are invoked through the **CLI** (`ck ingest`, `ck materialize`) and the **FreshnessGate**, which runs as a git pre-commit hook that blocks commits on staleness.

Internally, the scope structures around several key components. The **Graph** is the only mutable state, wrapped behind a thin protocol for backend flexibility (v1 uses LightRAG with pluggable storage). The **OrientationServer** exposes an MCP surface (`ck mcp`) with two read-only tools — `overview` and `find` — that point coding agents at materialized files without performing LLM calls or graph traversal. The **FreshnessGate** checks headers containing graph_commit and source-tree hashes, implementing invariant 2 from THEORY.md by making stale reads structurally impossible at the read boundary. The **ConfigStore** loads from `.context-kernel/config.toml` per invocation, with all knobs having defaults and secrets explicitly excluded.

Key design patterns include Parnas-secret interfaces for model choices (summarization and embedding), a pure-function projection from Graph to materialized tree, and a stateless MCP server with no runtime synthesis. The scope rejects pull-based JIT regeneration in favor of pre-commit hook enforcement, and explicitly does not support real-time updates, multi-tenant identity, or HTTP transport in v1. The hybrid corpus for `find` searches lives inside the Graph's vector store, not as a separate artifact.
