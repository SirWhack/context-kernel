# HANDOFF

## Current status (2026-05-26)

**S10 demo: 6 of 7 checkpoints passing.** The full pipeline runs end-to-end across two real projects (evergreenlabs + evergreenlabs-bot) on the 7900 XTX.

### What works

- `ck ingest --portfolio ~/Code` processes both repos: 338 entities, 203 relationships, 354 embedded chunks. evergreenlabs (7.1s), evergreenlabs-bot (16.4s) — both well under the 60s threshold.
- `ck materialize --all` writes AGENTS.md + CLAUDE.md to every scope in both project trees, plus cross-cutting `index.md` under `.context-kernel/views/`.
- MCP `find` returns cross-project results — a query about "log notes and haiku generation" surfaces `log_drafter.ts` from the bot alongside `TinkeringLog.jsx` from the website. A query about "how site data flows" traces `publishSiteData` → `siteData.js` across both repos.
- Embedder (Qwen3-Embedding-0.6B on :8081) and graph persistence (JSON-backed LightRAGStore) are fully operational.
- 211/211 unit tests passing.

### What's not done

- **S10 checkpoint 6: pre-commit hook freshness proof.** Requires `ck init` in the target repos and a real edit→commit cycle. Manual step.
- **Summarizer not wired.** 90 markdown files (READMEs, ADRs, docs) across both repos are skipped during ingestion. The `Summarizer` protocol exists and the model server (Qwen3-30B-A3B on :8080) is running, but no concrete implementation connects them. Board item created for this.
- **LightRAGStore is a JSON-file backend, not LightRAG.** The v1 store uses JSON persistence with brute-force cosine search. It implements the full `KnowledgeStore` protocol and works, but doesn't use the LightRAG library's native entity extraction or GraphML storage. This is sufficient for v1 — the store handles 338 entities and 354 chunks with sub-second queries.

### What we implemented this session

1. **`LightRAGStore` real implementation** (`context_kernel/graph/lightrag_adapter.py`) — JSON-persisted store with entity/relationship/summary/chunk storage, adjacency-list neighbor lookup, brute-force cosine similarity search.
2. **Wired `HttpEmbedder`** into `_cmd_ingest` and `_cmd_mcp` in `agent_cli.py` — embeddings now flow through the real pipeline.
3. **Auto-discovery of config.toml** from `--portfolio` path in the CLI.
4. **Fixed tree-sitter dependencies** — installed `tree-sitter`, `tree-sitter-javascript`, `tree-sitter-typescript` to unblock all 211 tests.
5. **Portfolio config** at `~/Code/.context-kernel/config.toml` with both projects + index view.

### What we learned

- **Cross-project find works well.** Semantic search over AST-extracted entities surfaces real architectural relationships (bot publishes site data that website components consume) without any manual annotation.
- **Markdown is the gap.** Code entities are fully indexed via AST handlers, but prose (READMEs, ADRs, design docs) needs the Summarizer wired to flow into the graph. This is the next high-value piece.
- **Potpie AI comparison.** Researched their GitHub — different product, different bet. They put intelligence in the query path (45 entity types, runtime evidence planning, fact-family TTLs). Context Kernel puts it in the materialization path (pre-computed files, zero infrastructure). Not redundant — genuinely different architectures for different audiences.
- **Thesis expansion brewing.** Sam wants to grow Context Kernel beyond code into a universal business context layer (Microsoft 365, CRM, etc.). This is a thesis rewrite, not a feature. Current thesis ("agentic engineer building my portfolio") should be validated via S10 demo first, then revisited.

## Resume pointers

- **To finish S10:** run `ck init` in evergreenlabs and evergreenlabs-bot, edit a file, `git commit`, verify materialized files update.
- **To wire the Summarizer:** implement a concrete `Summarizer` that calls Qwen3-30B on :8080 with an extraction prompt, connect it in `_cmd_ingest`.
- **Model servers:** `llama-server` binary at `/home/swynn/src/llama.cpp/build/bin/llama-server`. Models at `~/models/`. Summarizer on :8080, embedder on :8081.
- Roadmap: [PLAN.md](./PLAN.md). Decisions: [docs/adr/](./docs/adr/). Vocabulary: [CONTEXT.md](./CONTEXT.md). Thesis: [THEORY.md](./THEORY.md).
