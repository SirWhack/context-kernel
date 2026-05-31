# Query-time expansion A/B + the corpus reframe (2026-05-30)

Built ADR-0023 neighbor expansion to make the graph visible at query time, then measured it.
The measurement came back **no measurable gain on model-time** — and chasing *why* surfaced a
reframe that reorganizes the whole eval program.

## What was built

`find` now expands along edges (ADR-0023): a strong seed's 1-hop neighbors are pulled into the
candidate set, scored by `seed.find_score × edge_weight(kind) × hop_decay × neighbor.confidence`
— no kind allowlist, `edge_weight` gates (imports@0.3 self-starves, governed-by@0.95 surfaces).
Knobs `CK_SCORING_EXPANSION*`. Provisionally default-on, **unvalidated** (see verdict).

## The measurement (`scripts/expansion_ab.py`)

A deterministic, agent-free A/B: 10 model-time "why / what-governs" questions, each with gold
source paths (the ADR/code that answers it). For each question we retrieve **once** and apply
both rankings (expansion off, then on) to the same seed set, then read where the gold lands.

**Result: helped 0, hurt 0, unchanged 10.** Expansion never changed the rank of the best answer
and never regressed it. What it *did* do: append the **complementary-altitude** node lower in
the list — e.g. "why can't reads be stale?" keeps `THEORY.md` at rank 2 in both arms, and
expansion adds `context_kernel/freshness_gate.py` (the actual code) at rank 10, which the
doc-heavy vector hits had missed. That cross-altitude completion is real but is *not* captured
by "rank of first gold," and whether it helps an agent is untested.

### Two methodology notes (both cost us a wrong conclusion once)

1. **Double-retrieval artifact.** The first version of the probe re-embedded and re-retrieved
   *per arm*, so vector-search noise (duplicate `THEORY.md` chunks reordering) fabricated a
   "regression" that did not exist. Fix: retrieve once, rank twice. Only then is expansion the
   single variable. **Lesson: an A/B on a stochastic retriever must share one retrieval across
   arms.**
2. **`nearest_chunks` is non-deterministic across calls** — the local embedder returns slightly
   different query vectors run-to-run, reordering tied cosines. It does not affect the
   within-question off/on delta (shared retrieval), but it makes any *absolute* retrieval metric
   noisy at the top-N window boundary. Worth a stability pass before trusting fine-grained recall.

## Why expansion is a no-op here — the reframe

It is **not** that traversal is worthless. It is that **every repo we have evaluated is the
wrong kind of repo for this system.**

The Context Kernel is built for **agentic engineering — developing with/by agents**, where the
human-curated documentation layer is thin, inconsistent, or absent, and the graph is the only
thing connecting intent to code. But our entire corpus — open-webui, marimo, prefect, pydantic,
**and model-time itself** — is **human-authored and doc-rich**: careful hand-written ADRs,
THEORY, ARCHITECTURE, reference docs whose vocabulary already mirrors the code. On such a repo:

- Direct embedding search already places the governing ADR in the top 1–6 (model-time's ADR
  titles practically *are* the questions). There is nothing one-hop-away-and-invisible for
  traversal to rescue — the premise of "the answer sits one hop away, unreachable" is **false
  for a well-documented repo.**
- This is the **third** time model-time being "too good a corpus" has dissolved a hypothesis:
  it made doc↔code linking *work* (the merge needs docs that name code); it made the code-edge
  eval *flat* (code structure wasn't the bottleneck); now it makes traversal a *no-op* (direct
  retrieval already wins).

The kernel's differentiation should appear where the doc layer **doesn't** already answer the
question: **vibecoded repos** — agent-generated codebases with sparse/auto/inconsistent docs,
where the answer node shares little vocabulary with the query but *is* graph-connected to a hit.
We have been testing the system on the corpus it is **least** needed for.

## Verdict & next steps

- **Expansion: keep, default-on but flagged UNVALIDATED.** No harm shown, it implements the
  mechanism the architecture is built around, and the eval will toggle the knob explicitly
  regardless of the default. Do **not** cite this eval as evidence it helps — it shows only
  *no harm on a human-doc-rich repo.* Revisit the default after the vibecoded eval.
- **The real test is on vibecoded repos** (being pulled). Re-run `expansion_ab.py`-style A/B
  there, plus the kernel-vs-grep battery, with `CK_SCORING_EXPANSION=off` vs `on`. Hypothesis:
  expansion (and the kernel overall) beats direct search *only* where the doc layer is thin —
  that is the system's actual thesis and we have not yet tested it on its target corpus.
- **Stabilize the retriever** (deterministic query embedding / tie-break) before trusting
  fine-grained retrieval metrics.

## Artifacts

- `scripts/expansion_ab.py` — deterministic agent-free expansion A/B (battery inline; gold =
  source-path substrings).
- ADR-0023 — the expansion design and the "edge_weight gates, no allowlist" rationale.
