# ADR-0015: Entity Confidence Scoring Across Altitude Axes

## Status

Accepted. Axis 2 (recency) superseded by [ADR-0020](./0020-staleness-as-structural-drift.md);
the compute-time boundary is fixed by [ADR-0019](./0019-confidence-materialized-relevance-at-query.md);
edge-kind families/naming by [ADR-0021](./0021-structural-vs-semantic-edge-families.md).

## Context

The HANDOFF.md incident (2026-05-27) exposed a structural gap: the graph treats all entities as equally authoritative. An entity extracted from THEORY.md carries the same weight as one from a stale handoff note. When `summarize_scope()` builds an AGENTS.md summary, or `find` returns results, there is no signal to prefer current, authoritative, structurally central claims over stale, ephemeral, peripheral ones.

The thesis says Context Kernel composes context across altitudes. Today "altitude" means spatial position in the directory tree. But altitude is at least four axes, and confidence is the composite score across them.

## Decision

Entities and relationships gain a per-record confidence score computed at ingest time from four axes. This ADR defines *what* the axes are and *how* they compose; the compute-time boundary (what is materialized at ingest vs. composed per query) is settled separately in [ADR-0019](./0019-confidence-materialized-relevance-at-query.md), and the temporal axis is replaced by drift in [ADR-0020](./0020-staleness-as-structural-drift.md). In brief: the intrinsic score is stored on the record (per ARCHITECTURE.md tenet 2: work belongs in materialization, not query time), and query-time operations (`find`, `summarize_scope()`) use the pre-computed score for weighting and ranking.

### Axis 1: Authority (static, from source document tier)

The document hierarchy in CLAUDE.md already defines shelf-life tiers. Authority maps source file path to a weight reflecting how trustworthy and durable that source's claims are.

| Source tier | Authority | Rationale |
|---|---|---|
| THEORY.md invariant | 1.0 | Trunk — constrains everything, rarely wrong |
| ARCHITECTURE.md contract | 0.95 | Defines what a module owns |
| ADR | 0.9 | Settled decision, forever-localized |
| Code (structured handler) | 0.85 | Always current for what IS; says nothing about why |
| CONTEXT.md term | 0.8 | Canonical vocabulary |
| Reference doc | 0.8 | Authored understanding, months shelf-life |
| Spec / slice | 0.5 | Weeks shelf-life |
| README, handoff, ephemeral | 0.2 | Disposable context |
| **Unmatched prose (catch-all)** | **0.3** | Unknown source — lean low |

The catch-all leans **low (0.3)** deliberately. The motivating failure (the HANDOFF.md
incident) was *over*-trusting an ephemeral doc, so an unrecognized document is far more
likely to be scratch/notes than a missed THEORY.md. Better to under-trust an unknown
source and let a human promote it explicitly than to silently over-trust it. Code is
matched by extension, so the catch-all only ever applies to prose.

The mapping from source path → tier is a function in the ingester, derived from filename
patterns and directory position. The table is a **hardcoded internal default** (PoSD
Ch. 8 — the kernel knows the right tiers better than the caller does); it is *not* a
required config. Resolution precedence for every scoring knob is
**hardcoded default → `.context-kernel/config.toml` `[ingester.scoring]` → `CK_SCORING_*`
environment variable** (highest wins). The env layer exists so eval-driven tuning can
sweep knobs per run without editing files — see EVALS.md.

### Axis 2: ~~Recency~~ → **superseded by [ADR-0020](./0020-staleness-as-structural-drift.md)**

> **This axis is replaced.** The original model here was *recency* — time-decay of a
> source's last-modified date. ADR-0020 rejects it: code is functionally timeless, so trust
> erodes from **change**, not the passage of time. The temporal axis is now **drift** — the
> git-measured magnitude of change to a node's graph neighbourhood since the node itself
> last changed, carried on the edge and directional (referent → claimant). See ADR-0020 for
> the full model. The composite below uses `(1 − drift)` in place of the old `recency`.

### Axis 3: Centrality (static, from graph topology)

How many other entities structurally depend on this one. Computed as **distinct-source
in-degree** over the dependency-bearing edge kinds — structural `implements` and `inherits`
plus semantic `realizes` and `governed-by` (edge families per ADR-0021) — counting the
number of *distinct source documents* that contribute an in-edge to a node, not the raw
edge multiplicity. Normalized to [0,1] by the graph's maximum. The weak / historical kinds
(`motivates`, `addresses`, `supersedes`) and `imports` (ubiquitous, pure noise) are excluded.

The distinct-source rule is a deliberate defense against **lexicon inflation**: the doc
extractor mints a `realizes` edge every time a chunk name-drops a code identifier, so
a single chatty or stale document could otherwise manufacture centrality by repetition.
Counting distinct sources caps any one document's contribution at 1; ten *different*
documents depending on a node is genuine centrality.

Centrality is **never confidence-weighted** — it stays a raw structural signal, stored
separately from confidence. A node can be highly central yet untrustworthy (a stale doc
whose terms saturate the repo lexicon); that combination must remain *visible* so the
health rollup (issue #8) can flag "structurally load-bearing **and** untrustworthy."
Folding centrality into confidence, or discounting central nodes by their trust, would
erase exactly the case worth surfacing.

`KnowledgeStore` protocol, `Entity` type, and THEORY.md invariants rank highest because
many *distinct* modules reference them. A private helper mentioned once ranks lowest.

### Axis 4: Structural proximity (dynamic, per-query)

How close this entity is to the query's seed entities in the graph, weighted by edge type. This is the only axis computed at query time, but from pre-built graph structure (adjacency lists + relationship types). Not an LLM call.

Edge weights by relationship kind (families per ADR-0021). The same weight serves both
proximity propagation here *and* drift aggregation (ADR-0020) — one decision, reused.

| Kind | Family | Weight | Propagation |
|---|---|---|---|
| `governed-by` | semantic | 0.95 | Strong transitive propagation |
| `implements` | structural | 0.9 | Literal code dependency (class→interface) |
| `inherits` | structural | 0.9 | Literal code dependency (subclass→base) |
| `realizes` | semantic | 0.9 | Code realizes a decision/invariant |
| `supersedes` | semantic | 0.85 | Historical context |
| `addresses` | semantic | 0.7 | Decision resolves question |
| `motivates` | semantic | 0.5 | Causal but indirect, decays fast |
| `imports` | structural | 0.3 | Ubiquitous — kept but starved so it doesn't flood |

Weight is a **static function of kind only** — not kind × source reliability. Source
reliability is already captured by confidence (`authority × (1 − drift)`); folding it into
edge weight would double-count the same signal. Traversal direction matters: upstream
dependencies (outgoing `implements`/`inherits`/`realizes`/`governed-by`) are weighted higher
when working IN a scope; downstream consumers are weighted higher when assessing impact of a change.

**Query-time mechanics.** A free-text query has no seed entities, so the **top-3 results by
similarity become the seeds**. Each remaining candidate is then boosted by its 1-hop graph
adjacency to those seeds:

```
proximity(c) = 1 + max over seeds s of edge_weight(s, c)   if c is a 1-hop neighbour of a seed
             = 1                                           otherwise
```

Proximity is a **boost (≥ 1), never a gate**: an unconnected but highly-similar result keeps
`proximity = 1` and is never zeroed — it survives on similarity × confidence alone. (One hop
only, matching drift; 2-hop neighbourhoods dilute the signal.) **Centrality does not enter
the find score by default** (`CK_SCORING_CENTRALITY_IN_FIND=0`) — a query wants *relevant*
results, not merely *central* ones; the knob exists only so an eval can test a centrality prior.

### Composite score

For `summarize_scope()`:
```
entity_weight = authority × (1 − drift) × (1 + centrality)
              = confidence × (1 + centrality)
```
Entities sorted by weight before being sent to the LLM. The prompt instructs the LLM to emphasize high-weight entities.

> **Refinement (boost, not gate).** The original form multiplied by `centrality`
> directly. Real-data ingest (FEAT01, 190 code entities) showed that pure-code scopes
> give almost every entity centrality 0 — only `inherits` bears centrality among code,
> while `realizes`/`governed-by` arrive with the doc pass — so `× centrality` collapsed
> ~99% of code entities to a 0 tie and erased the confidence ordering entirely. Centrality
> is therefore a **boost (`1 + centrality`), never a gate**, exactly as proximity is in
> the find score: confidence is the ordering backbone, central entities rise above it.

For `find`:
```
score = embedding_similarity × confidence × proximity
      = embedding_similarity × (authority × (1 − drift)) × (1 + max-edge-weight-to-a-seed)
```
Results ranked by composite score, not embedding similarity alone. `proximity` is the
boost defined under Axis 4 (≥ 1, never a gate); `drift` is the edge-aggregated node drift of
ADR-0020; `confidence = authority × (1 − drift)`.

### Schema changes

`Entity` gains: `source_tier: float`, `centrality: float`, `confidence: float` (the
pre-computed `authority × (1 − drift)`). No timestamp is stored — ADR-0020 removed the time
axis, so the earlier `source_mtime` field is dropped.

`Relationship` gains: `weight: float` (from the kind mapping above) and `drift: float`
(ADR-0020 — the edge's directional staleness, loaded on the claimant end).

Both are additive — no breaking changes to existing interfaces.

## Consequences

- `summarize_scope()` produces summaries that reflect current code state over stale doc claims
- `find` returns results ranked by reliability and structural relevance, not just semantic similarity
- High-centrality entities (protocols, invariants, core types) survive hierarchical compression
- Stale docs naturally fade from influence without manual cleanup
- Greenfield projects work: code entities start at confidence 0.85, doc entities enter later with higher authority as docs are authored
- The HANDOFF.md class of failure is mitigated (low authority × high drift = near-zero confidence)
- Partial overlap with GitHub issue #4 (doc-vs-code contradiction detection): a code entity at 0.85 contradicting a doc entity at 0.04 is a detectable signal

## Related

- [ADR-0020](./0020-staleness-as-structural-drift.md) — replaces Axis 2 (recency) with drift: staleness is git-measured structural change, not elapsed time
- [ADR-0019](./0019-confidence-materialized-relevance-at-query.md) — the compute-time boundary (confidence materialized at ingest, relevance composed at query)
- [ADR-0016](./0016-contextual-entity-extraction.md) — addresses the upstream cause (extractor lacks context during extraction)
- [THEORY.md open question](../../THEORY.md) — "Should entities carry a confidence score across spatial, temporal, and authority axes?"
- GitHub issue #4 — doc-vs-code contradiction detection
