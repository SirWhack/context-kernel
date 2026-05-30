# ADR-0019: Confidence materialized at ingest, relevance composed at query time

## Status

Accepted

## Context

ADR-0015 defines a four-axis scoring model (authority, drift, centrality,
proximity — the temporal axis is drift per [ADR-0020](./0020-staleness-as-structural-drift.md))
but leaves the *compute-time boundary* implicit — it says scores are
"stored on the record... not query time" in a single parenthetical and names
proximity as "the only axis computed at query time," without working through why,
how, or what that costs. That boundary is the load-bearing decision, and it deserves
to be explicit.

The scoring model actually describes **two different quantities that live at different
times**:

- **Confidence** — *how much do I trust this node/edge, independent of any query?*
  Composed from authority (source tier), drift (git-measured structural divergence,
  ADR-0020), and centrality (graph in-degree). All three are intrinsic to the graph:
  the HANDOFF.md "summarizer not
  wired" node is low-trust whether you searched for "summarizer," "embeddings," or
  nothing at all.
- **Relevance** — *how relevant is this node to THIS query, right now?* Composed from
  embedding similarity (exists only once there is a query), the node's confidence, and
  structural proximity to the query's anchors in the graph (a walk that exists only
  once there is a query).

Two design problems follow from conflating them:

1. **Where is each computed?** Recomputing confidence per query would re-walk the
   entire relationship set for centrality on every `find` call and repeat work that
   did not change since the last ingest. But relevance *cannot* be precomputed — two
   of its three inputs do not exist until a query arrives.

2. **Temporal-axis determinism.** A time-decay axis (`age = now − source_modified`)
   would make confidence depend on wall-clock `now`: it drifts on every ingest even when
   no source changed, churning `graph_commit` and re-writing the whole tree on a no-op
   ingest — a direct ADR-0008 violation. ADR-0020 dissolves this entirely by replacing
   the temporal axis with **drift**, a pure function of git diff *content* between two
   commit IDs — there is no `now`, so confidence is deterministic by construction.

## Decision

### 1. Confidence is materialized at ingest; relevance is composed at query time

Confidence (`authority × (1 − drift)`, with centrality used for ranking) is computed
once during `ck ingest` and **stored on the record**. Relevance is **never stored** —
it is composed per query by reading the stored confidence off the node and combining
it with this query's similarity and proximity.

```
write-time (ingest)   →  Entity.confidence, Entity.centrality, Relationship.weight  →  state.json
read-time  (find)     →  find_score(similarity, stored_confidence, proximity)
```

This honors ARCHITECTURE tenet 2 (work belongs in materialization): the expensive,
intrinsic, query-independent work happens once; only the genuinely query-dependent
slice (similarity + proximity) happens at runtime.

### 2. The temporal axis carries no clock (see ADR-0020)

The original draft of this ADR pinned a *reference time* (the newest commit in the corpus)
to keep a time-decay axis deterministic. ADR-0020 made that machinery unnecessary: the
temporal axis is **drift**, computed from git diff *content* between two commit IDs (a
node's last commit and HEAD), with **no `now` and no elapsed-time term at all**. So
confidence is deterministic and reproducible across clones by construction — there is no
clock to pin. A node whose neighbourhood has not changed since it was last touched has
drift 0; an edgeless node has drift 0. Git I/O (per-file churn) is isolated in
`change_detection.py`; the scoring functions themselves are pure and total.

### 3. The store stays a similarity mechanism; `find` composes the policy

`KnowledgeStore.search_similar` returns ranked cosine similarity and the entity handle
— nothing about trust or proximity. The relevance composition
(`similarity × confidence × proximity`) lives in one place, `find`, calling the shared
`scoring` module. The graph backend never learns the scoring policy (PoSD Ch. 7 —
different layer, different abstraction; folding the policy into the backend would leak
the same decision into two modules).

Because a free-text query has no seed entities, **the top-similarity hits become the
proximity seeds**: remaining candidates are boosted by walking outward over stored
relationship `weight`s from those seeds. This is the only graph traversal at query
time — an adjacency lookup over pre-stored weights, no LLM, no recompute of confidence.

### 4. Scoring decisions are owned by one module

All tier tables, decay formulas, edge weights, and composite rules live in
`context_kernel/scoring.py` (a pure, top-level module, peer to `change_detection.py`).
`ingest` and `find` orchestrate and call it; neither inlines a tier number or a
formula. The future health rollup (issue #8) calls the same module to explain a score.

## Alternatives considered

- **Recompute everything at query time (no stored scores).** More flexible — a scoring
  formula change needs no re-ingest. Rejected: centrality and drift are whole-graph
  computations repeated on every `find`; they repeat query-independent work; the health
  rollup (#8) has nothing to *read*; and folding live values into ranking makes results
  non-reproducible.
- **Wall-clock time-decay for the temporal axis.** Simplest. Rejected: confidence drifts
  every ingest, churning `graph_commit` and the entire materialized tree on no-op ingests
  — a direct ADR-0008 violation. (ADR-0020 goes further and removes the temporal-decay
  model altogether.)
- **Store weights similarity internally (`search_similar` returns `sim × confidence`).**
  One call, less wiring. Rejected: the backend absorbs the relevance policy (leakage),
  and it cannot host the proximity axis (search has no seeds).

## Consequences

- `Entity` gains `source_tier`, `centrality`, `confidence`; `Relationship` gains `weight`
  and `drift` (ADR-0020). Additive, with neutral defaults — no breaking change. Axes are
  stored (not just the composite) so #8 and debugging can explain *why* a score is low, not
  just *that* it is. (No `source_mtime` — ADR-0020 stores no timestamp.)
- A change to a scoring table or formula requires a re-ingest to take effect (per
  ADR-0008 migration). Acceptable: scoring tables change rarely and deliberately.
- `find` is the single relevance-composition site; the store stays pure and
  backend-swappable.
- Confidence is a deterministic function of `(source content, git history)` — two
  clones at the same commit materialize identical confidence.
- The health rollup (issue #8) is unblocked to read stored axes per scope.

## Related

- [ADR-0015](./0015-entity-confidence-scoring.md) — defines the four axes and how they
  compose; this ADR fixes *when* each is computed and *where* it is stored (refines the
  "stored on the record... not query time" parenthetical).
- [ADR-0020](./0020-staleness-as-structural-drift.md) — replaces the temporal axis with
  drift (git-content, no clock), making this ADR's determinism absolute.
- [ADR-0008](./0008-content-derived-graph-commit.md) — content-derived `graph_commit`;
  drift is pure git-content, fully aligned with it.
- [ADR-0017](./0017-entity-resolution-identity-merging.md) — resolution merges sources;
  a node's authority is the max authority across its merged sources.
- [ADR-0012](./0012-find-retrieval-via-hybrid-embedding-search.md) — the `find`
  retrieval path that this ADR extends from pure similarity to composed relevance.
- GitHub issue #6 — the implementing work. GitHub issue #8 — the health rollup that
  consumes the stored axes.
