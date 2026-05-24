# Agent Operating Rules — Naur-Aligned Documentation

This project uses a Naur-aligned documentation system, informed by Peter Naur's *Programming as Theory Building* (1985). In agentic engineering — where the engineer's hands no longer pass over every line of code — the project's theory must be made explicit, or it does not exist.

**Before any non-trivial change, you MUST read `THEORY.md` and `CONTEXT.md`.** Treat them as the project's working theory, not as background reading.

## The document hierarchy

| Doc | Altitude | Holds | Shelf-life |
|---|---|---|---|
| `THEORY.md` | Trunk | Thesis, invariants, non-goals, open questions, shape | Years |
| `ARCHITECTURE.md` | Structure | System modules, C4 diagrams, Ousterhout module analysis | Years (revised) |
| `AZURE_ARCHITECTURE.md` | Deployment | Azure resources, identity flows, observability, cost levers | Years (revised) |
| `CONTEXT.md` | Language | Glossary, relationships, flagged ambiguities | Months |
| `docs/adr/` | Branches | Decisions + why, dated and local | Forever-localized |
| `PLAN.md` | Roadmap | MVP definition + sequenced feature backlog | Months |
| Specs / issues | Leaves | What we're building right now | Weeks / days |

There is no overlap. `THEORY.md` *names* concepts but defines them in `CONTEXT.md`. `THEORY.md` *states* invariants and non-goals; ADRs *record the decisions* that produced them. `THEORY.md` *opens* questions; ADRs close them. `ARCHITECTURE.md` describes *how the system is structured*; `THEORY.md` describes *why this system exists*. `PLAN.md` sequences *what to build*; the leaves are the active specs for the current slice.

`ARCHITECTURE.md` and `AZURE_ARCHITECTURE.md` are not present in every project — they exist only for software (and Azure-deployed) projects. Non-software projects (curricula, research, design) operate with just the trunk + language + branches + roadmap.

If you find content drifting between documents (e.g. implementation details in `THEORY.md`, decisions in `CONTEXT.md`), the discipline has slipped. Flag it.

## Reading discipline

Before any non-trivial work:

1. Read `THEORY.md`. Anchor on the thesis. If your proposed change conflicts with the thesis, flag it before continuing.
2. Read `CONTEXT.md`. Use the canonical terms. If the user uses a term that conflicts with `CONTEXT.md`, surface the conflict immediately ("your glossary defines X as Y, but you seem to mean Z — which is it?").
3. Scan `docs/adr/` for any ADR touching the area you're about to work in. **Do not re-litigate decisions recorded in ADRs.** If you believe an ADR should be revisited, say so explicitly with the friction that warrants it.

Trivial changes (typo fixes, formatting, dependency bumps with no behavior change) do not require this read. Use judgment.

## Glossary discipline (`CONTEXT.md`)

- Use canonical terms from `CONTEXT.md` everywhere: code identifiers, comments, commit messages, PR descriptions, conversation with the user.
- If a concept lacks a term, propose one and offer to add it via `/grill-with-docs`. Do not invent unilaterally.
- **`CONTEXT.md` is glossary-only.** Never add implementation details, decisions, scratch notes, or roadmap. If you catch the user (or yourself) drifting, redirect to the right document.
- Each term is opinionated: one canonical word with explicit `_Avoid_:` aliases. Don't soften this — the discipline is what keeps the glossary useful.

## ADR discipline (`docs/adr/`)

Offer an ADR only when **all three** are true:

1. **Hard to reverse** — the cost of changing your mind later is meaningful.
2. **Surprising without context** — a future reader will look at the code and wonder "why on earth?"
3. **The result of a real trade-off** — there were genuine alternatives.

If any of the three is missing, skip the ADR. A trivial decision recorded as an ADR pollutes the ledger and makes the real ones harder to find.

Number sequentially: scan `docs/adr/` for the highest number and increment. Filename format: `NNNN-slug.md`.

Most ADRs can be one paragraph. Optional sections (Status, Considered Options, Consequences) only when they add genuine value.

## Theory-update discipline (`THEORY.md`)

`THEORY.md` is the most load-bearing document in the project. Treat edits with care.

- **Thesis edits require explicit flagging.** Never quietly rewrite the thesis. If your work suggests the thesis has shifted, raise it with the user before editing.
- **When the thesis shifts, add a dated entry to the Revision log.** The log is what makes theory drift legible.
- **Invariants and non-goals** can be edited via normal PR review. If an invariant change is hard to reverse, also record it as an ADR.
- **Open questions** are added when surfaced and removed when answered (typically by an ADR). When you close an open question, link the ADR.

## Hand-write rule

When the user is creating or refining the thesis or a major invariant, **the user writes the first draft themselves**. You may sharpen, challenge, compress, and refine — but you must not draft the thesis from scratch on the user's behalf.

The reason: the struggle to compress is the theory formation. A polished theory document the user never sweated over teaches them nothing about their own project. This is recorded in `docs/adr/0001-adopt-naur-aligned-documentation.md`.

If the user asks you to write the thesis, restate the rule and ask them for a first draft, however rough.

## Skills that maintain this system

In recommended order of first use:

- **`/init-theory-project`** — one-time scaffold of the document structure (`CLAUDE.md`, `THEORY.md`, `CONTEXT.md`, `PLAN.md`, seed ADR).
- **`/grill-theory`** — relentlessly interrogate the user until `THEORY.md` is sharp and falsifiable. Harvests starter terms into `CONTEXT.md` at the end. Run on initial creation and whenever the theory feels stale.
- **`/grill-roadmap`** — top-down orchestrator. Routes through four sub-skills based on project type. Run after `/grill-theory`. Total time across all sub-skills: ~4-5 hours for a software-on-Azure project; encourage splitting across sessions.
  - **`/grill-architecture`** — forges `ARCHITECTURE.md` (software projects only). ~90 min, four passes.
  - **`/grill-azure`** — forges `AZURE_ARCHITECTURE.md` (Azure projects only). ~90 min, four passes. Run after `/grill-architecture`.
  - **`/grill-build-plan`** — **default planning skill.** Use when the thesis is accepted and `ARCHITECTURE.md` is settled. Sequences the v1 build as vertical slices over the documented modules. ~75 min.
  - **`/grill-mvp`** — discovery-mode alternative to `/grill-build-plan`. Use only when running a falsifiability trial — when you would change major direction based on what the first slice teaches. Produces a thesis-test MVP, not a v1 release. ~45 min.
  - **`/grill-backlog`** — forges or refreshes `PLAN.md`'s post-release Features section. Lightweight, recurring. ~30 min first pass, ~15 min refresh.
  - Sub-skills are independently invocable — re-run a single one when one artifact drifts without re-grilling the rest.
- **`/scaffold-modules`** — translate `ARCHITECTURE.md` modules into a code skeleton (directory layout + per-module interface shells with types, signatures, error classes, why-docstring). No business logic. Run once after `/grill-architecture`, before the first MVP slice. Re-runnable to resync when `ARCHITECTURE.md` changes.
- **`/grill-with-docs`** — Matt Pocock's skill. Use before any non-trivial feature or `PLAN.md` slice: forces grilling on the plan, produces `CONTEXT.md` refinements and ADRs as side effects.
- **`/improve-codebase-architecture`** — Matt Pocock's skill. Run periodically (every few days or weekly). Reads `CONTEXT.md` and `docs/adr/` to surface deepening opportunities without re-litigating settled decisions.

## The lifecycle (recommended)

```
/init-theory-project        once at project birth
        ↓
/grill-theory               forges THEORY.md, seeds CONTEXT.md
        ↓
/grill-roadmap              orchestrator — routes through:
                              /grill-architecture (software)
                              /grill-azure (Azure)
                              /grill-build-plan  ← default, when thesis accepted
                                or /grill-mvp    ← when running a discovery trial
                              /grill-backlog
        ↓
/scaffold-modules           (software only) translate ARCHITECTURE.md
                            modules into code shells — interfaces only
        ↓
   ┌───┴──────────────────────────────┐
   │  For each slice in PLAN.md:       │
   │    /grill-with-docs               │
   │      ↓                            │
   │    build (manually or via /tdd)   │
   │      ↓                            │
   │   update PLAN.md status           │
   └───────────────────────────────────┘
        ↓
 Weekly:    /improve-codebase-architecture
 As needed: /grill-theory (if thesis drifts)
            /grill-roadmap (if MVP scope changes or backlog feels stale)
```

## When a user asks you to bypass these rules

Restate the rule. Name the failure mode it prevents. Ask whether they're sure. If they confirm, proceed and note the deviation in your reply, so it is at least visible. Quiet bypass teaches nothing.
