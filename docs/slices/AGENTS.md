<!-- context-kernel-freshness
graph: 4828895ec2ab8c46292fc502e3c028e8b68915c679ff81f463cf9148983976a0
source-tree: dfdf933cfdc90e1f02559f53979563ec3e2518e46a501adc0bf9af7bd98470f0
materialized: 2026-05-27T21:03:11Z
-->

This scope captures the architectural decisions, research findings, and validation results that define the S0 and S1 implementation phases of the context-kernel project. It serves as the project’s memory for resolved trade-offs, hardware constraints, and sequencing commitments.

The scope documents a completed LightRAG validation spike that passed all four exit criteria on the 7900 XTX (24 GB VRAM). The spike locked Qwen3-30B-A3B-Instruct-2507 Q4_K_M as the default indexing LLM and established that the embedder runs co-resident on port 8081 via a separate llama-server process. The hardware budget is critically tight — 23.9 GB of 24.0 GB VRAM is consumed with the current configuration, leaving no headroom for larger context windows, higher parallelism, or a bigger embedder. This constraint drives the selection of Q8_0 quantization for KV caches and the rejection of larger model variants.

The walking skeleton implementation order is fixed: ingest → materialize → check → mcp. Phase-1 of S1 does not depend on LightRAG and is ready to begin, while Phase-2 and end-to-end verification are gated on S0 completion. The scope also records the selected embedder (Qwen3-Embedding with 1024-dim output, bypassing LightRAG’s openai_embed dimensions enforcement via direct httpx POST) and the default storage trio (JsonKVStorage, NanoVectorDBStorage, NetworkXStorage) that requires zero external infrastructure.

Key decisions include the test corpus selection (LifeStrands project trimmed to ~41 files across 11 scopes), the exclusion of MTP turbo-quant from S0 (not in upstream master, revisit only if KV becomes a bottleneck), and the post-S0 workflow: insert S0 in PLAN.md, resolve placeholders in S1.md, optionally re-run grill-with-docs, then begin Phase-2 implementation. The scope also captures unresolved questions about LightRAG-API wrapping levels that may be closed by re-running documentation analysis on S1.
