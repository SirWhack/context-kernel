# TODO / Working notes

Findings from building the EntityResolver (ADR-0017) and probing Stage 4 against a real
multi-thousand-entity codebase. Project-specific details are intentionally omitted.
Decisions that should outlive this file belong in an ADR.

## Where things stand

Stages 1–3 of cross-altitude linking are **built, tested, and verified** on a real corpus.

- **Stage 1 — identity merge** (code-anchored, within-project): the same concept across code +
  docs + ADRs collapses into one canonical node. `entity_resolver.py`.
- **Stage 2 — relationship resolution**: global name resolution + a deterministic file-path→module
  resolver; drops (never phantom-mints) unresolvable endpoints.
- **Stage 3 — ADR-0016 contextual extraction**: feed Phase-1 code entities + CONTEXT.md vocab into
  the doc-extraction prompt so the LLM cites real identifiers.

Result vs the prior graph, which had **zero** cross-file edges (IDs keyed by source_file;
per-chunk relationship resolution):

| | prior | S1+2 | **S3 (contextual)** |
|---|---|---|---|
| cross-altitude edges (code↔doc) | 0 | 808 | **1,016** |
| nodes spanning code AND docs | 0 | 118 | **181** |

A representative concept that previously existed as ~7 disconnected nodes now resolves to **one
canonical node** spanning its code definition, ~6 docs, 2 ADRs, and tests, with ~40 traversable
typed edges.

## Stage 4 (embedding-assisted linking) — measured, NOT viable as designed

Goal: link doc *concept* nodes to the code they're about via embedding cosine, for the conceptual
tail that name-matching/extraction misses. **It does not work with description embeddings.**

Measured concept→code best-cosine (n≈5,100 concepts):
`p50=0.416  p90=0.543  p99=0.645  max=0.756`
vs within-group `code↔code p50=0.755`, `concept↔concept p50=0.656`.

Code and concept embeddings sit in **different regions of the space** (cross-modal gap). A
precision-safe threshold (~0.78) recovers ~0; lowering it imports noise. The mutual-kNN guard
correctly refused to fabricate a hairball.

**Decision:** do not ship Stage 4 as cosine-on-descriptions. Leverage stays in S1–S3.

If doc→code recall matters more later, the viable paths (NOT cosine-on-descriptions):
- **(A) Gloss embeddings** — emit a one-line natural-language "what this is" per code entity and
  embed *that* (not the structural `Module:/Exports:` dump), so the two modalities are comparable.
- **(B) LLM pair-judge** on token-prefiltered candidate pairs — precise but slow; gate hard against
  confabulation (ADR-0009).

`semantic_linker.py` (the untyped embedding recall layer for variant A) was **removed** — ADR-0027
rejected it in favour of deterministic `path:Symbol` resolution. Revisit only as a *judged* pass per
that ADR.

## Caveats worth an ADR note

- **ADR-0016's cost assumption is provider-specific.** It assumed prompt caching (~85% hit) would
  amortize the ~2k-token context prefix. On a backend with **no prompt caching**, the contextual
  re-ingest cost ~11× the non-contextual pass and ~5× wall time. Mitigation: lower
  `code_context_tokens`, or treat it as a once-per-code-change cost.
- **The embedding deployment is the throughput bottleneck, not chat.** The chat model had ample TPM;
  the embedding endpoint rate-limited (429s) under high concurrency. Retry/backoff+jitter absorbs it;
  keep `parallel_requests` moderate (~24).
- **`/init-reference` is a phantom** — the materializer advertises it (`reference_docs.py`) but no such
  skill exists. Build it or stop advertising it. (Left for now.)
- 1–2 doc chunks consistently fail JSON extraction on the reasoning model (content filter / empty
  output) — skipped harmlessly.

## Model & embedding limitations we're hitting

1. **Embedding cross-modal gap.** The embedder encodes *surface text*. A structural code description
   and a conceptual doc sentence about the same thing land far apart (median concept→code cosine
   ≈0.42, ceiling ≈0.76 — barely the *median* of code↔code). Embeddings can't *discover* doc↔code
   links. They're strong for (a) **disambiguation** among a narrow same-name candidate set, and (b)
   **retrieval ranking** (query↔passage, no absolute threshold) — and weak for open-ended discovery.
2. **Similarity ≠ identity ≠ typed relation.** Cosine yields a "related neighborhood," not "is the
   same as" or "implements/governed-by." Drawing edges from it erases edge semantics and risks the
   confabulation engine ADR-0009 rejects.
3. **Reasoning-model quirks.** Rejects `max_tokens` (needs `max_completion_tokens`); reasoning tokens
   eat the completion budget (truncation risk); ungrounded, it emits *descriptive* relationship
   targets, not real identifiers (~5% matched code names before contextual extraction).
4. **Prompt caching is provider-specific** — a "cache-friendly constant prefix" design can cost full
   price on a backend without it.
5. **Two ground truths, neither complete.** AST = precise names, no "why"; LLM = "why", fuzzy names.
   Bridging them is a *naming/grounding* problem (S1–3), not a vector-similarity one.
