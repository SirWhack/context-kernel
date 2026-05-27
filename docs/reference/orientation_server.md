# OrientationServer — Reference

How the MCP orientation surface works today. Operational reference for agents and engineers working in `context_kernel/orientation_server/`.

Contract: [ARCHITECTURE.md](../../ARCHITECTURE.md) §2.5.
Decisions: [ADR-0006](../adr/0006-files-as-primary-interface.md), [ADR-0012](../adr/0012-find-retrieval-via-hybrid-embedding-search.md).

## Overview

The OrientationServer is the read-only MCP surface of the Context Kernel. It exposes two tools — `overview` and `find` — that point coding agents at the right materialized files for a given question. It is a pure read-through over on-disk state: no independent state, no runtime synthesis, no live LLM calls, no on-the-fly graph traversal (THEORY.md invariant 3). Spawned by `ck mcp` as a stdio process; the coding agent connects to it as an MCP server.

The design principle is **MCP points; files deliver**. Every response includes file-path citations. The agent follows up with `Read` on those paths for full depth. MCP is a narrow orientation aid, not the primary interface — the materialized tree is ([ADR-0006](../adr/0006-files-as-primary-interface.md)). If the MCP server is unavailable, the file tree still answers every question; orientation just requires more manual navigation.

## MCP tools

### overview

Reads a scope's `AGENTS.md` and returns it within a token budget. This is the "where am I?" tool — an agent entering a directory calls `overview` to get the scope summary, entity list, cross-scope relationships, and pointers to deeper documentation.

**Parameters:**
- `scope` (string, required) — path to the scope directory (relative to portfolio root).
- `max_tokens` (int, optional) — response cap. Default: `OrientationConfig.default_max_tokens` (4096).

**Behavior:** Resolves `scope` to `{tree_root}/{scope}/AGENTS.md`. If the file does not exist, returns a "no materialized overview" message. Strips the freshness header before returning content. If the file exceeds the token budget, truncates at a paragraph boundary (preferring a clean `\n\n` break in the second half of the budget).

Token budget enforcement uses a `_CHARS_PER_TOKEN = 4` heuristic — coarse but sufficient for orientation responses where precision is not load-bearing.

### find

Embedding-similarity search over the hybrid corpus. This is the "where is X?" tool — an agent with a conceptual question ("how does authentication work?", "what implements the Embedder interface?") calls `find` to get ranked results with source file citations.

**Parameters:**
- `query` (string, required) — natural-language search query.
- `scope` (string, optional) — restrict search to a single scope. Omit to search the entire portfolio.
- `max_tokens` (int, optional) — response cap. Default: `OrientationConfig.default_max_tokens` (4096).

**Behavior:** Embeds the query string via the Embedder in `"query"` mode (asymmetric prompting — see below), then calls `KnowledgeStore.search_similar()` for the top-10 results by cosine similarity. Results are formatted as markdown chunks with `> Source: \`{path}\`` citations and assembled within the token budget.

If no Embedder is configured, returns a clear error directing the agent to use `overview` instead. If the Embedder endpoint is unreachable, returns an error with the exception detail. No silent degradation — per [ADR-0012](../adr/0012-find-retrieval-via-hybrid-embedding-search.md).

## Hybrid corpus

The `find` tool searches over the hybrid corpus: the combined set of entity descriptions and per-scope summaries, both embedded at ingest time and stored in the Graph's vector index. Per [ADR-0012](../adr/0012-find-retrieval-via-hybrid-embedding-search.md).

**Entity descriptions** come from StructuredHandlers (Python AST, TypeScript tree-sitter). These are fine-grained: individual modules, classes, functions with their signatures, visibility, and Ousterhout depth metrics. A query like "what implements the Embedder interface?" matches entity descriptions.

**Scope summaries** are generated mechanically during the ingestion pass — entity counts by kind, Protocol detection, top public interfaces. These are coarse-grained: what a directory does, not what individual symbols do. A query like "what does the ingester module do?" matches scope summaries.

Both kinds are tagged with a `kind` field (`"entity"` or `"summary"`) and a `scope` field on the `EmbeddedChunk` / `SearchResult` dataclasses. The scope field enables the optional scope filter on `find`.

The hybrid corpus is populated entirely at ingest time. The OrientationServer does not write to it — it is a pure reader. See [docs/reference/ingester.md](./ingester.md) for how embedding happens during the ingestion pipeline.

## Asymmetric prompting

The Embedder uses Qwen3-Embedding-0.6B, which requires different prompt formats for passages (ingest-time) and queries (search-time). This is called asymmetric prompting.

- **Passage mode** (`mode="passage"`): text is embedded as-is. Used during the ingestion pass when entity descriptions and scope summaries are embedded into the hybrid corpus.
- **Query mode** (`mode="query"`): text is prefixed with `Instruct: Find relevant code modules, classes, functions, or documentation in a software portfolio.\nQuery: {text}`. Used by `find` at query time.

Omitting the query prefix costs 1-5% retrieval accuracy per S0 measurement. The `Embedder` protocol exposes this via the `mode` parameter; the OrientationServer always passes `mode="query"` when calling the Embedder from `find`. This is a deterministic vector computation (sub-second), not runtime synthesis — invariant 3 is not violated.

## Statelessness

The OrientationServer holds no state across requests. Every MCP session starts fresh — no recall of previous queries, no session affinity, no in-memory cache. Per THEORY.md invariant 3 and ARCHITECTURE.md tenet 3: the server is a pure function of on-disk state. Restart-safe by construction.

This means:
- No background daemon. The server process lives only as long as the MCP session.
- No cross-session memory. If the agent asks the same question twice, both calls do the same work.
- No on-the-fly graph traversal. `find` searches the pre-embedded vector index; it does not walk graph relationships at query time.
- The only "computation" at query time is embedding the query string (a forward pass through a 0.6B parameter model) and a vector similarity lookup. Both are infrastructure, not synthesis.

## Configuration

All OrientationServer config lives in `OrientationConfig` (loaded from `.context-kernel/config.toml` `[orientation]` section):

| Key | Default | Purpose |
|---|---|---|
| `default_max_tokens` | `4096` | Token budget for `overview` and `find` responses |

The Embedder endpoint configuration is shared with the Ingester (lives in `[ingester]` section): `embedder_endpoint`, `embedder_model`, `embedder_dim`. The `ck mcp` command reads these from `IngesterConfig` when constructing the `HttpEmbedder`.

## Interfaces

### MCP tool schemas

The server exposes two tools via the `mcp` Python SDK's `FastMCP` class, using stdio transport:

- `overview(scope: str, max_tokens: int) -> str` — scope-level orientation from `AGENTS.md`.
- `find(query: str, scope: str | None, max_tokens: int) -> str` — embedding-similarity search with file-path citations.

Both return plain markdown strings. Error conditions (missing files, unreachable embedder, no results) return human-readable error messages as the response body, not MCP protocol errors.

### Internal modules

- `tools.py` — the `overview()` and `find()` functions implementing tool logic.
- `similarity.py` — `nearest_chunks(query, store, embedder, k, scope)` that embeds the query and delegates to `KnowledgeStore.search_similar()`.
- `response.py` — `assemble(chunks, paths, max_tokens)` that formats results with citations and enforces the token budget.
- `__init__.py` — `serve(tree_root, store, config, embedder)` that registers tools on a `FastMCP` instance and calls `app.run()`.

## Relationships to other subsystems

- **Graph** — the OrientationServer reads from it via `KnowledgeStore.search_similar()`. Never writes. See [docs/reference/ingester.md](./ingester.md) for how the hybrid corpus is populated.
- **Ingester** — populates the hybrid corpus that `find` searches over. Also provides the `Embedder` implementation (`HttpEmbedder`) that the OrientationServer uses at query time. The OrientationServer and Ingester share the same Embedder endpoint config.
- **Materializer** — writes the `AGENTS.md` files that `overview` reads. The OrientationServer strips the freshness header from materialized files before returning content.
- **FreshnessGate** — ARCHITECTURE.md §2.5 notes that the OrientationServer "invokes FreshnessGate before returning any chunk." In the current implementation, freshness is enforced by the pre-commit hook ([ADR-0010](../adr/0010-pre-commit-hook-regeneration.md)), not by a runtime check in the server. The server reads whatever is on disk.
- **AgentCLI** — `ck mcp` constructs the `LightRAGStore`, `HttpEmbedder`, and `OrientationConfig`, then calls `serve()`. See `agent_cli.py` `_cmd_mcp()`.

## Current limitations

- **No HTTP transport.** stdio only — one MCP session per editor process. Multiple editors means multiple server processes, each with their own stdio pipe. HTTP transport is deferred (ARCHITECTURE.md §6).
- **No write tools.** The OrientationServer is strictly read-only. Future MCP write tools (per invariant 1) would be additive, routing through the Graph — not retrofitted into `overview` or `find`. Deferred until a concrete need emerges where Bash-invoked `ck` is insufficient.
- **Single-editor concurrency.** stdio transport means one connected client at a time. No multiplexing, no shared sessions.
- **No pagination.** Token-budget-capped responses only. Callers needing more must narrow the scope or split into multiple queries.
- **No result ranking beyond cosine similarity.** `find` returns raw vector similarity scores. No re-ranking, no BM25 hybrid, no LLM-based relevance filtering. Sufficient for v1 portfolio sizes.
- **Coarse token estimation.** The `_CHARS_PER_TOKEN = 4` heuristic can over- or under-count. Acceptable for orientation responses where the budget is a soft cap, not a protocol constraint.
- **Embedder required for `find`.** If the Embedder endpoint is down, `find` is unavailable. `overview` still works (it reads files, no embedder needed).
