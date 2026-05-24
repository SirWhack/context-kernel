# S0 spike results

Per [docs/slices/S0.md](../docs/slices/S0.md). Corpus: LifeStrands (114 files
across 25 scopes after `tests/` exclusion; trimmed to `services/chat-service:shared:root-md`
≈ 41 files / 11 scopes for the first measurement pass).

## Validated infrastructure

- **llama.cpp**: upstream master commit `549b9d8`, built with `GGML_HIP=ON`, `AMDGPU_TARGETS=gfx1100`
- **GPU**: AMD Radeon RX 7900 XTX (24 GB), ROCm 7.2.0 on WSL2 Ubuntu
- **LLM server**: `127.0.0.1:8080` (one of Qwen3-30B or Qwen3.6-MTP — see launch flags in `README.md`)
- **Embedder server**: `127.0.0.1:8081` (Qwen3-Embedding-0.6B Q8_0, `--pooling last`, `--no-mmap`)
- **MTP**: `--spec-type draft-mtp` is in upstream master (verified). TurboQuant KV is fork-only — skipped.
- **VRAM accounting (concurrent)**: Qwen3.6-MTP @ 16K ctx / parallel 1 + embedder ≈ 23.9 GB used / 24.0 GB total — 589 MiB headroom

## Smoke test (3 root markdown files, Qwen3.6-MTP)

| | |
|---|---|
| Files | 3 (AGENTS.md, CLAUDE.md, DM_AGENT_ARCHITECTURE.md) |
| Wall time | 299 s (~100 s/file) |
| Graph | **135 entities, 166 relationships** |
| Cross-scope density | 0/166 = 0 % (all 3 files in scope `.` — expected; measurement code passes sanity check) |
| Notable LightRAG warning | `LLM output format error; found 5/4 fields on ENTITY 'DM Service' @ 'MCP Server'` — handled gracefully, indicates Qwen3.6-MTP occasionally emits an extra tuple field |

## Throughput recap (from llama-server smoke tests; not full ingest)

| Model | Config | Decode tok/s | Notes |
|---|---|---|---|
| Qwen3-30B-A3B-Instruct-2507 Q4_K_M | no spec dec | 94.4 | 495 prompt tok/s |
| Qwen3.6-35B-A3B-MTP UD-IQ4_NL | `--spec-draft-n-max 3`, 4-par/32K ctx | 121.3 | 72% draft acceptance |
| Qwen3.6-35B-A3B-MTP UD-IQ4_NL | `--spec-draft-n-max 3`, 1-par/16K ctx | 109.3 | 70% draft acceptance (lean cfg) |
| Qwen3-Embedding-0.6B Q8_0 | `--pooling last` | — | 22 ms/embed warm, 2071 ms cold |

## Runs against the trimmed corpus

### Qwen3.6-35B-A3B-MTP UD-IQ4_NL — 2026-05-24

Corpus: LifeStrands `services/chat-service` + `shared` + root markdowns (42 files / 10 scopes).

| Criterion | Measurement | Verdict |
|---|---|---|
| 1. LightRAG works end-to-end | 42 files ingested → graph with 1145 entities, 1195 relationships | ✅ |
| 2. Ingest wall time | **1519.4 s** (~25 min, 36 s/file avg) | ✅ |
| 3. First-read latency proxy (synthesize `services/chat-service`) | **12.7 s** | ✅ (< 60 s) |
| 3b. Synthesize `shared/auth` | 11.8 s | ✅ |
| 3c. Synthesize `shared` | 12.4 s | ✅ |
| 4. Cross-scope density (ADR-0009) | **520 / 1195 = 43.5 %** | ✅ (≥ 15 % = go) |
| Format-error warnings | 311 (Qwen3.6 emits 5-field tuples occasionally; LightRAG handles) | tolerable |

**Top cross-scope edge pairs:**

```
369  .  ↔  services/chat-service
201  .  ↔  services/chat-service/managers
182  services/chat-service  ↔  services/chat-service/managers
101  services/chat-service  ↔  services/chat-service/services
 99  .  ↔  services/chat-service/services
 89  .  ↔  shared
 87  .  ↔  services/chat-service/clients
 85  .  ↔  services/chat-service/api
 73  services/chat-service  ↔  services/chat-service/clients
 72  services/chat-service  ↔  shared
```

The `services/chat-service ↔ shared` cluster validates ADR-0009's stated win condition: when auth utilities in `shared/auth/` are referenced by `chat-service/managers/`, LightRAG's surface-name entity merging surfaces the link, and B's source-id traversal counts it as cross-scope.

**Spot-check (synthesized prose quality):**

- `services/chat-service`: names canonical file paths inline (`managers/conversation_manager.py`, `storage/thread_store.py`, `clients/model_client.py`), correctly identifies the WebSocket → ConversationManager → ThreadStore flow, catches the Redis backing of ThreadStore. One minor wart: said "LM Studio" inferred from the OpenAI-compatible HTTP shape; the code is provider-agnostic.
- `shared/auth`: catches verify-only design, three roles (Admin/Readonly/Service), the `AUTH_DISABLED` dev bypass, the WebSocket close-code-1008 mechanism.
- `shared`: catches PYTHONPATH-mounting strategy from Wave 2 Architecture, the D05 LIFO bug fix in `queues.py`, TTL semantics in `redis_keys.py`.

**Verdict: GO.** Qwen3.6-MTP passes all four S0 exit criteria with substantial margin. The thesis (cross-scope orientation via LightRAG's native merging + source-id traversal) is validated on a real source-code corpus.

### Qwen3-30B-A3B-Instruct-2507 Q4_K_M — _not yet run_

Pending: stop the Qwen3.6-MTP llama-server, restart with the Qwen3-30B GGUF (same lean flags, no `--spec-type` / `--reasoning off`), re-run ingest + measure against `./storage_qwen3_30b/`. Comparison will show whether the simpler model produces an equally usable graph; if it does, Qwen3-30B is the safer S1 default (no MTP draft, no warning noise).

## Notes carried forward

- **Ingest cost scales with file size, not just file count.** 3 markdown files (~40 KB total) took 5 min; 41 mostly-Python files will likely take 60-90 min at current settings.
- **`llm_model_max_async=1`** in the spike matches `--parallel 1` on llama-server. Raising the server parallelism could cut wall time but risks Qwen3.6-MTP draft acceptance degradation under concurrent load (untested).
- **The 5-fields-where-4-expected warning** suggests adding a post-extraction validation that's more lenient. Defer to S1 phase-2's `LightRAGStore` wrap.
- **`openai_embed` from LightRAG forces `dimensions=1536`** via a decorator that fights 1024-dim Qwen3-Embedding. The spike bypasses with a direct httpx POST to `/v1/embeddings`. S1 should either use a custom embedder adapter or pin to a model that emits 1536 dims.
