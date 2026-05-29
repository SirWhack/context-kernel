# ADR-0018: Evidence-anchored concept edges (CodeSpan leaves)

**Status:** Accepted
**Date:** 2026-05-29

## Context

[ADR-0017](./0017-entity-resolution-identity-merging.md) made the graph **code-anchored**: the finest entity is an AST symbol, and pure-doc clusters become *concept* nodes. The concept layer the spike then built grounds concepts onto code two ways — entity-concepts by deterministic alias-match (`implemented-by`), aspect-concepts by an LLM classifier (`participates-in`) over a keyword/structural recall net, confirmed by a source-reading judge.

The H2 orientation A/B (kernel-hub arm vs `grep` arm, single-language corpus, four orientation questions) exposed a precise defect. On the concurrency **aspect** question:

- the kernel hub rated its own answer **medium confidence**, `grep` rated **high** — and *both were correct*. `grep` earned "high" because every file it claimed came with the primitive at a line (`Lock`/`Semaphore`/`wait_for` + line number) and it could prove the negative ("no `threading` anywhere"). The kernel said, verbatim, *"the hub lists participants but does not crisply separate real coordination from merely async; I inferred."*
- measured precision (`scripts/h2_eval.py`, scored against the concept's strict `precision_patterns` oracle): **kernel 79% vs grep 100%**. The kernel's false positives were files that only `await asyncio.sleep` — no shared-state coordination.

Root cause is a single omission. The source-evidence judge **reads** the matched primitive and its line to confirm each participant — then materialization keeps only (a) membership in the participant list and (b) a prose gotcha, and **discards the evidence line**. The hub records the verdict but not its justification. That one missing datum causes *both* failures: the reading agent has no receipt to be confident with (the confidence gap), and nothing downstream can distinguish a real `Lock` from an incidental `async def` (the precision gap). A "participant" with no evidence is indistinguishable from one with.

This is an open question THEORY raised twice over — the aspect-concept precision weak point, and the load-bearing risk that *"annotations must never be load-bearing"* (invariant #2). It needs a decision because the obvious fixes (store a line number; let engineers hand-tag concerns) are exactly the brittle, position-dependent, hand-maintained things this system exists to avoid.

## Decision

Promote evidence to a first-class, content-addressed graph node — a **CodeSpan** — and make an aspect concept *extensionally defined by its spans*: a concept **is** the set of code spans that instantiate it, not a label attached to symbols.

1. **CodeSpan node.** A derived blob in a new content-addressed `kind = "spans"` (alongside `embeddings`/`summaries` in `addressing.py`): `digest = sha256(symbol_id + pattern + snippet)`, attributes `{pattern, snippet}`. It carries the matched coordination primitive and the surrounding source text — **never a line number.**
2. **Two edges, one join point.** `concept —evidenced-by→ span` (conceptual axis) and `span —within→ symbol` (structural axis). The span is the precise sub-symbol location where a conceptual edge lands: structurally *owned* by the symbol (drives its lifecycle), conceptually *claimed* by the concept (gives it meaning).
3. **Addressed by content, not position.** The line number is **derived at materialize time** by relocating `pattern`/`snippet` in the symbol's *current* source. There is no stored line to go stale. Content-addressing the snippet is stable across line drift; cosmetic edits that change the snippet simply re-address it on the next ingest (same as a re-summarized chunk).
4. **Derived, never annotated.** Spans are emitted during the concept pass — the aspect classifier's judge already reads the source; it returns the matched spans instead of dropping them. They are regenerated every `ck ingest` and committed in sync by the pre-commit hook (invariant #2). No engineer ever writes `# concept: concurrency`; if a concern is findable only because someone hand-tagged it, that is the forbidden load-bearing annotation.
5. **Zero evidence ⇒ not confirmed.** An aspect `participates-in` edge with **no** `evidenced-by` span is dropped (or rendered `FLAGGED`), not surfaced as a participant. Precision becomes a **data-model property**, not a confidence cutoff: a file with no primitive acquires no leaf, so the false positive cannot render. Evidence-less edges decay automatically when the primitive is deleted from source.
6. **Evidence count is a confidence axis** ([ADR-0015](./0015-entity-confidence-scoring.md) input). Two independent signals now exist per edge — the LLM judge's verdict and the structural span count — and **their disagreement is the alarm**: LLM-confirmed + zero spans = classifier hallucination; span-rich + LLM-rejected = an over-strict judge. The kernel can now detect its own confabulated participation.
7. **Spans are shared and deduplicated by content.** One span may be `evidenced-by` multiple concepts — e.g. a single `_circuit` line is evidence for both *concurrency* and *circuit-breaker/error-handling* (both already match it in the ontology). Content-addressing makes that one node, two edges, automatically.
8. **Scope: aspect-concepts.** Entity-concepts are alias-grounded — their "evidence" is the anchor symbol itself, and their code-level gotchas come from the separate gotcha pass; spans are optional there and not over-applied.
9. **One oracle, two consumers.** The span extractor *is* `h2_eval.py`'s `precision_patterns` matcher (`find_primitive_spans(source, patterns) → [(pattern, snippet)]`). The ingest concept-pass emits spans from it; the eval scores against it. The audit stops being external and becomes the pipeline checking its own work with the same ruler.

## Measured evidence

The defect (H2 round 3): the kernel hub carried participation verdicts without the evidence the judge computed.

| concurrency aspect | r3 kernel (pre-fix) | **r4 kernel (with spans)** | grep |
|---|---|---|---|
| precision (`precision_patterns` oracle) | 79% (11/14) | **100%** (11/11) | 100% |
| error-handling precision | 92% | **100%** (14/14) | 100% |
| self-rated confidence | medium ("I inferred") | **high** | high |
| tool calls / fresh tokens | 5 / 34.4k | **5 / 34.8k** | 10 / 98.9k |

**Confirmed (round 4, spike-layer prototype of this ADR).** Emitting a CodeSpan per confirmed participant and rendering `file:line — <primitive>` leaves moved kernel aspect precision to **100%**, matching `grep`, at **2.8× fewer tokens and half the tool calls**. The reading agent read the receipts, **explicitly demoted the flagged zero-primitive participants** ("`retry.py` is an ⚠ unverified lead"), and reproduced the definition nuance carried in the hub's gotchas (`asyncio.gather` = fan-out, not shared-state coordination) — the distinction it could not make in r1–r3. Evidence-precision at classify time held **0.92–0.97** across all four aspects; zero-primitive LLM confirmations were quarantined to the flagged list (decision-points 5–6 working as data, not heuristic). The prototype lives in `scripts/concept_spans.py` (the shared oracle), `concept_classify.py` (emission), `concept_materialize.py` (rendering); the next step is promoting CodeSpan into the real graph schema (see Consequences).

## Considered options

- **Evidence on the edge `description` (no new node).** Zero schema change; fixes the hub's confidence and precision immediately. Rejected as the *durable* form because three properties want a first-class addressable thing: shared spans across concepts (the `_circuit` dual-concept case), `find`-time retrieval/embedding of evidence snippets, and auto-decay expressed as data rather than render logic. It remains the correct MVP and a valid fallback if CodeSpan cardinality proves unmanageable.
- **Store the line number on the span.** Rejected — a stored line is the most fragile possible anchor and violates invariant #2 the moment source drifts. Position is derived, never persisted.
- **Hand-annotation (`# concept: …` markers the graph trusts).** Rejected — the load-bearing-annotation trap named in THEORY. Evidence must be *derived* from source, so that deleting the code deletes the concept membership.
- **LLM free-mints evidence spans.** Rejected per [ADR-0009](./0009-cross-scope-relationships-via-source-id.md)'s confabulation risk. Spans are *proposed by pattern match and confirmed by the judge* (propose-and-drop); the LLM never invents a span the source doesn't contain.
- **Does this re-open ADR-0017's rejected "concept-hub separate from code"?** No. ADR-0017 rejected a concept node *mirroring* a code node because it "creates concept/symbol pairs to keep in sync." A CodeSpan is not a mirror of a symbol and carries no sync burden — it is regenerated from source every ingest, so there is no second copy to drift. Code remains ground truth; the span is a derived projection of it.

## Consequences

- `addressing.py` gains a `"spans"` blob kind; `protocol.py`/`lightrag_adapter.py` serialize CodeSpan nodes and the `evidenced-by`/`within` relationship kinds.
- `concept_classify.py`'s judge returns `(participant, [span])` instead of discarding the match; `concept_materialize.py` renders spans as the concept hub's leaves (`file:line — primitive`, line derived at render) and drops/flags zero-evidence participants.
- The aspect precision number is no longer a tuned cutoff — it is whatever the source contains, recomputed each ingest.
- Re-ingest is the migration (`rm -rf .context-kernel`), consistent with [ADR-0008](./0008-content-derived-graph-commit.md).
- **Cross-language note for THEORY:** this realizes the concept-as-bridge answer to THEORY's cross-language open question — a concept node stays language-neutral while its evidence legs are language-specific (`asyncio.Lock` on one side, a `Mutex`/`Promise.all` on another). The spans are exactly where language-specificity lives and where the bridge attaches. The THEORY update is tracked separately; this ADR only records the data-model decision.

## When this should be revisited

- CodeSpan cardinality explodes (spans-per-project into the thousands) → cap per (concept, symbol), keep only the strongest primitive, or fall back to edge-carried evidence.
- Content-addressing churn proves noisy (cosmetic edits constantly re-addressing spans) → address by `(symbol_id, pattern, ordinal)` instead of snippet hash.
- Entity-concepts turn out to want spans too (e.g. to pin a specific landmine line) → extend decision-point 8.
- The round-4 measurement does **not** show precision/confidence moving as predicted → the defect was mis-diagnosed; re-open the judge design before shipping the node kind broadly.
