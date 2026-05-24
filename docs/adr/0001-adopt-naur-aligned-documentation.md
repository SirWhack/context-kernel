# Adopt Naur-aligned documentation: THEORY.md, CONTEXT.md, ADRs

**Status:** accepted
**Date:** 2026-05-23

The project root contains three documents — `THEORY.md` (thesis, invariants, non-goals, open questions), `CONTEXT.md` (glossary, relationships, flagged ambiguities), `CLAUDE.md` (agent operating rules) — plus an ADR ledger under `docs/adr/`. The split is informed by Peter Naur's *Programming as Theory Building* (1985) and Matt Pocock's `grill-with-docs` convention.

The argument: in agentic engineering, the engineer's hands no longer pass over every line of code. Naur's tacit theory-formation loop — the one that gets built incidentally through the act of typing — is broken. The theory must be made explicit through documentation rituals, or it does not exist. Vibe coding is the failure mode where no theory was ever built. These documents are the scaffolding that forces theory to exist.

Each document has a different altitude and a different shelf-life:

| Doc | Altitude | Holds | Shelf-life |
|---|---|---|---|
| `THEORY.md` | Trunk | Thesis, invariants, non-goals, open questions, shape | Years |
| `CONTEXT.md` | Language | Glossary, relationships, flagged ambiguities | Months |
| `docs/adr/` | Branches | Decisions + why, dated and local | Forever-localized |
| Specs / plans / issues | Leaves | What we're building right now | Weeks / days |

No overlap. `THEORY.md` *names* concepts but defines them in `CONTEXT.md`. `THEORY.md` *states* invariants and non-goals; ADRs *record the decisions* that produced them. `THEORY.md` *opens* questions; ADRs close them.

## Considered options

- **Agent-rules file alone (`CLAUDE.md` / `AGENTS.md`).** Rejected: the agent-rules file is operating instructions for the agent, not a record of the project's theory. Folding theory into agent instructions rots both — instructions get cluttered with rationale, theory gets dressed as commands.
- **`README.md` as theory document.** Rejected: `README.md` drifts toward marketing and quickstart and is read by visitors. The theory document must be tight, falsifiable, and primarily for the engineer.
- **Single `THEORY.md` including the glossary.** Rejected: glossary work has a different shelf life and a different discipline (the glossary contains no implementation details, no decisions, no scratch notes). Folding it into `THEORY.md` would rot the trunk as terms accumulated.
- **ADRs alone, no `THEORY.md`.** Rejected: ADRs are branch artifacts. Without a trunk, future readers must reconstruct the thesis from the union of decisions — the exact Naur failure mode the system is meant to prevent.

## Consequences

- Every non-trivial change is checked against `THEORY.md` before merging. If the theory shifts, the revision log is updated in the same change.
- Glossary discipline: `CONTEXT.md` is *only* the project's language. Drift here is a maintenance signal.
- ADRs follow the three-condition rule: hard to reverse, surprising without context, real trade-off with real alternatives. Most decisions are not ADR-worthy. The ledger stays sparse.
- The user hand-writes the thesis paragraph before the agent refines it. The struggle to compress is the theory formation; polished theory documents the user never sweated over teach nothing.
- This decision is itself the seed entry in the ADR ledger and the template for ADRs that follow.

## When this should be revisited

When the documentation system itself shows signs of rotting: `THEORY.md` becomes a pitch deck or marketing copy; `CONTEXT.md` fills with implementation notes or stale terms; ADRs proliferate to cover trivial decisions; or contributors begin citing the documents without being able to defend their content. Any of those is a signal that the discipline has slipped, not that the system is wrong — but the symptom is the same and merits a revisit.
