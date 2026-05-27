# ADR-0013: Markdown entity taxonomy for documentation ingestion

**Date:** 2026-05-26
**Status:** Accepted

## Context

Context Kernel's Ingester extracts structured entities from code (Python via AST, TS/JS via tree-sitter) but treats markdown files as opaque text — sliding-window chunking with no structural awareness. The Summarizer protocol existed as an interface with no concrete implementation, so markdown files produced zero entities during ingestion.

Technical documentation (ADRs, specs, architecture docs, theory docs) carries the "why" that code can't express. The graph needs to link that reasoning back to the code entities it explains. This requires: (1) heading-aware chunking that preserves document structure, and (2) an entity taxonomy that an LLM can reliably extract from prose.

## Decision

### Entity kinds (8)

| Kind | Captures |
|---|---|
| `decision` | A resolved choice with rationale. Non-goals are decisions NOT to do something. |
| `constraint` | An externally imposed boundary. Not chosen — inherited. |
| `invariant` | A property the system must always maintain. Internally chosen. |
| `trade-off` | An explicit tension between competing qualities. |
| `risk` | An identified threat to success. |
| `workflow` | A sequenced process or pipeline. |
| `interface` | A contract boundary — API, protocol, schema. |
| `open-question` | An unresolved issue requiring future decision. |

### Relationship kinds (5)

| Kind | Semantics |
|---|---|
| `implements` | Code entity realizes a doc entity. |
| `governed-by` | Code/design constrained by a rule. |
| `motivates` | One entity is the reason another exists. |
| `supersedes` | One decision replaces another. |
| `addresses` | A decision resolves an open question. |

### Heading-aware chunking

The `MarkdownHandler` splits on heading markers (`#` through `######`) and prepends the heading ancestry path (e.g., `[heading: Invariants > Graph is source of truth]`) as context in each chunk. Oversized sections fall back to sentence/line-boundary splitting within the heading section.

## What was cut

- **Requirement** — in this project, requirements are either invariants or implicit in slice specs. Adding it as distinct from `constraint`/`invariant` would confuse the LLM.
- **Pattern** — referenced in docs but as attributes of decisions, not standalone navigable entities.
- **Measurement** — concrete data points (e.g., "94 tok/s") are attributes of `decision` or `risk` entities, not standalone nodes.
- **Non-goal (as separate kind)** — modeled as a `decision` with negative stance.

## Consequences

- The Summarizer protocol now returns `RawEntity`/`RawRelationship` (not `Entity`/`Relationship`), aligning with the handler protocol pattern where IDs are assigned by `_resolve_raw_entities`.
- `LLMSummarizer` is the concrete implementation, calling a local OpenAI-compatible endpoint.
- The taxonomy is deliberately a working hypothesis — 8 kinds is within the sweet spot where an LLM can reliably distinguish types. Expect refinement through dogfooding.

## Revisit when

- Dogfooding reveals the LLM consistently confuses two kinds (merge them) or misses a pattern (add a kind).
- A new document type (e.g., runbooks, postmortems) introduces entity patterns not covered by these 8.
- Extraction F1 measurement becomes available and shows the taxonomy is too coarse or too fine.
