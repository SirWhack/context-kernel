# ADR-0021: Structural vs semantic edge families; rename semantic `implements` → `realizes`

## Status

Accepted. Refines ADR-0013 (entity/relationship taxonomy); relates to ADR-0011 (two handler
protocols), ADR-0015 (edge weights / centrality), ADR-0020 (drift).

## Context

Graph edges come from two producers with fundamentally different epistemics:

- **Structured handlers** (Python `ast`, TypeScript tree-sitter) emit `imports`, `inherits`,
  `implements` — deterministic, literal facts read straight off the syntax tree.
- **The LLM extractor** emits `implements`, `governed-by`, `motivates`, `supersedes`,
  `addresses` — *inferred* relationships read out of prose.

`implements` straddles both: the literal `class Foo implements interface Bar` (a parsed
fact) and the inferred "code entity realizes a decision" (e.g. `LLMSummarizer implements
ADR-0004`). Same label, one a fact and one an inference. That overload is a conflation
hazard on two ends: the extractor LLM should never reason over a vocabulary that overlaps
code keywords (it invites mislabelling literal-import-like prose as a semantic edge), and a
reading agent can't tell whether an `implements` edge is a deterministic fact or a model's
guess.

## Decision

1. **Two edge families.**
   - **Structural** — parser-derived, literal, deterministic: `imports`, `inherits`,
     `implements`. The highest-confidence edges in the graph.
   - **Semantic** — LLM-inferred relationships: `governed-by`, `motivates`, `supersedes`,
     `addresses`, `realizes`.

   A consumer (or the model itself) that knows an edge's family knows whether it is a
   **fact** or an **inference**.

2. **Rename the semantic `implements` → `realizes`** ("code *realizes* a decision /
   invariant"). The extractor's relationship vocabulary becomes **pure relationship verbs
   with zero code-keyword overlap** — nothing to conflate against code nomenclature — and
   `implements` now means *only* the literal structural sense.

3. **Keep the structural names literal** (`imports` / `inherits` / `implements`). They are
   accurate, deterministic, and the most trustworthy edges in the graph; abstracting them to
   vaguer verbs would discard precision a reading agent can rely on. The fix for conflation
   is the family distinction and de-overloading `implements`, *not* renaming facts.

## Consequences

- The summarizer prompt and `RELATIONSHIP_KINDS` change `implements` → `realizes` for the
  semantic kind. A re-ingest remaps stored edges (per ADR-0008 migration).
- The edge-weight table and the centrality kind-set (ADR-0015) adopt the split vocabulary:
  centrality counts structural `implements` / `inherits` plus semantic `realizes` /
  `governed-by`; weights gain `inherits` and `imports`, and the semantic weight moves from
  `implements` to `realizes`.
- Drift (ADR-0020) operates on semantic doc↔code edges with code as the reference frame;
  the rename changes only the label it reads, not the mechanics.
- The confidence axes are otherwise unchanged.

## Related

- [ADR-0013](./0013-markdown-entity-taxonomy.md) — entity/relationship taxonomy this refines.
- [ADR-0011](./0011-two-handler-protocols.md) — the structured vs chunk handler split that
  produces the two edge families.
- [ADR-0015](./0015-entity-confidence-scoring.md) — edge weights and centrality kind-sets.
- [ADR-0020](./0020-staleness-as-structural-drift.md) — drift over semantic doc↔code edges.
