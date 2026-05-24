# Cross-scope relationships derived from LightRAG's native graph via source_id traversal

**Status:** accepted
**Date:** 2026-05-24

Context Kernel's value over flat vector RAG is **cross-scope orientation** — when an agent reads `AGENTS.md` for `src/auth/`, the summary names what auth depends on elsewhere in the portfolio and what depends on auth. Without this, the kernel is a glorified `tree && cat *.md`. The mechanism for surfacing these cross-scope relationships is thesis-load-bearing — per [THEORY.md](../../THEORY.md) open question 4.

We adopt a two-stage mechanism:

**Primary (A): LightRAG's native cross-document entity merging.** LightRAG processes every source-file chunk in one ingest pass and runs an LLM extraction prompt per chunk; entities are merged across chunks by surface-name normalization. If the same logical entity appears in chunks from `src/billing/customer.py` and `src/auth/session.py`, LightRAG merges them into a single graph entity whose `source_id` set references both chunks. Relationships emerge automatically when the LLM extracts edges from a chunk that mentions entities living in another scope.

**Bridge (B): Source-ID traversal at the end of ingest.** After LightRAG completes, the Ingester walks every relationship in the graph. For each `e1 → e2`, the source files of `e1`'s chunks and `e2`'s chunks are mapped to scopes (chunk → file → directory). A relationship is recorded as **cross-scope to scope X** if one endpoint has a source-chunk in X and the other endpoint has any source-chunk not in X. This set is what the per-scope synthesis prompt (per [ADR-0007](./0007-per-scope-summaries-at-ingest.md)) receives as the "Relationships crossing to other scopes" input.

When `PythonHandler` and `TSHandler` land in PLAN.md S3/S4, their AST-extracted import edges become first-class `Relationship` records the Ingester upserts directly — additive over A+B, not a replacement. Mechanism (D) catches structural dependencies (`from billing import Customer`) that the LLM may miss; A+B catches semantic dependencies (the auth flow calls into billing's session validator via an interface) that the AST cannot see.

## Considered options

- **Active cross-scope synthesis pass.** After ingest, for each scope, ask the LLM "what entities in other scopes are conceptually related to this scope's entities?" Rejected because: (1) O(scopes²) LLM calls is expensive; (2) it is a **confabulation engine** — the model will invent plausible-sounding links the code does not contain, corrupting the graph in a way that is hard to detect downstream; (3) if a real cross-scope relationship exists in the code, primary mechanism (A) is supposed to have already found it. Actively synthesizing means we do not trust A — and if we do not trust A, the right answer is to fix A (different LLM, different prompt, different backend), not to layer a confabulation pass on top.
- **AST-only import-graph relationships, skip A.** Rejected because it only works for code, does not capture semantic dependencies (interface-mediated calls, stringly-typed lookups), and provides nothing for markdown, ADRs, or PDFs — which is the majority of the portfolio's *orientation content*. AST is additive (mechanism D), not a replacement.
- **A different graph backend entirely** (GraphRAG, Graphiti, custom). Rejected during [ADR-0004](./0004-switch-to-lightrag.md); cross-scope linkage is LightRAG's stated selling point and we should test it before discarding it. Re-litigated only if S0 returns a hard fail.

## Consequences

- **Mechanism quality is bounded by LightRAG's entity-merging heuristics.** If the LLM extracts `Customer` in `billing/` and `customer entity` in `auth/`, LightRAG's surface-name normalization may or may not merge them. Inconsistent naming across files → fragmented graph → cross-scope edges invisible to B. This is the **single biggest thesis risk** and is what [THEORY.md](../../THEORY.md) open question 4 tracks.
- **S0 must measure cross-scope relationship density directly.** Per [HANDOFF.md](../../HANDOFF.md) S0 exit criterion: count of relationships whose endpoints span ≥2 scopes, as a fraction of total relationships. Heuristic thresholds — ≥15% = go; <5% = stop and re-grill [ADR-0004](./0004-switch-to-lightrag.md); 5-15% = limp forward with caveat and watch closely.
- **B is deterministic on top of A's output.** No extra LLM calls; idempotent; cheap. The Ingester computes the per-scope cross-edge set as the last step of the second pass (per [ADR-0007](./0007-per-scope-summaries-at-ingest.md)) before issuing the synthesis call for that scope.
- **No effect on `graph_commit` semantics.** Per [ADR-0008](./0008-content-derived-graph-commit.md), `graph_commit` is derived from source content, not from cross-scope linkage. Re-ingest under a different LLM that produces denser cross-scope merging yields a different *graph content* under the same `graph_commit`. Operator-driven `rm -rf .context-kernel/` is the migration story.

## When this should be revisited

- S0 measurement returns <5% cross-scope density on a representative corpus — re-grill [ADR-0004](./0004-switch-to-lightrag.md). The system's central differentiator does not work on the chosen backend.
- AST-based handlers (D) land in S3/S4 and prove to be much denser than A+B — would suggest A is weak and the LLM-extracted relationships are largely redundant with structural imports, prompting either a different extraction prompt or a different graph backend.
- A use case emerges where the LLM consistently extracts the same entity under two surface names (`Customer` vs `CustomerEntity`) across scopes — would justify the deferred `EntityResolver` (per [ARCHITECTURE.md](../../ARCHITECTURE.md) §6) coming forward in priority.
