<!-- context-kernel-freshness
graph: 4828895ec2ab8c46292fc502e3c028e8b68915c679ff81f463cf9148983976a0
source-tree: 892336ac2609b051f64368d6d4c56032158d33d86017b068ff04e51f2ac62b1c
materialized: 2026-05-27T21:03:12Z
-->

This is a throwaway spike script that validates LightRAG integration against the LifeStrands corpus for S0 exit criteria. The single-file module (`spike.py`) ingests a codebase through LightRAG, measures cross-scope relationship density, synthesis latency, and format error rates, then compares results across different LLM models. It is explicitly marked as throwaway — the production architecture lives in `ARCHITECTURE.md` and `docs/slices/`.

The public API consists of five command functions dispatched from `main()`: `cmd_ingest()` feeds files into LightRAG, `cmd_measure()` computes cross-scope density from the stored graph, `cmd_synthesize(scope)` proxies first-read latency by gathering one scope's entities and relationships and sending them to the LLM, and `cmd_query(question)` runs a query against the indexed graph. Two critical adapter functions — `llm_model_func` and `embed_func` — wrap llama-server HTTP endpoints. `embed_func` is notable because it bypasses LightRAG's `openai_embed` which forces 1536 dimensions via a decorator, instead doing a direct `httpx` POST to `/v1/embeddings` to match Qwen3-Embedding's 1024-dim output. `make_rag()` assembles the `LightRAG` instance with these custom adapters and per-model storage directories (`spike_storage_<model>/`).

Internally, `collect_files(root)` walks the corpus directory filtering by `INCLUDE_EXTS` and `INCLUDE_PREFIXES` while excluding `EXCLUDE_PATH_PARTS`. `scope_of(file_path, root)` derives a scope string from the file path relative to the portfolio root. The module imports `lightrag.LightRAG`, `QueryParam`, `openai_complete_if_cache`, and `EmbeddingFunc`, plus `httpx`, `numpy`, and `networkx` for HTTP calls and graph analysis. Two llama-server processes must run locally — one for the LLM (Qwen3-30B or Qwen3.6-MTP on port 8080) and one for embeddings (Qwen3-Embedding-0.6B on a separate port). The spike revealed that `--cache-ram 0` is non-negotiable for both servers to avoid memory bloat, and that Qwen3-30B produces 150× fewer format errors than Qwen3.6-MTP at the cost of 37% slower ingest.

## Recommended documentation

This scope has 11 code entities across 1 files but no reference documentation. To create one: `/init-reference spike`

