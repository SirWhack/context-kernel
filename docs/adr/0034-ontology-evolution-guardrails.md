# ADR-0034: Ontology evolution guardrails — proposed-kinds holding pen and release gates

**Date:** 2026-06-09
**Status:** Proposed (extends ADR-0024 / ADR-0025)

## Context

ADR-0024 set the advisory-semantic posture: out-of-vocabulary kinds the LLM extractor emits
are retained descriptively (`log.debug("…accepting anyway")`) and weighted at
`edge_weight_default`. ADR-0025's union-add lets per-project overlays extend the semantic
vocabulary. Two drift risks are now documented rather than hypothetical
(docs/research/2026-06-09-ontology-and-entity-resolution.md §4):

- **Vocabulary proliferation.** Unconstrained LLM extraction self-generates kinds at scale —
  EDC measured 529–667 self-generated relation types where ~200 sufficed (arXiv:2404.03868);
  DIAL-KG (arXiv:2603.20059) gates new schema elements behind an explicit "evolution-intent"
  assessment for exactly this reason.
- **Prompt-reliability ceiling.** Extraction quality degrades measurably as the label space
  grows (NER 4→18 types, RE 10→42, "drops significantly" 100→800 relations;
  arXiv:2407.18540). The safe band is single-digit-to-low-teens kinds per prompt; the kernel's
  current 8–9 semantic kinds sit inside it, but union-add has no brake.

Vocabularies that survived decades (SKOS practice, Getty, Library of Congress) share three
habits: stable concept IDs (additions and deprecations, never mutations); batch editorial
release gates rather than per-edit churn; one editor with final control.

## Decision

1. **A proposed-kinds holding pen.** The accepting-anyway path additionally records, per run,
   `(kind, count, example extraction, source chunk ref)`. These materialize as
   `views/ontology-proposals.md`: frequency-ranked, with a ready-to-paste overlay snippet per
   kind (the ADR-0033 queue UX, applied to vocabulary). Out-of-vocabulary kinds continue to
   enter the graph descriptively at default weight — nothing is rejected — but they are now
   *visible and promotable* instead of silently accumulating in debug logs.
2. **A composed-prompt kind budget.** `compose_ontology()` warns loudly when a project's
   composed semantic-kind count exceeds `ontology.max_prompt_kinds` (default 15). Warn, never
   fail — the errors-out-of-existence contract holds; the warning names which overlay
   additions pushed past the band.
3. **The release-gate convention, documented in the schema.** Vocabulary changes land as
   deliberate overlay commits (the per-project composed-ontology hash, ADR-0025 §5, already
   scopes the re-extraction blast radius). Kinds are **deprecated, never deleted**; renames
   keep the old name as a hidden alias so historical extractions still resolve. The convention
   lives as prose in `ontology.base.yaml`'s header — the file is the documentation (ADR-0024).
4. **The pen feeds the gap machinery.** A proposed kind recurring across many runs/projects is
   itself a vocabulary gap; the proposals view ranks by recurrence so the operator promotes
   what the corpus keeps asking for — the same surfaced-candidate → human-promotes loop as
   ADR-0025 §6 concepts and ADR-0033 merges.

## Considered options

- **Hard-closed semantic vocabulary (reject OOV kinds at extraction).** Rejected — ADR-0024
  already settled open-with-guidance on the research record (rejection loses information;
  precision is recovered downstream by confidence, not schema constraints).
- **Auto-promotion of frequent kinds.** Rejected — same stance as ADR-0033: promotion without
  a human gate is precision drift; frequency is the *ranking*, not the decision.
- **Per-edit ontology releases (no batching).** Rejected — per-edit cache busts and constant
  re-extraction churn; the surgical hash (ADR-0025 §5) makes batch commits cheap, and the
  surviving-vocabulary precedent is uniformly batch-gated.

## Consequences

- Schema drift becomes an observable, ranked queue instead of a silent debug-log phenomenon;
  the kind vocabulary stays small *because the pressure to grow it is visible and triaged*.
- One new view; one new warning; counter plumbing in the summarizer's validation path. No
  graph-schema change.
- The 15-kind budget creates the first explicit constraint on ADR-0025's union-add — a
  per-project overlay that would breach it gets warned at compose time, before extraction
  quality silently degrades.

## When this should be revisited

- The proposals view stays empty across months of real ingests → the extractor is already
  well-guided; retire the view to a journal line.
- A genuine domain needs >15 kinds → that is the trigger to design *kind retrieval*
  (EDC-style retrieve-then-extract per chunk) rather than raising the budget — a different,
  larger decision.

## Related

- [ADR-0024](./0024-ontology-as-type-system.md) — the open-with-guidance posture this instruments.
- [ADR-0025](./0025-ontology-composition-per-project-overlays.md) — union-add and the surgical hash.
- [ADR-0033](./0033-merge-review-queue.md) — the sibling promote-from-queue mechanism.
- docs/research/2026-06-09-ontology-and-entity-resolution.md §4.
