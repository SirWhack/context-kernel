# ADR-0031: Structural importance — reference-graph PageRank for materialization selection

**Date:** 2026-06-09
**Status:** Proposed (extends ADR-0015)

## Context

ADR-0015's centrality deliberately counts distinct-source in-degree over the doc-linkage kinds
(`implements`, `inherits`, `realizes`, `governed-by`, `implemented-by`) and deliberately
excludes `calls` (0.6) and `imports` (starved at 0.3). That is the right design for its
question — *what is well-grounded, where are the documentation gaps* — but it leaves the
kernel without the importance signal that has the most production precedent for deciding
**what makes the cut** in a token-budgeted orientation artifact: reference-graph ranking.

Evidence (docs/research/2026-06-09-hierarchical-materialization-and-importance-ranking.md §2):

- Aider's repo map (recipe verified from `repomap.py`): tree-sitter defs/refs → file-node
  graph with damped edge weights → PageRank → rank redistributed to definitions →
  binary-search the token budget. The most-copied production precedent for "pre-computed,
  token-budgeted code orientation."
- HippoRAG's Personalized PageRank (+20% multi-hop QA, NeurIPS 2024) and LocAgent (92.7%
  file-localization over a typed code graph) show graph diffusion over reference structure is
  the working signal.
- **Honest gap:** no published ablation shows PageRank beating plain in-degree for LLM context
  selection. The choice is plausible-but-unproven; both are cheap.

## Decision

1. **A pure `importance()` in `scoring.py`** — `importance(nodes, weighted_edges, *,
   damping=0.85, personalization=None) -> dict[node_id, float]` — keeping the module's no-I/O
   tenet (the ingester prepares edges and feeds them in; NetworkX may be used for the solver).
2. **Computed at ingest over the structural family only**: `calls`, `imports`, `inherits`,
   `implements` (and `contains` at low weight) — exactly the edges centrality excludes.
   Semantic/doc edges stay out: importance answers "what does the *code* treat as
   load-bearing," and letting chatty docs mint importance would re-open the lexicon-inflation
   hole ADR-0015 closed for centrality.
3. **Aider's multipliers, adapted:** target name starting with `_` → ×0.1 (private plumbing);
   target whose bare leaf is defined in >5 files → ×0.1 (ambiguous; the resolver's
   `ambiguous_names` already knows); no sqrt-multiplicity term (the store dedups
   `(source, target, kind)` so multiplicity ≤ 1).
4. **Stored, normalized, additive.** Normalized to [0,1] by graph max;
   `Entity.importance: float = 0.0` joins `centrality` as an additive schema field
   (serialization in the store adapter). Like centrality, it is **never folded into
   confidence** — trust and structural load stay independently visible.
5. **Consumption.** Phase-4 ranking becomes
   `ranking_weight = confidence × (1 + centrality) × (1 + importance)` (boosts, never gates —
   the ADR-0015 refinement lesson). ADR-0028's section selection multiplies by
   `(1 + importance)`. `find` is untouched by default (same stance as centrality:
   a query wants relevant results, not central ones; a knob exists for the eval).
6. **The open question ships as a knob.** `CK_SCORING_IMPORTANCE_MEASURE = pagerank | indegree
   | off` (default `pagerank`, provisional). ADR-0029's harness decides it — this ADR
   explicitly does not claim PageRank superiority, only that *some* reference-graph importance
   signal must exist.
7. **Scope-local personalization** (with ADR-0030): when ranking for scope S's materialization,
   personalization mass sits on S's entities — "important from S's vantage point" — replacing
   aider's chat-session personalization, which has no analog in a pre-materialized file.

## Considered options

- **Widen ADR-0015 centrality to include `calls`/`imports`.** Rejected: centrality's
  distinct-source rule and kind-set are load-bearing for the documentation-gap/health use
  case; widening it would blur two different questions into one number. Two fields, two
  meanings, both visible.
- **Betweenness or HITS instead of PageRank.** No evidence either way for this use; PageRank
  chosen for precedent (aider, HippoRAG, ComponentRank) and O(edges) iteration. The knob keeps
  the door open.
- **Compute at query time.** Rejected: importance is query-independent (ARCHITECTURE tenet 2 —
  work belongs at materialization).

## Consequences

- The kernel gains the one selection signal the review found missing, at small cost (one
  power-iteration per ingest, one float per entity).
- `EDGE_WEIGHTS` gains a second consumer (edge preparation for importance) — the
  one-policy-table property of ADR-0023 §1 extends rather than forks.
- Centrality redistribution from ADR-0026 (classes → methods) now also shapes importance;
  method-granularity is what makes `calls`-based ranking meaningful.
- Re-ingest is the migration (schema field addition; ADR-0008).

## When this should be revisited

- The ADR-0029 A/B shows `indegree` matching `pagerank` → flip the default to the simpler
  measure and record it (Occam).
- Importance and centrality turn out to correlate so highly on real corpora that one is
  redundant → consider retiring one *after* checking the health/gap consumer still works.
- The composite `confidence × (1+centrality) × (1+importance)` shows ordering pathologies in
  Phase-4 selection → sweep the composition shape in the eval rather than hand-tuning.

## Related

- [ADR-0015](./0015-entity-confidence-scoring.md) — the axes this extends; boost-not-gate lesson.
- [ADR-0026](./0026-methods-as-first-class-nodes.md) — method nodes that make `calls` ranking meaningful.
- [ADR-0028](./0028-edge-derived-agents-md-sections.md), [ADR-0030](./0030-hierarchical-scope-summarization.md) — consumers.
- [ADR-0029](./0029-private-paired-eval-harness.md) — decides the open measure question.
- docs/research/2026-06-09-hierarchical-materialization-and-importance-ranking.md §2.
