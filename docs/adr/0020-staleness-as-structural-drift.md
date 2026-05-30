# ADR-0020: Staleness as structural drift, not time decay

## Status

Accepted — supersedes ADR-0015 Axis 2 (recency / time-decay).

## Context

ADR-0015 modeled the temporal confidence axis as *recency* — time-decay of a source's
last-modified date. That model is wrong at its root: **code is functionally timeless.** A
correct function written years ago, whose dependencies have not moved, does exactly the
same thing today — it has not decayed. What erodes a claim's trustworthiness is not the
passage of time but **change**: to the code it describes, to its dependencies, to the
documents around it. Calendar age was only ever a *proxy* for "probability that the thing
changed," and a poor one — it fires on old-but-valid invariants (false positive) and
misses a brand-new note already contradicted by a simultaneous commit (false negative).

Even the motivating failure — the HANDOFF.md incident — was a change signal in a time
costume: "summarizer not yet wired" became false because `LLMSummarizer` was *implemented*,
not because a week passed. Had the code never changed, the note would still be true.

## Decision

The temporal axis is replaced. **Staleness is structural drift: the magnitude of change to
a node's graph neighborhood, read from git diffs between commits — no wall-clock, no
calendar age.**

### Drift is an edge property

Divergence is relational: a document's claim about one entity can be stale while its claim
about another is current. So drift is computed and stored **per relationship**, not per
node. An edgeless prose node has no edges, hence zero drift — correct, since nothing
connected to it changed.

Per-edge storage lets each consumer aggregate differently, which matters:

- **Confidence (ranking signal)** uses the **edge-weighted mean** of a node's
  claimant-side edge drifts: `node_drift = Σ wᵢ·driftᵢ / Σ wᵢ` (weight by edge `weight`,
  ADR-0015 Axis 4). Then `confidence = authority × (1 − node_drift) × …`, centrality kept
  separate. The mean is *proportional* — a large, mostly-current doc is not buried by one
  churned reference; a small focused doc still collapses to "stale" because the drifted
  edge dominates its mean.
- **Health / the return-to-project review (issue #8)** uses a **sensitive** aggregation —
  `max` edge drift, or a count of edges over a threshold — to *flag* (not rank) any doc
  carrying a materially stale claim, and to name the specific edge
  ("HANDOFF→`LLMSummarizer` drifted 0.9").

Deliberately deferred: drift is **not** weighted by the *referent's* centrality (drift to
`KnowledgeStore` arguably matters more than drift to a private helper). Edge-weight-by-kind
approximates it, and centrality-weighting would couple two axes ADR-0015 keeps separate. A
future refinement, not v1.

### Drift is directional: referent → claimant

Each edge has a **claimant** end (the describer / dependent) and a **referent** end (the
thing described / depended upon):

```
drift(e) = normalized churn to the referent's source within ( last_commit(claimant) , HEAD ]
         , loaded on the claimant. The referent never accrues this edge's drift.
```

**Code is the reference frame.** A doc↔code edge always has code as the referent: code
drives drift into the docs that describe it, and *never* accrues drift from a doc edit
(editing a doc must not make stable, working code look stale). For code↔code edges the
dependency is the referent (`A` imports `B`; `B` churns → `A` drifts). The "referent
changed *after* the claimant last did" condition is automatic — if the referent did not
change in the window, churn is 0.

A worked example: HANDOFF.md (last commit 100) claims `LLMSummarizer` is unbuilt; the code
is then implemented and churns through commit 200. The edge's referent (`LLMSummarizer`)
changed across (100, HEAD], so drift loads on the **HANDOFF side** — exactly the end that
is out of date. Update HANDOFF and its last-commit jumps to HEAD, emptying the interval and
resetting the edge's drift to 0: "I reviewed this, it's current" falls out of the model for
free, with no annotation.

### Magnitude is size-relative, one hop

```
normalized churn = min(1, lines_changed / referent_size)
```

A 400-line change to a 400-line file is a rewrite (≈1.0); the same change to a 40k-line
file is minor. Propagation is **one hop** (direct neighbors only); transitive drift is
deferred to avoid an "everything is stale" cascade.

### Computed at ingest, from git content only

Drift is intrinsic (query-independent) and is materialized at ingest, stored on the edge —
consistent with ADR-0019. It is a pure function of git diff *content* between two commit
IDs (the claimant's last commit and HEAD); there is no "now," so it is fully deterministic
and reproducible across clones. This *strengthens* the ADR-0019 / ADR-0008 determinism
story rather than complicating it — there is no clock to pin.

### v1 scope

Doc↔code edges only: a doc node's drift comes from churn to the code entities it references
since the doc's last commit. Code↔code dependency drift (same referent→claimant rule, with
the dependency as referent) is the fast-follow.

### Relationship to contradiction detection (issue #4)

Drift is the **graded, structural** generalization of #4's **binary, semantic**
contradiction signal. The HANDOFF case trips both; an ADR whose `KnowledgeStore` churned
400 lines without an outright contradiction trips only drift.

## Consequences

- `Relationship` gains a `drift` field (alongside `weight`). `Entity` keeps `source_tier`,
  `centrality`, `confidence`; **`source_mtime` is dropped** — no timestamp is stored
  because none is used.
- Pause the project indefinitely with no changes → drift 0 everywhere; nothing falsely goes
  stale. A fresh repo → drift 0. Touching a doc resets its drift.
- The kernel gains a **return-to-project review signal**: "these docs reference code that
  moved while you were away," ranked by drift — fed to the health rollup (issue #8).
- Requires per-file git churn between commits (numstat) at ingest, reusing the
  `change_detection` git layer; the context-keyed extraction cache (ADR-0016) already
  re-reads a doc against new code state when the code set changes, and global resolution
  (ADR-0017) re-materializes the edge once both endpoints exist.
- The eval knob family shifts from recency half-lives to churn normalization (see EVALS.md).

## Related

- Supersedes ADR-0015 Axis 2 (recency / time-decay); the other three axes (authority,
  centrality, proximity) stand.
- [ADR-0019](./0019-confidence-materialized-relevance-at-query.md) — drift is materialized
  at ingest and stored; relevance is composed at query. Drift removes the last clock,
  making that determinism absolute.
- [ADR-0008](./0008-content-derived-graph-commit.md) — content-derived `graph_commit`;
  drift is pure git-content, fully aligned.
- [ADR-0016](./0016-contextual-entity-extraction.md) — context-keyed cache re-extracts a
  doc's claims against new code state.
- [ADR-0017](./0017-entity-resolution-identity-merging.md) — global resolution
  re-materializes the doc↔code edge once both endpoints exist.
- [ADR-0018](./0018-evidence-anchored-concept-edges.md) — edges as first-class carriers of
  derived signal; drift is another edge-borne signal.
- GitHub issue #4 (contradiction — drift's binary cousin), #6 (implementing work), #8
  (consumes drift for health and the return-to-project review).
