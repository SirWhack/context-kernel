# ADR-0035: Manifest and contract handlers — external packages and deterministic cross-project edges

**Date:** 2026-06-09
**Status:** Proposed (relates to ADR-0026; respects THEORY non-goal 2)

## Context

Two measured gaps share one root — things the portfolio depends on that have no node:

1. **External libraries.** ADR-0026's audit: 11.4% of `imports` edges (198/1,735) landed on
   doc-prose nodes, dominated by external libraries (`anthropic`, `pydantic`) modeled only as
   `constraint` prose; its residual 28 conflated `calls` were the same class. ADR-0026 named
   "modeling third-party libraries as their own node kind" as the follow-up.
2. **Cross-project structure.** Portfolio concept hubs are today the *only* cross-repo bridge.
   Real portfolios carry deterministic cross-project structure the kernel drops: dependency
   manifests naming sibling projects, and API contracts binding a TS frontend to a Python
   backend. THEORY open question 1 asks whether cross-project insight needs entity merging;
   it cannot be answered while deterministic non-merging linkage is left unbuilt.

Evidence (docs/research/2026-06-09-ontology-and-entity-resolution.md §5): name-based
cross-language symbol matching has no research support, and inter-language dependencies are
empirically the buggiest edges (arXiv:2411.08388); industry converged on the **contract
artifact as the join point** — FastAPI → `openapi.json` → openapi-typescript, with
operationIds/schema names as the shared anchors.

## Decision

1. **New structural kind `external-package`** (closed family, parser-emitted, ADR-0024). One
   node per declared dependency; description carries the version spec and manifest source.
2. **`ManifestHandler` (StructuredHandler)** over `pyproject.toml` and `package.json`
   (dependencies + devDependencies): emits `external-package` entities and
   `module(project root) —depends-on→ package` edges.
3. **Edge-kind naming fix.** The YAML handler emits `depends_on` (underscore) where every
   other kind is hyphenated; normalize to **`depends-on`** in the base ontology. Re-ingest is
   the migration (ADR-0008).
4. **Resolver binding for externals.** In `_resolve_endpoint`'s precedence, an
   `imports`/`calls` endpoint that fails code resolution but exactly matches an
   `external-package` name binds there — closing ADR-0026's residual class deterministically
   instead of falling through to doc prose or dropping. Code precedence is unchanged: a real
   in-repo definition still wins over a package of the same name.
5. **Cross-project edges via the declared project list — no guessing.** A portfolio post-pass
   in `ingest_portfolio()`: a dependency whose normalized name matches a **project declared in
   the portfolio config** becomes `projectA —depends-on→ projectB` between root module nodes,
   flagged `cross_repo` (the export layer already carries the flag). Matching is exact against
   the config's project list — never fuzzy, never against arbitrary directory names.
6. **Materialized at the right altitude.** ADR-0028's sections render package dependencies at
   project scope and the project-dependency table at the portfolio root — the portfolio
   AGENTS.md can finally answer "what breaks downstream if I change X" deterministically.
7. **Phase 2 — `OpenAPIHandler` (declared, not yet wired).** `operation` and `schema`
   entities from `openapi.{json,yaml}`; `exposes` edge to the backend handler by **exact**
   operationId ↔ function-name match; `consumes` edge from frontend call sites where the
   generated-client import is structurally identifiable. Exact-match-or-drop throughout
   (ADR-0017's stance). GraphQL SDL / protobuf are the same pattern when a portfolio needs
   them.

## Considered options

- **Suppress doc-binding for structural edges instead** (ADR-0026's alternative). Partially
  adopted via (4): externals get a real node to bind to, which is strictly better than
  dropping — the edge survives *and* is truthful.
- **Name/embedding-based cross-language symbol linking.** Rejected — no research support,
  highest-risk namesake class, and the contract artifact exists precisely to make this
  unnecessary.
- **Cross-project entity merging.** Out of scope by THEORY non-goal 2 — this ADR is the
  experiment that tests whether the non-goal holds: if contract + manifest edges plus concept
  hubs answer the cross-project questions in the eval, merging stays deferred.

## Consequences

- `imports` conflation residue (11.4%) collapses toward zero; external dependencies become
  first-class, queryable, and renderable.
- The portfolio graph gains its first deterministic cross-repo edges with zero LLM cost and
  zero identity risk.
- New kinds in the base ontology: `external-package` (node), `exposes`/`consumes` (phase 2
  edges); `depends_on` → `depends-on` rename.
- Version-bump churn is bounded: the manifest is one small file; its entities re-derive in
  microseconds (no LLM in the path).

## When this should be revisited

- Monorepo-style path dependencies (`file:../sibling`) or aliased package names appear in a
  real manifest → extend matching rules explicitly, still against declared projects only.
- Phase 2's exact operationId match recovers too little on a real frontend/backend pair →
  consider route-string matching (decorator path ↔ client path) before anything fuzzy.
- A portfolio adds non-Python/TS projects → manifest support is per-ecosystem; add parsers as
  composition demands (same policy as language handlers, PLAN backlog).

## Related

- [ADR-0026](./0026-methods-as-first-class-nodes.md) — the residual conflation this closes; the named follow-up.
- [ADR-0017](./0017-entity-resolution-identity-merging.md) — exact-match-or-drop resolution stance.
- [ADR-0028](./0028-edge-derived-agents-md-sections.md) — where the edges become visible.
- THEORY.md non-goal 2 / open question 1 — the deferral this ADR stress-tests without violating.
- docs/research/2026-06-09-ontology-and-entity-resolution.md §5.
