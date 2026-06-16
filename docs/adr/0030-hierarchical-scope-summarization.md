# ADR-0030: Hierarchical scope summarization over the directory tree

**Date:** 2026-06-09
**Status:** Proposed (amends ADR-0007 and ADR-0008)

## Context

The thesis is altitude composition — "context at one altitude doesn't compose into context at
another" — yet every scope summary is generated flat and independently from its own entities
(Phase 4, ADR-0007). A parent directory's AGENTS.md does not compose its children's; the
portfolio root does not compose its projects'. The altitude axis is asserted, not built,
inside the kernel's own output.

The research base (docs/research/2026-06-09-hierarchical-materialization-and-importance-ranking.md §1):

- Recursive summarization works and compresses hard: RAPTOR (arXiv:2401.18059) sustains ~0.28
  summary/children token ratio with quality gains; GraphRAG root summaries at 2.3–2.6% of
  corpus tokens still win 72% of comprehensiveness comparisons (arXiv:2404.16130).
- The error-compounding fear is measured and small: RAPTOR's audit of 150 summary nodes found
  4% node-level hallucination and **zero upward propagation**.
- Structure-given trees beat derived clusters for code: every successful repo-level system
  (arXiv:2501.07857; ICCSA 2025; Meta-RAG arXiv:2508.02611) composes over the directory tree;
  none clusters. Agentless showed the bare tree is a top-tier signal.
- Incremental recomputation: the dirty set for a change is exactly the ancestor chain of
  changed scopes — far simpler than GraphRAG's community maintenance.

## Decision

1. **Bottom-up composition over the directory tree.** Phase 4 processes scopes deepest-first.
   A leaf scope summarizes from its ranked entity descriptions (unchanged). A non-leaf scope
   summarizes from **its children's summary texts + its own direct entities**, ranked by the
   Phase-4 weight (ADR-0015; × importance once ADR-0031 lands). Project and portfolio roots
   are the top of the same recursion — the cross-project orientation that v1's flat root
   summary approximated becomes composed.
2. **A non-leaf prompt variant** in the Summarizer: given child summaries and local entities,
   write the parent orientation — shared purpose, how children divide the responsibility,
   cross-child seams. Token budget unchanged (300–500); target ~3–4× compression per level.
   Children that exceed the prompt budget are truncated by rank with the truncation noted in
   the output.
3. **Caching composes for free — by construction.** The parent prompt is built from child
   summary *content*, so the existing content-addressed summarizer cache gives the no-op
   property: unchanged child text → unchanged parent prompt hash → cache hit. No new cache
   machinery; this is a constraint on prompt construction (never build parent prompts from
   file lists or timestamps).
4. **Mechanical verification (decompose-then-verify, mechanized).** After generation, extract
   backtick-quoted identifiers and path-like tokens from the summary; each must appear in the
   scope's entity-name set ∪ child-scope names ∪ source paths. On failure: one retry with the
   offending names listed; then fall back to the deterministic `_generate_scope_summary`.
   Failures log to the journal — the summarizer's own effective-false-positive meter.
5. **Freshness composes (amends ADR-0008).** A scope summary's digest input includes its
   children's summary digests, so a leaf change re-materializes exactly its ancestor chain
   and `ck check` sees parent files as stale when any descendant changed.

## Considered options

- **Leiden/cluster-derived hierarchy (GraphRAG-style).** Rejected: code's native tree is
  authoritative, free, and what agents navigate; no evidence clustering beats it for code
  orientation. Clustering remains available to cross-cutting views.
- **Top-down decomposition (summarize root from raw corpus, then refine).** Rejected: breaks
  incrementality (every change dirties the root input) and the cache-composition property.
- **No verification pass.** Rejected: the verifier is nearly free (symbol tables exist), and
  the HANDOFF.md incident showed fabricated/stale names in summaries are the kernel's worst
  failure class.

## Consequences

- The altitude thesis becomes implemented behavior: an agent at the portfolio root reads a
  summary *derived from* the project summaries, which derive from scope summaries, which
  derive from entities — with freshness guaranteed at every level.
- Phase 4 gains an ordering constraint (deepest-first) and a verification step; wall-clock
  cost is bounded by the ancestor-chain property (a one-file edit re-summarizes its chain,
  typically 3–5 scopes).
- ADR-0008's graph-commit/freshness derivation is amended (child-digest inclusion);
  re-ingest is the migration as usual.
- Hallucination risk is bounded by measurement (4%, non-propagating) plus the verifier; the
  journal makes the kernel's own summary-failure rate observable.

## When this should be revisited

- Verification-failure rate persistently above a few percent per ingest → the prompt or the
  model is wrong for non-leaf composition; re-grill before trusting parent summaries.
- Very wide directories (>30 children) blow the prompt budget even after rank-truncation →
  consider intermediate grouping (sub-summaries by sibling cluster) as a measured exception.
- The eval (ADR-0029) shows flat summaries matching hierarchical ones at the root → the
  composition is not earning its cost; investigate before expanding it.

## Related

- [ADR-0007](./0007-per-scope-summaries-at-ingest.md) — the flat Phase-4 this amends.
- [ADR-0008](./0008-content-derived-graph-commit.md) — freshness identity amended (child digests).
- [ADR-0031](./0031-structural-importance-pagerank.md) — ranking used for prompt selection.
- [ADR-0029](./0029-private-paired-eval-harness.md) — measures the composition's value.
- docs/research/2026-06-09-hierarchical-materialization-and-importance-ranking.md §1.
