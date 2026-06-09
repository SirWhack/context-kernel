# ADR-0028: Edge-derived deterministic sections in materialized AGENTS.md

**Date:** 2026-06-09
**Status:** Proposed

## Context

The graph's edges do almost none of their work where agents read. ADR-0023 diagnosed the
problem at query time ("the structural and semantic edges we pay to extract do most of their
work at ingest and almost none at retrieval"); the same is true at materialize time, which
matters more because files are the primary interface (ARCHITECTURE settled tradeoff 2). The
materializer renders `get_summary(scope)` prose, and that summary is built by handing ranked
entity *descriptions* to the LLM — `summarize_scope` receives no relationships. Cross-scope
dependencies, `realizes`/`governed-by` links into ADRs, and concept hubs — the
thesis-load-bearing structure — never deterministically appear in AGENTS.md.

The research base (docs/research/2026-06-09-hierarchical-materialization-and-importance-ranking.md §3):

- Graph serialization format moves LLM comprehension by up to 17.5 points; subject-grouped
  structured formats win, RDF-style triple dumps lose (KG-LLM-Bench, arXiv:2504.07087;
  "Talk like a Graph", arXiv:2310.04560).
- Position effects are real: mid-file content can fall below the closed-book baseline
  (Lost in the Middle, arXiv:2307.03172).
- Generated prose that restates what code already shows is *negative* value for agents
  (−0.5 to −2 pts success, +20% cost), while specific non-redundant facts help
  (ETH AGENTS.md study, arXiv:2602.11988). Deterministic edge facts with file-path pointers
  are exactly the non-redundant class.

## Decision

1. **New pure renderers** in `context_kernel/materializer/sections.py`, fed from existing
   `KnowledgeStore` reads (`list_entities_by_scope()`, `list_relationships()`); no LLM, no new
   store methods:
   - **Depends on** — outgoing structural edges (`imports`, `calls`, `inherits`) whose target
     scope differs from the source scope, grouped by target scope, naming the specific
     entities used and their file paths.
   - **Used by** — the reverse direction.
   - **Governing decisions** — semantic edges (`realizes`, `governed-by`, `addresses`) from
     this scope's code entities to nodes whose source tier is ADR / THEORY / ARCHITECTURE,
     rendered as links with a one-line edge description.
   - **Concepts** — concept hubs with `implemented-by`/`manifested-by` anchors in this scope,
     each with its CodeSpan receipt (`file:line — primitive`, line derived at render,
     ADR-0018).
2. **Selection and caps.** Entries rank by `edge_weight × target.confidence`
   (× `(1 + importance)` once ADR-0031 lands); per-section cap
   `materializer.max_section_entries` (default 8); empty sections are omitted.
3. **Section order** follows the position-effect evidence: freshness header → pinned blocks →
   summary prose → Governing decisions → Depends on / Used by → Concepts → reference/gap
   footer. Load-bearing content never sits mid-file by construction.
4. **Pointers, not content.** Every entry terminates in a relative file path. The sections
   orient and point; the agent's own Read/Grep delivers depth (progressive disclosure).
5. **Token budgets become enforced.** Because the CLAUDE.md bridge auto-loads every AGENTS.md
   on the walked path, budgets are additive along the path. The materializer computes
   per-file and cumulative root→leaf token counts; `ck check --budget` warns when a file
   exceeds `materializer.max_file_tokens` (default 3k) or a path exceeds
   `materializer.max_path_tokens` (default 8k). Sections count against the budget; when tight,
   prose compresses before sections shrink (deterministic facts outrank generated prose per
   the ETH evidence).
6. **Determinism contract.** Section content is byte-identical across repeated
   materializations of the same `graph_commit` — same idempotency the rest of the
   materializer already guarantees.

## Considered options

- **Pass relationships into the `summarize_scope` prompt and let the LLM weave them into
  prose.** Rejected as the primary mechanism: it converts deterministic facts into
  paraphrase (the content class measured to hurt), is non-reproducible, and hides provenance.
  May still be done *additionally* for narrative quality.
- **A separate `views/dependencies.md` cross-cutting view instead of per-scope sections.**
  Rejected: views are not auto-loaded; the value is precisely that the agent sees its current
  scope's dependencies without asking.
- **Render full triple lists (source, kind, target).** Rejected on the serialization
  evidence; subject-grouped lists win.

## Consequences

- AGENTS.md becomes the visible differentiator over grep: an agent opening a scope sees what
  it depends on, what depends on it, and why it is shaped this way — without a single query.
- The materializer gains its first direct graph-edge reads; it remains a pure function of
  `(scope, graph_commit, view_spec)`.
- File sizes grow bounded by the caps; the budget check makes the growth observable.
- ADR-0023's query-time expansion becomes partially redundant for the within-scope case —
  acceptable; the eval (ADR-0029) measures both.

## When this should be revisited

- The budget check shows deep paths chronically exceeding `max_path_tokens` → revisit
  per-altitude section policies (e.g., Concepts only at project altitude).
- The eval shows agents ignoring the sections → re-grill the format against the
  KG-LLM-Bench alternatives before abandoning.

## Related

- [ADR-0023](./0023-query-time-neighbor-expansion.md) — the query-time half of "make the graph visible."
- [ADR-0018](./0018-evidence-anchored-concept-edges.md) — CodeSpan receipts rendered here.
- [ADR-0015](./0015-entity-confidence-scoring.md) — edge weights and confidence used for selection.
- [ADR-0002](./0002-materialize-agents-md-with-claude-code-bridge.md) — the bridge whose auto-load makes path budgets additive.
- docs/research/2026-06-09-hierarchical-materialization-and-importance-ranking.md §3.
