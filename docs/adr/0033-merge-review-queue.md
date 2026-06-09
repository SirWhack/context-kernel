# ADR-0033: Merge review queue — curated resolution constraints for recall without lost determinism

**Date:** 2026-06-09
**Status:** Proposed (extends ADR-0017)

## Context

ADR-0017's resolver is deliberately conservative: normalized-name clustering, code-anchored
canonicals, never-guess-ambiguous, embeddings only as a collision-guard second signal. The
canonicalization literature is unanimous that this under-merges (CESI, WWW 2018; EDC,
arXiv:2404.03868) — real duplicates remain: high-cosine cross-cluster pairs whose surface
names differ, doc concepts naming exactly one method leaf (ADR-0026's deferred merge), and
collision-guard deferrals. But the obvious fixes are worse: inline embedding or LLM merging is
non-deterministic (breaking idempotent regeneration) and is the "confabulation engine"
ADR-0009/0017 rejected.

The production pattern that resolves the tension
(docs/research/2026-06-09-ontology-and-entity-resolution.md §1–3):

- **Queue only where signals disagree** (query-by-committee); humans on the gray zone gives
  enforceable precision *and* recall at bounded cost (HUMO, ICDE 2018; r-HUMO).
- **Persist human verdicts as first-class inputs re-applied on every rebuild** (Apple Saga's
  quarantine model, running since 2018) — the merge itself stays deterministic.
- **Order the queue pay-as-you-go** so any review-session prefix is the best use of that time
  (Whang et al., TKDE 2013) — for one operator, the difference between a used queue and an
  ignored one.
- **Record rejections too**: split/merge-repair operates on must-link *and* cannot-link
  constraints; without recorded rejections the queue re-asks settled questions.
- LLM as merge-*verifier* (EDC's feasibility veto), never merge-proposer; zero-shot (in-context
  examples measurably degrade small models).

## Decision

1. **The resolver emits merge candidates.** `resolve()` additionally returns
   `merge_candidates: list[MergeCandidate]` — `(left_id, right_id, reason, cosine,
   evidence_excerpts)` — for: (a) cross-cluster pairs with cosine ≥ `θ_review` (default 0.75,
   below the 0.82 auto-guard) whose normalized names differ; (b) doc-only concepts whose name
   matches exactly one code-method leaf; (c) collision-guard deferrals. Pure change — no new
   I/O in the resolver.
2. **Optional LLM verifier pre-filter.** `Summarizer.judge_merge(left_desc, right_desc) ->
   bool`, zero-shot, content-addressed verdicts (the `judge_aspect` pattern), runs only on
   queued candidates; absent judge → no-op (tests stay LLM-free).
3. **Materialized queue.** `views/merge-queue.md`, ordered by expected gain
   (`cosine × max(centrality) × evidence_count`), each row showing names, sources, cosine,
   judge verdict, one-line description excerpts, and the **exact overlay snippet to paste**
   for accept or reject.
4. **Verdicts live in the ontology overlay** (ADR-0025 composition), both polarities:

   ```yaml
   concepts:
     turn-panel:
       altLabel: [TurnPanelResponder]      # accept → alias-driven deterministic merge
       hiddenLabel: [trn-panel]            # NEW: match-only strings, never rendered (SKOS)
   resolution:
     distinct-from:
       - ["Client (src/api.py)", "Client (src/db.py)"]   # reject → cannot-link, never re-asked
   ```

   The loader applies `altLabel`/`hiddenLabel` before clustering (fold surfaces into the
   cluster key) and `distinct-from` as cannot-link constraints (forbid cluster union).
   `hiddenLabel` is added to the concept-type schema as the third SKOS label tier.
5. **Idempotence is the contract.** Re-ingest is a pure function of *source + curated
   constraints*: same inputs, byte-identical graph. Recall improves only through curation —
   never through inline fuzzy matching.
6. **Verdicts are re-validated, not immortal** (Saga's rule): a verdict whose justifying
   evidence changes — the content hash of either side's defining source — is flagged back
   into the queue rather than silently kept.

## Considered options

- **Lower the inline collision-guard threshold instead.** Rejected: trades the precision
  stance of ADR-0017 for unaudited merges; the 0.82 guard stays as-is.
- **Auto-promote above a high cosine bar (no human).** Rejected: AutoKnow-style self-driving
  promotion depends on behavioral-log signal a personal kernel lacks; without it this is
  precision drift with no owner.
- **A separate curation file instead of the ontology overlay.** Open sub-decision; the overlay
  is proposed because it keeps one curation surface, one composition mechanism, one hash —
  revisit if `distinct-from` volume swamps the file.
- **LLM proposes merges directly.** Rejected — the confabulation-engine stance of
  ADR-0009/0017 stands; the LLM only vetoes.

## Consequences

- The under-merge debt becomes visible (the queue's size *is* the measurement) and payable in
  bounded operator time, with every payment persisted.
- `Entity`/resolver schema: no change to identity derivation; aliases already exist
  (ADR-0017). New: `hiddenLabel` in the concept schema, `resolution.distinct-from` in the
  overlay schema, `MergeCandidate` in resolver returns.
- ADR-0026's "leaf-aware merge" follow-up lands here as queue category (b) instead of as an
  automatic rule — the human gate is the second signal.
- The queue's own quality is measurable: accept/reject ratios in the journal are its
  effective-FP rate; `θ_review` tunes against verdict history.

## When this should be revisited

- Accept-rate persistently >90% for a candidate category → that category has earned
  auto-merge; promote it to a deterministic resolver rule (with the evidence recorded).
- Accept-rate <30% → `θ_review` is too low or the verifier prompt too weak; tune against the
  verdict log, or disable the category (Tricorder's disable-don't-tune).
- Cross-project candidates appear (same concept, two repos) → that is THEORY open question 1
  arriving with data; decide entity-vs-concept bridging there, not here.

## Related

- [ADR-0017](./0017-entity-resolution-identity-merging.md) — the deterministic core this extends.
- [ADR-0026](./0026-methods-as-first-class-nodes.md) — the deferred leaf-merge, now queue category (b).
- [ADR-0025](./0025-ontology-composition-per-project-overlays.md) — overlay composition the verdicts ride.
- [ADR-0009](./0009-cross-scope-relationships-via-source-id.md) — the confabulation risk that shapes the human gate.
- docs/research/2026-06-09-ontology-and-entity-resolution.md §1–3.
