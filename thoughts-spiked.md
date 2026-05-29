# thoughts-spiked.md — the spike that ends the reasoning

**Status:** scratch test-spec, local-only (gitignored). Companion to [`THOUGHTS.md`](./THOUGHTS.md).
Pure mechanics — no project data.

We have reasoned the concept-layer thesis to ~90% — see [`THOUGHTS.md`](./THOUGHTS.md) and the
**Candidate thesis expansion** section of [`THEORY.md`](./THEORY.md). Every claim past
[ADR-0017](./docs/adr/0017-entity-resolution-identity-merging.md) is *a priori*. This doc specifies
the **one experiment** that converts the remaining 10% from confident-but-untested into measured.
If you build nothing else from this thread, build this. Reasoning further mostly manufactures more
confident untested claims.

**Reading order:** [THEORY.md](./THEORY.md) (thesis, non-goal 2, open questions, candidate
expansion) → [THOUGHTS.md](./THOUGHTS.md) (geometry routing, worked example, design rule, the 8
unexamined gaps) → this doc (how to shoot at gaps 1–6).

---

## What we already know — the priors the spike builds on

- **[ADR-0017](./docs/adr/0017-entity-resolution-identity-merging.md):** code-anchored within-project
  resolution took cross-altitude edges 0 → ~1,016 and code+doc nodes 0 → ~181, *deterministically*.
  But its collision guard keeps same-name cross-language defs **distinct** (the `StepPanel` split —
  see THOUGHTS worked example) and **drops ~3,761 relationships** whose endpoints were conceptual
  phrases. Those drops are the conceptual tail this whole thread is about.
- **R1 (THOUGHTS / measured):** concept↔code best-cosine p50 ≈ 0.42, ceiling ≈ 0.76. Embeddings
  **cannot discover** concept↔code links. Cosine is fenced to the ≥0.82 same-name guard and the
  query door — never the graph's joints.
- **[ADR-0016](./docs/adr/0016-contextual-entity-extraction.md):** contextual re-ingest cost ~11× /
  ~5× wall on a backend with no prompt caching. Any classifier pass inherits this economics.
- **[ADR-0015](./docs/adr/0015-entity-confidence-scoring.md):** confidence scoring — accepted,
  **never implemented**. Gap 3 says it's more necessary at the concept layer than the structural one.
- **Two concept flavors (THOUGHTS):** *entity-concept* (a symbol **is** an instance →
  `implemented-by` → alias-groundable, deterministic) vs *aspect-concept* (a symbol **participates
  in** it → `participates-in` → no symbol-list to constrain against → classifier-grounded).

## The thesis under test

> *The Context Kernel is the externalized, queryable theory of the codebase* — concept→code, derived
> not annotated, kept fresh at commit time, resolving conceptual questions to precise code.
> (THEORY.md candidate expansion.)

The spike does **not** test the whole north-star. It tests the load-bearing sub-claims that, if
false, sink it — and isolates *which flavor* of concept survives.

---

## Hypotheses

Each is phrased to be killable, mapped to the THOUGHTS gap it shoots at, and to the
THEORY/ADR action its outcome forces. **Pre-register the bands below before running** — set them
now, not after seeing results, or the spike just rationalizes whatever happened.

### H1 — Grounding *recall*: mechanical grounding finds the true concept→code links (gaps 1, 5)
*Claim:* For a hand-authored concept, deterministic alias-match (entity) and a piggybacked classifier
(aspect) recover a usable fraction of the concept's true implementers — including ones code-anchoring
left disconnected (cross-file, cross-language).
*Why load-bearing:* this is the reframed [ADR-0009](./docs/adr/0009-cross-scope-relationships-via-source-id.md)
/ THEORY:68 density question — but measured as *recall against a gold set*, not "did it find ≥2"
(which is trivially gameable by picking concepts you know span files).
*Metric:* recall = found-true-links / hand-labeled-true-links, **split by mechanism (alias vs
classifier) and flavor (entity vs aspect)**.
*Provisional band:* entity/alias recall ≥0.9 expected (else a normalization/alias bug); aspect/
classifier recall ≥0.5 = go, 0.2–0.5 = needs the heavier attention link-constructor, <0.2 = aspect
grounding infeasible cheaply.

### H2 — Marginal value over the dumb baseline (gap 1) — **the existential test**
*Claim:* `resolve-concept` answers "where does concern X live" measurably better than
grep-plus-read-AGENTS.md-plus-reason.
*Why load-bearing:* if the baseline ties the graph, the concept layer doesn't earn its complexity —
record it as a negative result the way Stage 4 was recorded in TODO, and stay with materialized prose.
*Metric:* on the held-out query set, compare the **retrieved set** of (a) concept-resolve neighbors
vs (b) grep-hits ∪ AGENTS.md-mentions, scored against the same gold set: precision, recall, and a
crude effort proxy (files the agent must open to reach all gold locations).
*Provisional band:* graph recall ≥ baseline recall **+0.2** at equal-or-better precision = the layer
earns it; within ±0.1 = it doesn't, stop.

### H3 — Grounding *precision*: the derived edges are actually correct (gaps 2, 3)
*Claim:* asserted concept→code edges are right at usable precision.
*Why load-bearing:* connectivity ≠ correctness. A concept node full of false positives is *worse
than none* — it sends the bug-chaser to the wrong files. The classifier has **no deterministic
guard**, so this is where it's most likely to fail.
*Metric:* hand-check a sample of asserted edges; precision split by mechanism.
*Provisional band:* alias precision ~1.0 (else bug); classifier precision ≥0.8 = usable, 0.6–0.8 =
usable only behind [ADR-0015](./docs/adr/0015-entity-confidence-scoring.md) confidence, <0.6 =
aspect-concepts not viable as derived without the constrained link-constructor.

### H4 — Topology: the symbol×concept graph is navigable, not a hairball (gap 6)
*Claim:* concepts-per-symbol and symbols-per-concept stay in a navigable range.
*Metric:* distributions of both. (Free — just measure the graph H1/H3 already built.)
*Provisional band:* median concepts-per-symbol ≤3 and median concept size ≤~30 nodes = navigable;
beyond that, granularity (gap 7) is a real problem and concepts need splitting or query-time scoping.

### H5 — Freshness stability: re-derivation is stable enough to call "in sync" (gap 4)
*Claim:* running the classifier twice on **identical** input produces ~identical edges.
*Why load-bearing:* "kept in sync at commit time" is trivial for deterministic structural extraction
and an open problem for an LLM classifier.
*Metric:* edge-flip rate across two runs on unchanged input.
*Provisional band:* flip rate ≤5% = treat as stable (with caching/pinning); >15% = the freshness
invariant cannot extend to concepts without confidence + result-pinning.

### H6 — Query→concept lookup works against a small curated set (gap 5) — *extended*
*Claim:* an NL query resolves to the right ontology concept reliably *because the candidate set is
small* (the one regime embeddings are good at — query↔passage ranking, no absolute threshold).
*Metric:* NL-query → top-1 / top-3 concept-match accuracy over the query set.
*Provisional band:* top-3 ≥0.8 = fine; below = the agent must be shown the vocabulary, or routing
needs an LLM step.

---

## Method

**Corpus.** A real multi-language project already in the portfolio (a webapp + its backend) — gives
both an *entity-concept that spans two languages* (tests H1's cross-language bridge) and an
*aspect-concept inside one language* (tests classifier grounding). Use `CK_PORTFOLIO`, like the
existing `scripts/*.py` harnesses; reuse the summarizer cache so doc grounding is cache-hit (no LLM
spend) where possible.

**Concepts (~6, authored *before* looking at grounding output).**
- 2 entity-concepts: one cross-language (a UI component present in both frontend and backend), one
  single-language. Tests deterministic alias-match.
- 4 aspect-concepts: e.g. concurrency, error-handling, persistence/DB, external-IO. Tests the
  classifier — these are the ones with no symbol-list guard.

**Grounding wired (scoped — not the full design).**
- *Alias-match:* ontology entry carries a curated alias list; a code def whose normalized name hits
  an alias gets an `implemented-by` edge. Deterministic, no LLM. (The minimal resolver hook from the
  THOUGHTS worked example: route ontology-matched ambiguous names *up* to the concept instead of
  dropping.)
- *Classifier:* piggyback on the [ADR-0016](./docs/adr/0016-contextual-entity-extraction.md) pass —
  while reading a chunk, also emit aspect tags from the fixed 4-aspect vocabulary → `participates-in`
  edges.
- **Deferred on purpose:** the full attention link-constructor and constrained decoding (THOUGHTS).
  If classifier recall (H1) lands in the 0.2–0.5 band, *that's* the signal to build it next.

**Gold set (the real labor, shared across H1/H2/H3).** For each concept, hand-label the true set of
code locations — *before* running grounding. ~6 concepts × ~10–20 locations ≈ a few hours. This is
the ground truth the whole spike rests on; without it you measure connectivity, not correctness.

**Baseline (H2).** For each query: grep for plausible strings + read the relevant AGENTS.md scope
summaries, collect the location set a reasoning agent would land on. Score against the same gold set.

**Build artifact:** `scripts/concept_spike.py` (sibling to `resolver_prototype.py` /
`verify_graph.py` / `stage4_semantic.py`): loads ontology, runs both grounding mechanisms, emits the
concept→code edges + all six metrics. Generic / `CK_PORTFOLIO`-driven, no hardcoded names — same
sanitization discipline as the existing scripts.

---

## Decision matrix — result → THEORY/ADR action

| outcome | action |
|---|---|
| H1+H3 strong (both flavors) **and** H2 clears the +0.2 bar | Promote the candidate expansion to the **Thesis** (THEORY revision-log entry); write an **ADR superseding [ADR-0009](./docs/adr/0009-cross-scope-relationships-via-source-id.md)** ("portfolio concept ontology + concept-anchored cross-scope edges"); spec the resolver hook + classifier pass. |
| Entity strong, **aspect** precision/recall weak | Ship **entity-concepts** (alias-grounded, deterministic); **defer aspect-concepts** pending [ADR-0015](./docs/adr/0015-entity-confidence-scoring.md) confidence and/or the constrained link-constructor. Honest partial win. |
| H2 ≈ baseline | The concept *graph* doesn't earn its complexity over materialized prose + attention. **Record the negative result** (à la Stage 4 in TODO); invest in better AGENTS.md prose instead; do not build the graph layer. |
| H4 hairball / H5 high churn | Thesis may hold but isn't *operational*: do granularity (gap 7) + freshness/caching (gap 4) design before any build. |

## Explicitly NOT tested (scope discipline)

- The full attention link-constructor / constrained decoding (deferred — H1 tells us if it's needed).
- Cross-*project* bridging (THEORY non-goal 2; this corpus is one project, two languages — enough to
  falsify the cross-language claim without the cross-project machinery).
- Ontology cold-start workflow and multi-engineer/team theory (gap 8) — adoption concerns, not
  thesis concerns.
- Any change to the structural layer / [ADR-0017](./docs/adr/0017-entity-resolution-identity-merging.md)
  — it works; leave it.

## Effort

- **Minimum viable spike (H1 + H2 + H3 + H4):** gold-labeling (hours) + `concept_spike.py` (alias
  match is trivial; the classifier piggybacks the existing ADR-0016 pass) + the baseline collection.
  H4 is free once the graph exists. This quartet answers "does it work, is it correct, does it beat
  the baseline, is it navigable" — the whole existential question.
- **Extended (H5, H6):** H5 = run the classifier twice, diff (cheap). H6 = needs the NL query set
  (moderate). Add only if the MVP clears its bands.
