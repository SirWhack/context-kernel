<!-- context-kernel-freshness
graph: ce4c30de6021574f8be593ca3ef2c62ccfde5e39118e774477c1d6d76f0f9abe
source-tree: 892336ac2609b051f64368d6d4c56032158d33d86017b068ff04e51f2ac62b1c
materialized: 2026-06-01T01:08:20Z
-->

This scope is a **de-risking spike** that validates whether LightRAG can produce sufficient cross-scope relationship density (≥15%) to differentiate the Context Kernel from flat vector RAG. It is a throwaway validation harness, not production code. The spike answers four go/no-go questions about LightRAG viability before committing to the walking skeleton, and it has already confirmed the thesis on a real source-code corpus (LifeStrands), achieving 43.5% cross-scope density.

The public interface is a single module, `spike.py`, which exposes five CLI commands via `main()`: `cmd_ingest`, `cmd_measure`, `cmd_synthesize`, `cmd_query`, and `cmd_measure`. The spike connects to two local llama-server processes (LLM on port 8080, embedder on port 8081) and wraps LightRAG through custom adapter functions. `llm_model_func` and `embed_func` bypass LightRAG's built-in OpenAI-compatible clients — notably, `embed_func` uses a direct HTTP POST to `/v1/embeddings` to avoid LightRAG's `openai_embed` decorator that forces 1536 dimensions, incompatible with the 1024-dim Qwen3-Embedding model. `make_rag()` constructs a `LightRAG` instance with these custom functions, while `collect_files()` and `scope_of()` provide the file-scope mapping needed for cross-scope density measurement.

Internally, the spike implements a two-phase measurement pipeline. First, `cmd_ingest` runs LightRAG's full extraction pipeline (entity/relationship extraction via LLM, embedding, graph construction). Second, `cmd_measure` performs a post-ingest traversal pass that counts relationships as cross-scope when their endpoint entities have source files in different scopes, using the `scope_of()` function to map file paths to scope names. `cmd_synthesize` serves as a first-read latency proxy by gathering one scope's entities and relationships and sending them to the LLM with an S1-style synthesis prompt. The spike stores per-model artifacts in `spike_storage_<model>/` directories, isolating graph, vectors, and KV data by model variant.

Key dependencies include `lightrag.LightRAG` and its storage pipeline (`lightrag.kg.shared_storage.initialize_pipeline_status`), `httpx` for direct HTTP calls to llama-server, `numpy` and `networkx` for measurement computations, and `pathlib.Path` for file traversal. The spike has validated two model options: Qwen3-30B-A3B-Instruct (default for S1, slower but 150× fewer format errors) and Qwen3.6-MTP (faster but produces 311 format warnings). Critical operational constraints discovered include `--cache-ram 0` being non-negotiable for both servers to prevent memory bloat, and `llm_model_max_async=1` matching `--parallel 1` on llama-server to avoid draft acceptance degradation under concurrent load.

## Recommended documentation

This scope has 11 code entities across 1 files but no reference documentation. To create one: `/init-reference spike`

