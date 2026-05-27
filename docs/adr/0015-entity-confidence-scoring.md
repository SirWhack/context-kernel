# ADR-0015: Entity Confidence Scoring Across Altitude Axes

## Status

Accepted

## Context

The HANDOFF.md incident (2026-05-27) exposed a structural gap: the graph treats all entities as equally authoritative. An entity extracted from THEORY.md carries the same weight as one from a stale handoff note. When `summarize_scope()` builds an AGENTS.md summary, or `find` returns results, there is no signal to prefer current, authoritative, structurally central claims over stale, ephemeral, peripheral ones.

The thesis says Context Kernel composes context across altitudes. Today "altitude" means spatial position in the directory tree. But altitude is at least four axes, and confidence is the composite score across them.

## Decision

Entities and relationships gain a per-record confidence score computed at ingest time from four axes. The score is stored on the record (per ARCHITECTURE.md tenet 2: work belongs in materialization, not query time). Query-time operations (`find`, `summarize_scope()`) use the pre-computed score for weighting and ranking.

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

The mapping from source path → tier is a function in the ingester, derived from filename patterns and directory position. Configurable via `.context-kernel/config.toml` if projects need different tiers.

### Axis 2: Freshness (semi-static, from source modification time)

How recently the source was modified. Freshness interacts with authority non-linearly: high-authority sources decay slowly (THEORY.md unchanged for 6 months is stable, not stale), low-authority sources decay fast (a handoff note unchanged for a week is stale).

```
freshness = 1.0 - (days_since_modified / (shelf_life_days × authority))
clamped to [0.0, 1.0]
```

Code entities from structured handlers have freshness 1.0 by construction — the AST is re-parsed every ingest.

### Axis 3: Centrality (static, from graph topology)

How many other entities depend on this one. Computed from in-degree over `implements` and `governed-by` relationships. Entities that are targets of many structural relationships are more important — they should survive hierarchical compression into higher-altitude summaries.

`KnowledgeStore` protocol, `Entity` type, and THEORY.md invariants would rank highest because many modules reference them. A private helper function mentioned once ranks lowest.

### Axis 4: Structural proximity (dynamic, per-query)

How close this entity is to the query's seed entities in the graph, weighted by edge type. This is the only axis computed at query time, but from pre-built graph structure (adjacency lists + relationship types). Not an LLM call.

Edge weights by relationship kind:

| Kind | Weight | Propagation |
|---|---|---|
| `governed-by` | 0.95 | Strong transitive propagation |
| `implements` | 0.9 | Direct dependency |
| `supersedes` | 0.85 | Historical context |
| `addresses` | 0.7 | Decision resolves question |
| `motivates` | 0.5 | Causal but indirect, decays fast |

Traversal direction matters: upstream dependencies (outgoing `implements`, `governed-by`) are weighted higher when working IN a scope; downstream consumers are weighted higher when assessing impact of a change.

### Composite score

For `summarize_scope()`:
```
entity_weight = authority × freshness × centrality
```
Entities sorted by weight before being sent to the LLM. The prompt instructs the LLM to emphasize high-weight entities.

For `find`:
```
score = embedding_similarity × (authority × freshness) × structural_proximity_from_seeds
```
Results ranked by composite score, not embedding similarity alone.

### Schema changes

`Entity` gains: `source_path: str`, `source_tier: float`, `source_mtime: str`, `confidence: float` (the pre-computed `authority × freshness`).

`Relationship` gains: `weight: float` (from kind mapping, or computed at ingest from kind + source reliability).

Both are additive — no breaking changes to existing interfaces.

## Consequences

- `summarize_scope()` produces summaries that reflect current code state over stale doc claims
- `find` returns results ranked by reliability and structural relevance, not just semantic similarity
- High-centrality entities (protocols, invariants, core types) survive hierarchical compression
- Stale docs naturally fade from influence without manual cleanup
- Greenfield projects work: code entities start at confidence 0.85, doc entities enter later with higher authority as docs are authored
- The HANDOFF.md class of failure is mitigated (low authority × low freshness = near-zero confidence)
- Partial overlap with GitHub issue #4 (doc-vs-code contradiction detection): a code entity at 0.85 contradicting a doc entity at 0.04 is a detectable signal

## Related

- [ADR-0016](./0016-contextual-entity-extraction.md) — addresses the upstream cause (extractor lacks context during extraction)
- [THEORY.md open question](../../THEORY.md) — "Should entities carry a confidence score across spatial, temporal, and authority axes?"
- GitHub issue #4 — doc-vs-code contradiction detection
