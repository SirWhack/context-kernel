# ADR-0023: Query-time neighbor expansion (relevance flows along edges)

## Status

Accepted

## Context

`find` retrieves by embedding similarity (top-k chunks) and then reranks that fixed set
with [ADR-0019](./0019-confidence-materialized-relevance-at-query.md)'s
`find_score = similarity × confidence × proximity`. `proximity` already reads the graph —
it is `1 + max edge_weight(kind)` over a candidate's 1-hop adjacency to the top seeds — but
it only **reorders the vector top-k**. A node the embedding search did not retrieve is never
added, no matter how strongly it is connected to a strong hit.

This makes the graph **nearly inert at query time**. A dogfood measurement of the model-time
corpus (clean re-ingest, 4,564 entities) found a richly connected graph: 73 canonical nodes
that merge a code symbol with the docs/ADRs describing it (e.g. `freshness_gate` unifies its
module with ARCHITECTURE, ADR-0003, ADR-0016), and **434 cross-altitude semantic edges**
(`realizes`, `governed-by`, `motivates`, `addresses`). Yet a query like *"why is
`freshness_gate` built this way?"* retrieves the `freshness_gate` node and **stops one hop
short of ADR-0003** — the edge that holds the answer is computed and discarded. The structural
and semantic edges we pay to extract ([ADR-0021](./0021-structural-vs-semantic-edge-families.md))
do most of their work at ingest (identity for the doc↔code merge, centrality, contextual
extraction) and almost none at retrieval.

The natural fix is to let `find` **expand**: pull a strong hit's neighbors into the candidate
set even when the vector search missed them. The design question is *which* neighbors. The
tempting answer — a categorical allowlist of "expandable" edge kinds (e.g. only the semantic
`why` edges) — is wrong twice over:

1. It **duplicates a policy that already exists.** `EDGE_WEIGHTS`
   ([ADR-0015](./0015-entity-confidence-scoring.md)/[ADR-0020](./0020-staleness-as-structural-drift.md))
   already ranks the kinds continuously: `governed-by` 0.95, `realizes`/`implements`/`inherits`
   0.9, `addresses` 0.7, `motivates` 0.5, and `imports` deliberately starved to 0.3 ("so it
   doesn't flood"). An allowlist re-encodes this as a worse boolean.
2. It **mis-classifies structural facts.** An allowlist of "semantic why-edges" would exclude
   `implements`/`inherits` — but those are 0.9-weight first-class facts that `CENTRALITY_KINDS`
   already treats as backbone. The weight table, not a kind label, is the right authority.

There is also a hard constraint: an expanded neighbor has **no query similarity** (the embedder
never scored it against this query), so it cannot enter `find_score` through the `similarity`
term. Its relevance can only be inherited from the seed that reached it.

## Decision

### 1. Expansion reuses `edge_weight`; there is no kind allowlist

`find` expands along **any** edge, gated by the existing `edge_weight(kind)` rather than a
categorical filter. This keeps a single relevance policy (ADR-0015/0019) and lets the weight
table do the discrimination it was built for: `governed-by` (0.95) surfaces readily, `imports`
(0.3) self-gates and rarely clears the threshold — without naming a single kind in `find`.

### 2. Relevance flows from the seed (spreading activation)

An expanded candidate's score is its seed's relevance, attenuated by the edge it crossed:

```
expanded_score = seed.find_score × edge_weight(kind) × hop_decay × neighbor.confidence
```

This is personalized-PageRank-lite / spreading activation. It has the property we want: an
expanded node is **always subordinate to the real semantic hit that reached it** (the seed's
`find_score` is an upper bound, since every factor is ≤ 1), so expansion augments retrieval and
never hijacks it. Confirmed via embedding similarity → traversal; the seed is the door,
the edge walk is the rooms.

### 3. Expansion is bounded and never outranks a direct hit

- Seeds are the top-3 direct hits that carry an `entity_id`; expansion is **1 hop**.
- A neighbor is admitted only if `expanded_score ≥ EXPANSION_MIN_RATIO × (weakest direct hit
  score)` — weights gate; the cap is a guardrail, not the policy.
- At most `EXPANSION_MAX` neighbors are added.
- A direct (similarity-grounded) hit **wins every tie** against an expanded (inferred) one.

### 4. Knobs are `CK_SCORING_*`, default-on, switchable

`EXPANSION_HOP_DECAY`, `EXPANSION_MAX`, `EXPANSION_MIN_RATIO`, and an `EXPANSION` on/off flag
join the existing `CK_SCORING_*` precedence (default → `[ingester.scoring]` config → env). The
on/off flag exists so the kernel-vs-grep A/B can measure the traversal delta directly. The
three numeric knobs are **uncalibrated** at adoption — the weight *ordering* is trusted (it is
the same ordering the reranker already uses), but `hop_decay`/cap/ratio are swept against the
model-time eval, not guessed.

## Consequences

- **The graph becomes visible at query time.** "Why" questions can reach the ADR/decision one
  hop from a symbol — the kernel's actual differentiator over grep, which was built but unused.
- **One relevance policy, extended — not a second one beside it.** ADR-0019's composition gains
  a graph-reachable candidate set; `find_score` itself is unchanged for direct hits.
- **Expansion quality tracks edge-weight calibration.** If a kind's weight is wrong, expansion
  surfaces the wrong neighbors. This concentrates tuning pressure on one table (good) but means
  `EDGE_WEIGHTS` is now load-bearing for retrieval, not just confidence/centrality. Revisit the
  table if the eval shows a kind over- or under-surfacing.
- **Corpus dependence is unchanged but now matters at read time.** On a doc-poor repo (docs that
  never name code, e.g. governance prose) there are few semantic edges to traverse, so expansion
  is a no-op and `find` degrades gracefully to similarity-only. The value is realized only where
  docs describe code — a corpus property, surfaced now at query time as well as ingest.
- **No new write-time state.** Expansion reads `get_neighbors` + stored `edge_weight`/`confidence`
  at query time; nothing is materialized, consistent with ADR-0019's read/write split.
