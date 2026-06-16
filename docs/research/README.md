# Research notes

Research-grounded feature investigations. These are **inputs to ADRs, not decisions** — each
document surveys the literature for a planned feature area, flags evidence confidence, and ends
with design implications and the open questions an eventual ADR must ratify.

Origin: the 2026-06-09 external review ([REVIEW-FABLE.md](../reviews/REVIEW-FABLE.md)).

| Document | Feature area | Feeds |
|---|---|---|
| [Hierarchical materialization & importance ranking](./2026-06-09-hierarchical-materialization-and-importance-ranking.md) | Bottom-up scope summary composition; edge-derived AGENTS.md sections; PageRank-style selection; eval methodology | Review priorities 1–4; THEORY altitude-composition thesis |
| [Ontology & entity resolution](./2026-06-09-ontology-and-entity-resolution.md) | Candidate-merge review queue → curated aliases; ontology evolution without drift; cross-project/contract-anchored linking | Review priorities 5–6; THEORY open question 1; ADR-0017/0024/0025 follow-ups |
| [Design signals & the normative layer](./2026-06-09-design-signals-normative-layer.md) | Tenets distribution; hotspot/change-coupling/depth/doc-gap signals; effective-FP discipline; agent-facing promotion gates | REVIEW-FABLE.md Part II; THEORY open question on Ousterhout encoding |

Conventions: every load-bearing claim carries a citation; confidence flags ([HIGH]/[MED]/[LOW]
or inline) mark verification status; "absence claims" (no published work found) are flagged as
such since searches can miss obscure work.
