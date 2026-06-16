# ADR-0032: Tenets — authored design rules distributed through the ontology

**Date:** 2026-06-09
**Status:** Proposed (extends ADR-0024 / ADR-0025)

## Context

The kernel's emerging third job (REVIEW-FABLE.md Part II) is normative: guide how code should
be structured, not only describe what it is. The cheapest, best-evidenced mechanism is
**distribution, not computation**: the kernel is already a guaranteed-fresh distribution
system for context, and the operator's design rules are exactly the content class measured to
help agents.

Evidence (docs/research/2026-06-09-design-signals-normative-layer.md §5–6, §8):

- Human-authored, specific, non-redundant context is the only context-file class with a
  measured *positive* effect on agent success (+4 pts), while generated/redundant content
  measurably hurts (−0.5 to −2 pts, +20% cost) — ETH AGENTS.md study, arXiv:2602.11988.
- Agents **over-obey**: unnecessary specifications made tasks harder, and LLM reviewers
  systematically overcorrect (arXiv:2603.00539). Generic style edicts ("prefer deep modules")
  are a churn generator, not guidance.
- The validated shape for rules-vs-reality is Murphy & Notkin's reflexion model (FSE 1995):
  a small hand-authored model diffed against extracted structure, divergences reported. Its
  historical weakness — the authored model going stale — is the kernel's home specialty.
- Fitness-function practice (ArchUnit, import-linter) works but fails by over-prescription
  ("every minor decision enforced → red tape").

## Decision

1. **Tenets are ontology data.** The base declares the schema; overlays carry instances
   (ADR-0025 composition: portfolio tenets + per-project tenets):

   ```yaml
   tenets:
     git-io-single-module:
       text: All git I/O goes through context_kernel/change_detection.py — never call git elsewhere.
       scope: project              # or portfolio
       applies: "context_kernel/**"   # glob; renders only in matching scopes
       check:                      # optional — phase 2, declared now
         kind: only-importer
         subject: "context_kernel/change_detection.py"
         forbidden_elsewhere: ["subprocess.*git", "import git"]
   ```

2. **Authoring rules are part of the schema, enforced socially and structurally:** a tenet
   must be **scope-specific and falsifiable** — a claim about this codebase that the graph
   could in principle check ("X is the only writer to Y"), never an aesthetic ("write deep
   modules"). The schema documents this; review-gate discipline (ADR-0034's release
   convention) enforces it.
3. **Rendered with a hard budget.** A `## Tenets` section near the top of matching scopes'
   AGENTS.md (after pinned blocks, before prose — position-effect ordering per ADR-0028),
   capped at `materializer.max_tenet_lines` (default 5). The cap is enforced, not trusted:
   over-budget tenet sets render the highest-priority lines and warn loudly.
4. **Tenets participate in the composed-ontology hash** (mechanism already specified by
   ADR-0024 §5 / ADR-0025 §5): editing a tenet re-materializes exactly the matching scopes.
5. **Phase 2 — conformance checks (declared, not yet wired).** A small ingest pass evaluates
   declared `check:` rules against structural edges — initial kinds `only-importer`,
   `no-import-from`, `single-writer` — and emits divergences as findings into the
   design-signals view (ADR-0036) with the violating edge and `source_line` as receipt. This
   is the reflexion model with the staleness problem solved by the pre-commit loop: the
   authored model and the extracted model are re-diffed at every commit. Checks never fail
   the build in v1 — they flag (the kernel's posture: surface, never block; the operator owns
   judgment).

## Considered options

- **Hand-written tenets in pinned blocks per scope.** Status quo escape hatch; rejected as the
  mechanism because pinned content doesn't compose (no portfolio-wide tenets, no overlay
  inheritance), isn't budget-enforced, and can't carry machine-checkable rules.
- **Computed design signals first, tenets later.** Rejected: distribution is cheaper, has
  positive measured evidence today, and carries zero inference risk; signals (ADR-0036) need
  the eval harness first.
- **Enforcing checks (block the commit).** Rejected for v1: over-prescription is the
  documented failure mode of fitness functions, and a false block is worse than a false flag.
  Revisit per-tenet once precision is measured.

## Consequences

- The normative layer ships in its safest form first: the operator's rules, verbatim,
  fresh, scoped, budgeted.
- `ontology.yaml` grows a fourth layer (vocabulary, policy, projection, **tenets**) — locality
  semantics identical to concepts (ADR-0025 table extends by one row).
- The materializer renders one new section; the composed-hash plumbing already exists.
- Phase 2 creates the kernel's first conformance machinery — kept deliberately tiny (three
  check kinds) until ADR-0036's effective-FP loop can measure it.

## When this should be revisited

- Tenet counts creep past the budget portfolio-wide → the over-prescription failure mode is
  arriving; prune at the release gate, don't raise the cap reflexively.
- The ETH-style measurement (via ADR-0029) shows tenet sections not earning their tokens →
  cut to portfolio-root-only rendering.
- Check kinds proliferate → stop and design a proper rule language rather than accreting
  ad-hoc kinds (that is a different, bigger decision).

## Related

- [ADR-0024](./0024-ontology-as-type-system.md) / [ADR-0025](./0025-ontology-composition-per-project-overlays.md) — the artifact and composition this extends.
- [ADR-0028](./0028-edge-derived-agents-md-sections.md) — section ordering and budgets.
- [ADR-0036](./0036-design-signals-view.md) — where phase-2 divergences land.
- [ADR-0034](./0034-ontology-evolution-guardrails.md) — the release-gate convention.
- docs/research/2026-06-09-design-signals-normative-layer.md §5–6, §8.1–3.
