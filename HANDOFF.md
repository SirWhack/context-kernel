# HANDOFF

State at end of session **2026-05-23** (evening). Resume here.

## Where we are

Mid-`/grill-with-docs` on `PLAN.md` S1. No code was written and no project doc was modified this session — only research and decisions surfaced for user confirmation before resuming.

## Decision: insert S0 before S1

`PLAN.md` S1 (walking skeleton) assumes real LightRAG end-to-end. `ARCHITECTURE.md` §1.1.1 already required LightRAG validation on the 7900 XTX *before* commitment — that validation hasn't happened. **S0 is the de-risking spike**: prove LightRAG ingest + query works on the corpus, pick the indexing LLM by benchmark, record a first-read latency proxy. No `ck` AgentCLI shape, no module structure. Pure throwaway under `spike/`.

If S0 fails, the cost is re-grilling `/grill-architecture` (ADR-0004 / LightRAG) or `/grill-theory` (open question 3 / pull-based JIT). If S1 fails the same way, the cost is also a bunch of thrown-away scaffolding *plus* the spike work — so de-risk first.

## Settled this session

- **Provider stack.** LM Studio (OpenAI-compatible HTTP at `localhost:1234/v1`) for the LLM. No `Summarizer` / `Embedder` Parnas abstractions in the spike — direct calls. The seams in `ARCHITECTURE.md` §2.2 still hold; we just don't exercise them yet.
- **Embedder.** **bge-m3 GGUF** (~1-2 GB), served by a separate `llama-server` (or LM Studio second slot) on a different port. Reasons: LightRAG's first-recommended embedder, runs trivially in LM Studio, MIT license, dense + sparse + multi-vector in one pass. Jina v4 considered and rejected for S0 — 4B params, Qwen Research license (non-commercial), LM Studio incompat (`trust_remote_code` not honored), and the GGUF quants drop the multi-vector head that would justify the choice in the first place. **Stickiness reminder:** LightRAG requires nuking vector storage to switch embedders. Commit to bge-m3 now; revisit only if MTEB points genuinely matter.
- **Indexing LLM regime: MoE wins on the 7900 XTX.** Dense 30B Q4_K_M (~17 GB) is memory-bandwidth-bound at ~15-20 tok/s. Qwen3 / 3.6 MoE with ~3B active reads ~2 GB per token → ~80-100 tok/s. For an ingest workload (hundreds-to-thousands of LLM calls), this is the whole game.
- **Napkin-math correction.** Gemma 3/4 hybrid sliding-window attention (5:1 local:global, 1024-token local window) cuts KV cache by ~5x vs. the naive formula. The user's Gemma 4 31B @ 100K context Q8 KV actually fits (~20-21 GB), contradicting the earlier ~28 GB estimate. Lesson: trust empirical reports over per-layer math when SWA / GQA is in play.

## Open — confirm before resuming (Q3)

Proposed S0 spec; needs user yes/no on each branch:

### (a) Benchmark two LLMs side by side on the same ~50-file corpus

1. **Qwen3-30B-A3B-Instruct-2507** @ Q4_K_M, 64K ctx, Q8 KV, flash attention. Baseline — LightRAG team shipped Sept 2025 entity-extraction tuning for this exact model.
2. **Qwen3.6-35B-A3B** @ UD-IQ4_XS (~17.7 GB), 64K ctx, Q8 KV, `enable_thinking=False`. Challenger. Released 2026-04-16, no LightRAG-specific validation yet. **Footgun:** unified hybrid-thinking design has reports of think-tag leakage in llama.cpp ([issue #22398](https://github.com/ggml-org/llama.cpp/issues/22398)). Must verify the LM Studio chat template suppresses thinking on every call before trusting extraction.

Drop Gemma 4 31B from S0 — it's a comparator only if both Qwen variants disappoint on extraction quality.

### (b) Embedder

bge-m3 GGUF.

### (c) Embedding process placement

Separate `llama-server` (or LM Studio second slot) on a different port. Co-resident on the GPU since the MoE LLM only uses ~18-22 GB and bge-m3 GGUF is ~1-2 GB.

### (d) S0 exit criteria — what the spike must produce

1. Single-file Python script (not yet the `ck` AgentCLI shape) that runs LightRAG ingest + a representative query end-to-end against ~50 markdown files.
2. Per candidate model: ingest wall-time, tok/s during ingest, peak VRAM, extracted entity count, spot-check of 3-5 chunks for extraction correctness.
3. **First-read latency proxy:** wall-time to materialize one scope's worth of summary content from the graph. This is the number `ADR-0003` lives or dies on. Threshold: **< 60s** per `ARCHITECTURE.md` §7.
4. **Cross-scope relationship density** (per [ADR-0009](docs/adr/0009-cross-scope-relationships-via-source-id.md)): count of relationships whose endpoints span ≥2 scopes (source-files in different directories), expressed as a fraction of total relationships in the graph. **This is the number THEORY.md open question 4 lives or dies on — and with it, the thesis.** Heuristic thresholds: **≥15%** = go; **<5%** = stop and re-grill `ADR-0004` (LightRAG); **5-15%** = limp forward with caveat and watch closely.
5. Go/no-go on: (i) does LightRAG work, (ii) which model wins, (iii) is first-read latency under 60s, (iv) is cross-scope density ≥15%.

### (e) Spike location

Throwaway `spike/` directory at the project root. Not inside any future v1 module layout — proving the dependency, not building the architecture.

## Resume instructions

1. Re-read this file and the **Open** section above.
2. Confirm or adjust (a)-(e) with the agent.
3. Once confirmed, the agent should: write `spike/` script, run it for each candidate, fill `spike/results.md` with a table, report back.
4. After S0 passes, update `PLAN.md`: insert S0 explicitly above S1 with the results table linked, then resume `/grill-with-docs` on S1.

## Research trail

**LLM survey:**
- [Qwen3-30B-A3B-Instruct-2507 model card](https://huggingface.co/Qwen/Qwen3-30B-A3B-Instruct-2507)
- [Qwen3.6-35B-A3B model card](https://huggingface.co/Qwen/Qwen3.6-35B-A3B)
- [unsloth/Qwen3.6-35B-A3B-GGUF](https://huggingface.co/unsloth/Qwen3.6-35B-A3B-GGUF)
- [bartowski/Qwen_Qwen3.6-35B-A3B-GGUF](https://huggingface.co/bartowski/Qwen_Qwen3.6-35B-A3B-GGUF)
- [llama.cpp think-tag leakage on Qwen 3.6 (#22398)](https://github.com/ggml-org/llama.cpp/issues/22398)
- [Qwen3 technical report (arXiv 2505.09388)](https://arxiv.org/html/2505.09388v1)
- [Awesome Agents home-GPU LLM leaderboard](https://awesomeagents.ai/leaderboards/home-gpu-llm-leaderboard/)
- [llama.cpp ROCm performance discussion #15021](https://github.com/ggml-org/llama.cpp/discussions/15021)

**Embedder:**
- [BAAI/bge-m3 model card](https://huggingface.co/BAAI/bge-m3)
- [Jina v4 LM Studio incompat (HF discussion #84)](https://huggingface.co/jinaai/jina-embeddings-v4/discussions/84)
- [jina-embeddings-v4 paper (arXiv 2506.18902)](https://arxiv.org/abs/2506.18902)

**LightRAG plumbing:**
- [LightRAG README (HKUDS)](https://github.com/HKUDS/LightRAG)
- [LightRAG ProgramingWithCore.md](https://github.com/hkuds/lightrag/blob/main/docs/ProgramingWithCore.md)
- Quickstart pattern: `openai_complete_if_cache` + `openai_embed` both accept `base_url`. Default storage trio: `JsonKVStorage` + `NanoVectorDBStorage` + `NetworkXStorage` — all file-based, zero external infra. Matches `ARCHITECTURE.md` §2.1's NetworkX-default plan.

## Outstanding stale refs (clean up next PLAN.md touch)

- `PLAN.md` Status section says *"`git init` still pending (per `HANDOFF.md`)"* — `git init` happened.
- `temp.md` at root is a stale copy of the `ARCHITECTURE.md` §2 diagram with the CLI labeled "OperatorCLI" instead of "AgentCLI". Already gitignored; delete on sight.
