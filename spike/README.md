# spike/

Throwaway. The S0 LightRAG validation spike per [docs/slices/S0.md](../docs/slices/S0.md).

## What lives here

- `spike.py` — single-file script that ingests the LifeStrands corpus through
  LightRAG, then measures the four S0 exit criteria.
- `results.md` — recorded measurements per model.
- `.venv/` — Python env (don't track).
- `spike_storage_<model>/` — per-model LightRAG storage (graph + vectors + KV).

## Prerequisites

Two llama-server processes running locally:

```
# LLM (port 8080) — one of:
~/src/llama.cpp/build/bin/llama-server \
  -m ~/models/qwen3-30b-a3b-instruct-2507/Qwen3-30B-A3B-Instruct-2507-Q4_K_M.gguf \
  -ngl 99 --port 8080 --ctx-size 16384 --parallel 1 --no-mmap --cache-ram 0 \
  -fa on -ctk q8_0 -ctv q8_0 --jinja

# or Qwen3.6-MTP:
~/src/llama.cpp/build/bin/llama-server \
  -m ~/models/qwen3.6-35b-a3b-mtp/Qwen3.6-35B-A3B-UD-IQ4_NL.gguf \
  -ngl 99 --port 8080 --ctx-size 16384 --parallel 1 --no-mmap --cache-ram 0 \
  -fa on -ctk q8_0 -ctv q8_0 --jinja --reasoning off \
  --spec-type draft-mtp --spec-draft-n-max 3

# Embedder (port 8081):
~/src/llama.cpp/build/bin/llama-server \
  -m ~/models/qwen3-embedding-0.6b/Qwen3-Embedding-0.6B-Q8_0.gguf \
  --embeddings -ngl 99 --port 8081 --pooling last --no-mmap --cache-ram 0
```

**`--cache-ram 0` is non-negotiable.** llama-server defaults to an 8 GB prompt cache.
For an embedder it's useless (no shared prefixes) and during an ingest of 1000+
LLM extraction calls it accumulates several GB of anonymous RSS. Disabling it
keeps process RAM stable at ~1-2 GB across long ingests.

## Usage

```bash
# Activate venv
source .venv/bin/activate

# Ingest the LifeStrands corpus
LLM_MODEL=qwen3-30b python spike.py ingest

# Measure cross-scope density (ADR-0009 threshold ≥15%)
LLM_MODEL=qwen3-30b python spike.py measure

# First-read latency proxy: synthesize one scope from graph
LLM_MODEL=qwen3-30b python spike.py synthesize services/chat-service

# Sanity-check a query
LLM_MODEL=qwen3-30b python spike.py query "how does session auth work across services"

# To compare a second model, set LLM_MODEL to something else and re-ingest —
# storage is per-model (spike_storage_<model>/).
```

## Exit criteria (per S0.md)

| # | Criterion | Threshold |
|---|---|---|
| 1 | LightRAG ingest+query works end-to-end | binary |
| 2 | Which indexing LLM wins | qualitative |
| 3 | First-read latency proxy | < 60 s |
| 4 | Cross-scope relationship density (ADR-0009) | ≥ 15% go, 5-15% limp, < 5% stop |
