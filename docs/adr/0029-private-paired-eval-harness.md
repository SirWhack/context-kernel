# ADR-0029: `ck eval` — a private, paired, portfolio-specific evaluation harness

**Date:** 2026-06-09
**Status:** Proposed

## Context

THEORY non-goal 5 deferred the eval harness past v1. The deferral has expired in practice: at
least four accepted surfaces are tuned by intuition (edge weights, expansion hop-decay/caps,
the resolver's 0.82 similarity threshold, authority tiers); ADR-0023 ships default-on and
self-labels UNVALIDATED; and every proposed normative feature (ADR-0032, ADR-0036) explicitly
gates agent-facing exposure on measured precision. The kernel cannot promote, calibrate, or
honestly describe these without an instrument.

The research base (docs/research/2026-06-09-hierarchical-materialization-and-importance-ranking.md §4):

- The bar to beat is *strong agentic grep* — naive lexical retrieval is already near graph
  parity for repo-level tasks (GrepRAG, arXiv:2601.23254). A weak baseline arm is a straw man.
- Localization hit-rate is the cheap, sensitive proxy: retrieval, not generation, dominated
  SWE-bench failures (arXiv:2310.06770).
- Public benchmarks are the wrong primary instrument: contamination plus task defects
  (SWE-bench Verified: 59.4% of o3-failures had material test/spec defects; OpenAI retired it).
- LLM-judge bias is documented and correctable (position/verbosity/self-enhancement,
  arXiv:2306.05685): swap order, blind provenance, reference-guided, one fixed judge config.
- Paired bootstrap over tasks is the appropriate significance test (most LLM evals skip
  significance entirely; arXiv:2405.14782).

The kernel already owns the precursor patterns: `scripts/h2_eval.py` (kernel-vs-grep A/B with
a precision oracle), `scripts/expansion_ab.py` (deterministic paired comparison),
`evals/runs/` (run logs), and `LLMMetrics` (cost accounting on the ingest side).

## Decision

1. **Suite format.** `evals/suite.yaml`: entries
   `{id, question, altitude: file|scope|project|portfolio, kind: locate|orient|why,
   gold: {paths: [...], symbols: [...]}, notes}`. Target 50–100 questions across the
   portfolio's repos, all four altitudes.
2. **Re-enactment gold mining.** A miner walks `docs/adr/*.md` and closed issues, maps each to
   the files/methods its implementing commits changed (`git log --name-only` over the merge
   window). This is the feature-location field's standard gold-set method and is free from
   the portfolio's own history. Mined entries are reviewed before admission to the suite.
3. **Two arms, same everything else.** (a) *kernel*: agent session over the materialized tree
   + MCP `find`; (b) *baseline*: identical agent and budget with `.context-kernel/` masked,
   Read/Grep/Glob only. Strong baseline by construction.
4. **Metrics.** Primary: deterministic file/symbol hit-rate@k against gold for `locate`/`why`.
   Secondary: tokens in/out, tool calls, wall-clock per question (extend `LLMMetrics` to the
   read side). `orient` questions only are LLM-judged: blinded, order-swapped,
   reference-guided, one pinned judge config.
5. **Statistics.** Every question paired across arms; paired bootstrap over questions
   (10k resamples, 95% percentile CIs); per-altitude splits reported. No headline claims
   without intervals.
6. **Outputs and invocation.** `ck eval [--suite path] [--arms kernel,grep] [--label name]`
   writes `evals/runs/<date>-<label>.md` (existing convention) with config hashes pinned so
   runs are reproducible.
7. **The harness is the gate.** ADR-0023's expansion flag, ADR-0031's importance knob,
   ADR-0030's hierarchy, ADR-0032/0036's agent-facing promotion all cite an eval run or stay
   in their pre-promotion state. Future scoring-knob changes ship with a sweep, per the
   existing `CK_SCORING_*` design intent (ADR-0015).

## Considered options

- **Adopt a public benchmark (SWE-bench/CodeRAG-Bench/RepoQA) as the instrument.** Rejected as
  primary (contamination, task defects, wrong corpus — the kernel targets its own portfolio).
  Borrow their *shapes*: RepoQA-style find-the-function, LocAgent-style which-files.
- **LLM-judge everything.** Rejected: deterministic hit-rates are cheaper, unbiased, and cover
  `locate`/`why`; the judge is confined to `orient` where no gold exists.
- **Synthetic question generation by LLM.** Rejected for the core suite (distribution drift
  from real use); acceptable for smoke tests. Suite refreshes come from real session
  transcripts.

## Consequences

- Uncalibrated-knob debt becomes payable: expansion, importance measure, edge weights,
  thresholds get swept against one instrument.
- A standing cost: the suite must be maintained as the portfolio evolves (gold paths move).
  The re-enactment miner re-runs cheaply; stale gold shows up as impossible questions.
- The corpus-dependence caveat from ADR-0023 becomes testable: add a doc-thin agentic repo to
  the portfolio and the same suite measures the kernel where it claims to matter most.

## When this should be revisited

- Suite overfitting (features tuned to the 100 questions) → quarterly question refresh from
  real transcripts; hold out a rotation split.
- If hit-rate@k and judged orientation quality diverge persistently → the gold sets are
  measuring the wrong thing; re-grill question design.

## Related

- [ADR-0023](./0023-query-time-neighbor-expansion.md) — first consumer (validation debt).
- [ADR-0015](./0015-entity-confidence-scoring.md) — the knob layer built for sweeps.
- [ADR-0031](./0031-structural-importance-pagerank.md), [ADR-0032](./0032-tenets-authored-design-rules.md),
  [ADR-0036](./0036-design-signals-view.md) — gated consumers.
- EVALS.md; `scripts/h2_eval.py`; `scripts/expansion_ab.py`; evals/runs/.
- docs/research/2026-06-09-hierarchical-materialization-and-importance-ranking.md §4.
