# EVALS.md

How we measure whether the Context Kernel actually works — and how to evaluate a
change before it ships. Read alongside THEORY.md (the thesis the evals defend) and
ARCHITECTURE.md (the modules the evals exercise).

## The problem evals exist to solve

The unit suite (`tests/`, 274 tests, ~8s) proves the *plumbing* is correct: chunks
flow, IDs are deterministic, blobs round-trip, freshness headers parse. It proves
nothing about *quality*, because every test substitutes `_FakeSummarizer` /
`_FakeStore` for the LLM and the graph. The fake always returns the canned answer.

But the Context Kernel's thesis is a **quality** claim, not a plumbing claim:

> Materialized files are a faithful, never-stale projection of the code — accurate
> enough that a coding agent can trust them instead of re-deriving context by hand.

Every interesting failure mode lives in the gap the unit tests skip — the behaviour
of a *real* model on a *real* corpus:

- Does the extractor emit the right entities, or hallucinate / miss / duplicate them?
- Does it actually flag a doc-vs-code contradiction, or wave it through?
- Does entity resolution merge the right nodes and leave the rest distinct?
- Does `find` return the chunk a human would have picked?
- Did orientation cost fewer tool calls / tokens than grepping by hand — the whole point?

A green unit run tells us none of this. **An eval is any procedure that runs the real
pipeline against a corpus with known-good answers and scores the divergence.** This
doc is the registry of those procedures and the methodology for adding more.

## Principles

1. **Real model, real corpus, frozen answers.** An eval that mocks the model measures
   nothing the unit suite doesn't. The whole point is to observe model behaviour.
2. **Deterministic scoring over a non-deterministic system.** The model is stochastic;
   the *oracle* must not be. Score with grep-able ground truth (a primitive exists at
   `file:line` or it does not), counted gold sets, or structural graph invariants —
   never "ask another LLM if this looks right" as the primary signal.
3. **The oracle is shared, not bespoke per run.** Reuse the same ground-truth rule
   across ingest, materialize, and eval so the score isn't circular (see
   `h2_eval.py`'s aspect-precision note). One oracle, many call sites.
4. **A number plus its corpus.** Every score is meaningless without the corpus and
   commit it was measured against. Record both. A regression is a delta on a *fixed*
   corpus, not a vibe between two different runs.
5. **Corpora and transcripts stay local.** Eval *harnesses* are committed; the gold
   sets, transcripts, and re-ingested graphs they read are corpus-specific and
   git-ignored. Ship the ruler, not the thing measured.

## What we evaluate (dimensions)

| Dimension | Question | Oracle | Harness |
|---|---|---|---|
| Extraction quality | Right entities, no hallucination/dupes? | Counted gold entity set per chunk | _(needed)_ |
| **Contradiction detection** | Are doc-vs-code contradictions surfaced? | Code-state ground truth (entity exists ⇒ "unbuilt" claim is stale) | _(needed — see below)_ |
| Entity resolution | Merge rate; over/under-merging | Known alias clusters; dup-rate on a fixed corpus | `verify_graph.py` (partial) |
| `find` retrieval | Top-k contains the right chunk? | Gold query→chunk pairs | _(needed)_ |
| Orientation cost/precision | Fewer tool calls than grep; no hallucinated paths | Path resolution + primitive counting | `scripts/h2_eval.py` |
| Freshness | Stale read ever served? | Header vs source-tree hash | Covered by unit tests + invariant |

The empty Harness cells are the work. This doc grows a row's harness as each feature
matures past the fake-summarizer stage.

## Case study: doc-vs-code contradiction detection (issue #4)

This is the first feature to reach "implemented but not eval'd," so it sets the
template.

**The change.** The extractor flags a doc claim that contradicts a known code entity
as `kind: stale-claim` (ADR-0016); `ingest()` surfaces these as warnings + a
`contradictions` count and keeps them out of the canonical graph so the
code-anchored resolver (ADR-0017) can't absorb the signal into the very node the
claim contradicts.

**What the unit tests prove.** Given a summarizer that *already* returns a
`stale-claim`, the plumbing routes it correctly: not persisted as an entity, the
code node stays uncontaminated, a warning is logged, the count is reported.
(`tests/test_ingester.py::TestContradictionDetection`.)

**What the unit tests do NOT prove — and what the eval must.** Whether a *real* model
on *real* docs emits the `stale-claim` at all, and how often it's right:

- **Recall** — of the doc claims that genuinely contradict the code, what fraction
  did the extractor flag? Misses are silent (a false claim sails into the graph).
- **Precision** — of the claims it flagged as `stale-claim`, what fraction are truly
  contradictions vs. the model being trigger-happy (flagging an accurate or
  forward-looking statement as stale)?

**The canonical fixture: the HANDOFF.md incident (2026-05-27).** A stale handoff note
asserted "Summarizer not yet wired" while `LLMSummarizer` was already instantiated;
the false claim poisoned the ROOT summary. That is exactly one true contradiction
with a known-correct verdict — the seed of the gold set.

**How to run the eval (the procedure to build before the large run):**

1. **Corpus.** A small portfolio with planted contradictions: docs making N claims
   that the code contradicts (the HANDOFF case + variants) plus M accurate claims as
   negative controls (must NOT be flagged). Gold lives in a local
   `evals/contradictions/gold.toml` — `(source_file, claim, contradicted_entity,
   is_contradiction)` per row.
2. **Run** real ingestion (`ck ingest` with the cloud summarizer) against the corpus.
3. **Score.** Parse the `stale-claim` warnings / `contradictions` count from the
   ingest log against gold → precision, recall, F1. The oracle is code state itself:
   a claim of "unbuilt/missing" is stale iff the named entity exists in the Phase-1
   graph — grep-deterministic, no second LLM.
4. **Record** the score with corpus hash + graph_commit + model id. This is the
   baseline; a later prompt tweak is a regression iff F1 drops on the same corpus.

Until step 3's harness exists, issue #4 stays **open** — "implemented, not eval'd."

## How to evaluate any change

Before merging a change that touches extraction, resolution, materialization, or
retrieval:

1. **Unit suite first** — `PYTHONPATH=. .venv/bin/python3 -m pytest tests/ -x -q`.
   Necessary, never sufficient. It guards the plumbing only.
2. **Pick the dimension** the change moves from the table above. If it has no harness
   yet, the change isn't done — building the harness is part of the change (that is
   the standing lesson of issue #4).
3. **Baseline before, score after, same corpus.** Capture the metric on the current
   build first; a change with no before-number can't be shown to help.
4. **Watch the off-axis dimensions.** Resolution changes leak into `find` quality;
   prompt changes leak into cost. Re-run neighbours, not just the target row.
5. **Record corpus + commit + model** next to every number.

## Tuning knobs (scoring)

The confidence/relevance scoring system (ADR-0015, ADR-0019) is **eval-tunable**. Every
knob resolves through three layers, highest wins:

```
hardcoded default  →  .context-kernel/config.toml [ingester.scoring]  →  CK_SCORING_* env var
```

The env layer exists so an eval sweep overrides a knob **per run without editing files** —
`CK_SCORING_AUTHORITY_DEFAULT=0.4 ck ingest …`. The knobs:

| Env var | Controls | Default |
|---|---|---|
| `CK_SCORING_AUTHORITY_DEFAULT` | catch-all tier for unmatched prose | `0.3` |
| `CK_SCORING_AUTHORITY_<TIER>` | authority of a named tier (`THEORY`, `ADR`, `CODE`, …) | per ADR-0015 table |
| `CK_SCORING_DRIFT_HOPS` | propagation hops for drift (ADR-0020) | `1` |
| `CK_SCORING_DRIFT_NORM` | churn-normalization mode (`size-relative` \| `absolute`) | `size-relative` |
| `CK_SCORING_EDGE_WEIGHT_<KIND>` | proximity weight of an edge kind | per ADR-0015 table |
| `CK_SCORING_PROXIMITY_HOPS` | seed-neighbour hop limit in `find` | TBD |
| `CK_SCORING_CENTRALITY_IN_FIND` | whether centrality factors into find relevance (`0`/`1`) | TBD |

> The temporal knob is **not** a time decay — there is no half-life. Drift (ADR-0020) is
> git-measured structural change, so its only knobs are *how far it propagates* and *how
> churn magnitude is normalized*.

Because confidence is **materialized at ingest** (ADR-0019), an authority/drift/centrality
knob change requires a **re-ingest** to take effect; proximity/find knobs apply at query
time and take effect immediately. A scoring sweep is therefore: set `CK_SCORING_*`, re-ingest
the eval corpus, score against gold, record `(knob values, corpus hash, model)` with the result.

## Existing harnesses

- **`scripts/h2_eval.py`** — orientation-session eval. Scores Claude Code transcripts
  on cost (tool calls, dup reads, tokens), hallucination (claimed paths that resolve
  to nothing), and aspect precision (claimed files that actually contain the
  coordination primitive). The reference for "deterministic oracle over stochastic
  output." Reads `$CK_PORTFOLIO/.context-kernel/ontology.toml`.
- **`scripts/verify_graph.py`** — structural graph check after a re-ingest:
  cross-altitude (code↔doc) edge density and traversal of a known merged concept. The
  seed of an entity-resolution eval.

## Before the large eval (current state)

Features are landing faster than their harnesses (#4 done, eval pending; #6 confidence
scoring and #7 CodeSpan still to come). The plan is to batch the feature work, then
build the corpus + harnesses once and run a single large eval across all dimensions —
rather than re-ingesting per feature. This doc is the running list of what that large
eval must cover; each new feature adds its row and its fixture here as it lands.
