# ADR-0022: Repo-local role assignment, global role valuation

## Status

Accepted. Refines the authority axis of [ADR-0015](./0015-entity-confidence-scoring.md);
materialization boundary per [ADR-0019](./0019-confidence-materialized-relevance-at-query.md).

## Context

The first foreign-corpus eval (`full-stack-fastapi-template`, 2026-05-30 — see EVALS.md)
exposed a calibration gap. `classify_source` keys authority off model-time's *own*
document taxonomy (`THEORY.md`, `ARCHITECTURE.md`, the ADR filename pattern, `CONTEXT.md`).
On a third-party repo that recognizes none of those, the graded authority ladder collapsed
to **two values** — code at 0.85, all prose at the 0.2–0.3 floor:

- `README.md` — the most authoritative human-authored doc in that repo — was pinned to the
  `EPHEMERAL` floor (0.2), because *our* taxonomy treats README as disposable (model-time
  has `THEORY.md` as its trunk).
- `deployment.md` / `development.md` (573 lines of real operational reference) fell to the
  0.30 prose catch-all, below code.

Authority — the one axis that produced usable signal on that corpus — was therefore
meaningless on any repo not authored in the kernel's image. That is the onboarding ("init")
gap: the kernel assumed a documentation discipline almost no real repo practices.

The naive fix — let each repo declare its own authority *numbers* — breaks a load-bearing
property. The portfolio ingests every project into **one shared graph**, and `confidence`
(= authority × …) is the ranking signal *across that graph*: `find` and `summarize_scope`
compare a doc from project A against a doc from project B by confidence. Authority must stay
**one comparable ruler**. If repo A calls its README 0.9 and repo B calls its 0.5, A's docs
systematically outrank B's for no reason but scale generosity.

## Decision

Split the file→authority mapping into two layers along the local/global seam:

| Layer | Question | Owner | Where | Scope |
|---|---|---|---|---|
| **Role assignment** | what *is* this file in *this* repo? | a human | `[ingester.scoring.roles]` (per-repo) | **local** |
| **Role valuation** | what is a role *worth*? | the kernel | `AUTHORITY_TIERS` / portfolio config | **global — one ruler** |

`[ingester.scoring.roles]` is a per-repo map of **glob → role name**. `classify_source`
consults it first — most-specific glob wins (fewest wildcards, then longest literal) — and
falls back to the built-in filename heuristic for anything undeclared. The role *name* keys
the global `AUTHORITY_TIERS` table, so a role means the same authority in every project.

Two roles are added to the **global** vocabulary so most repos need only declare
assignments, not also define numbers:

- `OVERVIEW = 0.85` — a repo's top-level orientation doc (trunk README), **capped at `CODE`**.
- `OPS = 0.6` — operational reference (deploy / run / configure); above `SPEC` (weeks
  shelf-life), below `REFERENCE` (authored architectural understanding).

Guard rails:
- A role naming a tier that doesn't exist (after `authority_tiers` overrides) is a **loud
  config error**, not a silent fall-through to the catch-all.
- **Code is matched by extension and never reclassified by a prose glob** — a `*.md` role
  cannot touch `.py`/`.ts`.

### Why `OVERVIEW` is capped *at* code, not above it

The eval quantified the doc-vs-code interaction in `find`. For a natural-language query, a
README chunk out-*similars* a code chunk (it describes the feature in the query's own
words: README sim 0.75 vs `security.py` 0.61 for "JWT verification"). The original
code-first results were an **artifact of flooring the README at 0.2** — a bug masquerading
as correctness, suppressing a genuinely relevant doc. Raising authority to make code win
again would require dropping `OVERVIEW` to ≈ 0.68 (below `REFERENCE`), making "trunk" a lie.

So authority is **not** the lever for doc-vs-code intent — it is the lever for *trust*
(stale vs current). `OVERVIEW = CODE = 0.85` makes `find` treat README and code neutrally,
letting similarity decide and producing a **concept-then-implementation packet**;
`summarize_scope` still floats the README up via its centrality at equal authority. `find`
returns a *mixed packet* (the relevant code entity is reliably in the top-k regardless of
which leads), so ordering is orientation, not single-answer retrieval — a kind-aware
"prefer code" reranker was considered and rejected as YAGNI (it would break the conceptual /
ops / how-to queries where doc-first is correct).

### Why declare, not auto-discover

Inferring tiers from repo structure (doc position, inbound-link density, content-role
classification) was considered. Rejected for v1: the oracle for "is this inferred tier
right?" is itself fuzzy and not deterministically eval-able (EVALS.md principle 2). The
cross-project requirement forces the valuation to be global; only a human reliably knows an
arbitrary repo's doc roles, so the assignment is local and explicit. Discovery can later
*propose* an editable assignment, but the human-confirmed declaration stays the source of
truth.

## Consequences

- A foreign repo onboards by declaring ~6 lines of role assignments; **code is automatic**.
- The graded ladder is restored on foreign corpora. On the eval corpus: mean confidence
  0.68 → 0.81, README 0.20 → 0.85, central-but-low-trust ops hubs 0.30 → 0.60 (the
  central-AND-untrustworthy signal for the #8 health rollup sharpens rather than vanishes).
- **model-time's own behavior is unchanged**: the heuristic still floors its README at
  `EPHEMERAL` (its trunk is `THEORY.md`); roles are opt-in, empty by default.
- Because authority is materialized at ingest (ADR-0019), a role change requires a
  **re-ingest** to take effect.
- `ck init` scaffolding a starter `roles` block is a natural follow-on (not in this ADR).
- A per-project authority *multiplier* (flagship product vs throwaway spike) is a possible
  future knob; the role/number split is the load-bearing decision it would sit on top of.

## Related

- [ADR-0015](./0015-entity-confidence-scoring.md) — the authority axis this refines
- [ADR-0019](./0019-confidence-materialized-relevance-at-query.md) — materialized-at-ingest (why roles need a re-ingest)
- EVALS.md — the first foreign-corpus baseline that motivated this, and the regression anchor
