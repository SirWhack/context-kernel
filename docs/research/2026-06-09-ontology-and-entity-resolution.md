# Research: Ontology evolution, entity resolution, and cross-project linking

**Date:** 2026-06-09
**Status:** Research notes — input to future ADRs (not a decision)
**Origin:** [REVIEW-FABLE.md](../reviews/REVIEW-FABLE.md) Part I, priorities 5 and 6; THEORY.md
open question 1 (cross-project entity merging); ADR-0017/0024/0025 follow-ups
**Companion docs:** [hierarchical materialization](./2026-06-09-hierarchical-materialization-and-importance-ranking.md),
[design signals / normative layer](./2026-06-09-design-signals-normative-layer.md)

Three features motivated this research pass:

- **Feature C — candidate-merge review queue.** Deterministic ER (ADR-0017) under-merges by
  design; the proposed escape is a materialized review queue whose accepted verdicts become
  curated ontology aliases, keeping the merge itself deterministic and idempotent.
- **Feature D — ontology evolution without schema drift.** ADR-0024/0025 made the ontology a
  composed, versioned artifact; the open risk is vocabulary proliferation and drift across
  incremental re-ingests.
- **Feature E — cross-project / cross-language linking.** Today portfolio concept hubs are the
  only cross-repo bridge (non-goal 2 defers entity merging).

Low-confidence claims flagged inline.

---

## 1. Entity canonicalization — what the field learned (2018–2026)

- **CESI** (WWW 2018, [arXiv:1902.00172](https://arxiv.org/abs/1902.00172)): canonicalizes
  OpenIE phrases by fusing deterministic side information (entity linking, paraphrase DBs,
  IDF token overlap, morphological normalization) with learned embeddings, then clustering.
  ~17-point macro-F1 gain over the IDF-token baseline on ReVerb45K *(exact figures low
  confidence — lossy PDF extraction)*. Architectural lesson: deterministic lexical signals
  primary, embeddings one signal among several — structurally the kernel's collision-guard
  design.
- **EDC — Extract, Define, Canonicalize**
  ([arXiv:2404.03868](https://arxiv.org/html/2404.03868v1), 2024): the modern LLM recipe.
  (1) open extraction, (2) the LLM writes a **definition** per schema component,
  (3) canonicalization embeds the *definitions, not surface names*, with an **LLM feasibility
  veto** on embedding-proposed merges. Self-canonicalization precision 0.867–0.956; collapsed
  529–667 self-generated relation types to 200–225; beats CESI specifically on avoiding
  over-generalized merges. **Two takeaways: canonicalize over definitions/evidence, not raw
  names; use the LLM as merge-verifier, never merge-proposer.** (The kernel's recall-then-judge
  pattern, ADR-0025 §4, is the same shape.)
- **LLM pairwise ER is near-ceiling but non-deterministic.** Peeters & Bizer
  ([arXiv:2310.11244](https://arxiv.org/html/2310.11244)): GPT-4 zero-shot F1 76–98 across ER
  benchmarks; the result that matters here is **robustness** — fine-tuned matchers collapse
  36–61 F1 points on unseen entities while GPT-4 holds steady. In-context examples: negligible
  gains, and they *degraded* smaller models 4–26 points (skip them). OpenSanctions Pairs
  ([arXiv:2603.11051](https://arxiv.org/pdf/2603.11051), 2026): off-the-shelf LLMs beat a
  production rule-based matcher (GPT-4o 98.95% F1); remaining gains come from
  blocking/clustering, not pairwise matching.
- **Consensus tradeoff:** deterministic ER = high precision, recall-limited, free, stable;
  embedding ER = recall booster with precision risk on near-collisions; LLM ER = accurate and
  robust but costly and non-deterministic. Every strong system layers them cheap-first — which
  validates ADR-0017's posture and locates the missing piece precisely: a bounded,
  human-gated recall channel.

**Alias management in production KGs** (the pattern the kernel's aliases should follow):

- **Wikidata** ([Help:Merge](https://www.wikidata.org/wiki/Help:Merge)): a merge leaves a
  **permanent redirect**, never a deletion; colliding labels demote to aliases; explicit
  never-merge-when-ambiguous norm (don't merge "tree" with "oak") — the kernel's
  never-guess rule, institutionalized.
- **UMLS**: every source string is an atom (AUI); synonymous atoms cluster under a Concept
  Unique Identifier (CUI). **Two-level mention-ID / concept-ID with redirects-not-deletions is
  the production-standard model.** This maps onto the kernel as: per-project entity IDs
  (AUI-like) optionally clustered under portfolio concept IDs (CUI-like) — already the shape
  of ADR-0025's namespaced concepts.

---

## 2. The review queue — human-in-the-loop curation

- **What to queue: signal disagreement.** Query-by-committee / uncertainty sampling is the
  canonical selection strategy; risk-based sampling that mixes uncertain pairs with
  high-confidence representatives outperforms pure uncertainty
  ([KBS 2021](https://chenbenben.org.cn/paper/youcef_KBS_2021.pdf)). The kernel's "committee"
  already exists: {normalized-name verdict, embedding-cosine verdict, optional LLM-judge
  verdict}. **Queue exactly the pairs where the signals disagree.**
- **Quality guarantees from the gray-zone split.** HUMO
  ([arXiv:1710.00204](https://arxiv.org/abs/1710.00204), ICDE 2018) and r-HUMO
  ([arXiv:1803.05714](https://arxiv.org/abs/1803.05714)): machine decides the confident
  regions, humans decide the uncertain band — enforceable precision *and* recall targets at
  minimized human cost. Human+machine beats either alone.
- **Bounding effort: pay-as-you-go ordering.** Whang, Marmaros & Garcia-Molina (TKDE 2013):
  sort the queue so any review-session prefix yields maximal resolution progress. For a
  one-person operation this is the difference between a usable queue and an ignored one.
- **Reference implementations.**
  - **OpenRefine reconciliation** ([manual](https://openrefine.org/docs/manual/reconciling))
    is the best one-person template: scored candidates per cell; auto-commit above threshold;
    one-click pick in the band; defer below; properties as namesake tiebreakers.
  - **Apple Saga** ([arXiv:2204.07309](https://ar5iv.labs.arxiv.org/html/2204.07309)):
    suspicious facts are **quarantined for human curation**, and corrections are a streaming
    first-class data source re-applied on every rebuild — exactly the promote-to-alias plan.
    Saga also persists source-entity→canonical links as explicit provenance facts, re-validated
    when the underlying source changes (running since 2018 under 33× growth).
  - **Anti-pattern: Amazon AutoKnow's "self-driving" promotion** — viable only with
    behavioral-log training signal a personal kernel doesn't have; without it, auto-promotion
    is precision drift.
- **Record rejections, not just accepts.** Split/merge-repair literature (PAKDD 2016
  correlation-clustering repair) operates on must-link / cannot-link constraints — human
  verdicts map exactly onto these, and the cannot-link half is what prevents the queue from
  re-asking settled questions.

### Proposed kernel mechanism (for a future ADR)

1. At ingest, the resolver emits **merge candidates**: cross-cluster pairs with cosine ≥ θ_low
   but failing name-normalization, orphaned doc concepts matching exactly one method leaf
   (ADR-0026's deferred merge), and near-collision bases. Optional LLM merge-verifier
   (EDC-style feasibility check) pre-filters the queue — judge-gated, content-addressed
   verdicts like `judge_aspect`.
2. Materialize as `views/merge-queue.md`, pay-as-you-go ordered, each row carrying the
   evidence (names, sources, cosine, judge verdict, description excerpts).
3. Operator verdicts land in the ontology overlay as `altLabel` (accept) or a `distinct-from`
   list (reject / cannot-link). Both polarities persist; re-ingest re-derives the same graph
   from source + curated constraints — **idempotence preserved, recall arrives only through
   curation.**

---

## 3. Incremental ER — keeping merges correct across re-ingests

- **Order-dependence is the documented failure mode.** Saeedi & Rahm (ESWC 2020,
  [open access](https://pmc.ncbi.nlm.nih.gov/articles/PMC7250616/)): naive incremental
  attachment shows "substantially lower recall and F-measure... strong dependency on the
  insert order." Their **n-depth reclustering (nDR)** — re-cluster only new/changed entities
  plus their n-hop similarity neighborhood — matches full-batch quality *order-independently*,
  much faster. The kernel currently re-resolves per project from scratch each ingest (which is
  order-independent by brute force); nDR is the path if per-project full resolution ever
  becomes the bottleneck.
- **Staleness of merge decisions:** Saga's answer — explicit provenance per link, re-validated
  when the source partition changes — composes directly with the kernel's content addressing:
  a curated alias or merge whose justifying evidence span's content hash changes gets flagged
  for re-review rather than silently persisting.
- **The idempotence recipe** distilled from this literature: (1) deterministic core from a
  canonical input ordering; (2) every soft decision recorded with provenance so evidence edits
  trigger recomputation, not patching; (3) repair scoped to the changed neighborhood. The
  kernel already does (1); the review queue adds (2); (3) is an optimization to defer.

---

## 4. Ontology evolution without schema drift

- **Drift is measured, not hypothetical.** EDC: unconstrained LLM extraction self-generated
  **529–667 relation types where ~200 sufficed**. DIAL-KG
  ([arXiv:2603.20059](https://arxiv.org/abs/2603.20059), Mar 2026 — real, unreplicated,
  *medium confidence on claims*) gates new schema elements behind an **evolution-intent
  assessment**: is this genuinely a new kind, or drift of an existing one?
- **Kernel translation:** the advisory-semantic posture (ADR-0024) already retains unknown
  kinds descriptively. Add the DIAL-KG-style gate: out-of-vocabulary kinds the extractor emits
  go to a **proposed-kinds holding pen** (materialized, with frequency counts and example
  extractions), never directly into the weighted vocabulary. Promotion is an overlay edit —
  the same release-gate motion as alias promotion.
- **Vocabulary size has a measured ceiling.** Extraction quality degrades as the label space
  grows: NER drops from 4 → 18 types, RE drops from 10 → 42 relations, and "drops
  significantly" scaling 100 → 800 relation types
  ([arXiv:2407.18540](https://arxiv.org/pdf/2407.18540); attribution of the smaller-scale
  numbers *medium confidence*); including small-schema definitions in the prompt measurably
  helps ([arXiv:2305.01555](https://arxiv.org/pdf/2305.01555)). No exact sweet spot, but the
  evidence brackets it: **single-digit-to-low-teens kinds per prompt is reliable; dozens is
  not.** The kernel's 8–9 semantic kinds + 5 relationship kinds sits inside the safe band —
  treat that band as a budget when accepting per-project kind additions (ADR-0025 union-add
  could otherwise grow a project's composed prompt past it).
- **Versioning practice from vocabularies that survived decades** (W3C SKOS Primer; CSIRO SKOS
  best practice; Getty Vocabularies workflow; Library of Congress SACO):
  - **Version the scheme, never the concept URIs/IDs.** Stable IDs; additions and deprecations,
    not mutations; merges leave redirects.
  - One `prefLabel` (unique within the scheme) + `altLabel` for synonyms + **`hiddenLabel`** for
    match-only strings (misspellings, legacy names) that ground matches but never render — a
    third bucket the kernel's concept schema lacks and should add cheaply.
  - **Batch release gates, editor-controlled.** Getty publishes monthly after editorial vetting;
    SACO proposals take ~9–10 weeks of review. The one-person distillation: vocabulary changes
    accumulate as proposals; acceptance is an explicit ontology-file commit (the kernel's
    "release"), which — via the composed-ontology hash (ADR-0025 §5) — already invalidates
    derived artifacts surgically.
- **What not to build:** OWL-style axiom-heavy formalization. Both SEONs (Zurich's
  [se-on.org](http://se-on.org/); UFES's EKAW 2016 network) stayed academic; OSLC survives as
  a standard with chronic adoption problems; schema.org/SoftwareSourceCode survives *because*
  it is a handful of properties. The post-mortems converge on annotation cost without
  incentive alignment. **Small closed structural vocabulary + tiny advisory layer is the
  survivable shape** — the kernel's current design, kept deliberately.

---

## 5. Cross-project and cross-language linking

- **Contract-anchored linking, not name-based.** The research base for general cross-language
  link detection is thin (2023 JSS systematic review — paywalled, internals unverified, *low
  confidence*), and inter-language dependencies are empirically the buggiest edges
  ([arXiv:2411.08388](https://arxiv.org/pdf/2411.08388)). Industry converged on the **API
  contract as the join point**: FastAPI/Pydantic → `openapi.json` → openapi-typescript —
  operationIds and schema names are the shared anchors binding a Python symbol to a TypeScript
  symbol. **Kernel translation:** an OpenAPI/manifest StructuredHandler. The spec file is a
  deterministic source: `operation` and `schema` entities, `exposes`/`consumes` structural
  edges to backend handlers and frontend client call sites. This — plus dependency manifests
  (`pyproject.toml`/`package.json` naming sibling projects → project-level `depends-on`) — is
  cross-project linkage with zero LLM and zero entity merging, inside non-goal 2.
- **The concept layer is the right bridge for everything non-contractual** — and the UMLS
  AUI/CUI model says the current design (per-project entities, portfolio concept hubs) is the
  production-standard shape. Two projects' `Scheduler`s stay distinct entities that share (or
  don't) a concept. THEORY's open question 1 can likely be answered "no entity merging needed"
  *if* contract-anchored edges + concept hubs together carry the cross-project queries — a
  measurable claim for the eval.
- **Aspect-concepts are feature location — use that field's evaluation method.** The canonical
  survey (Dit, Revelle, Gethers & Poshyvanyk, JSME 2013) and follow-ups consistently find
  **hybrid techniques beat single-source ones** — IR + execution info + static dependencies
  (HITS/PageRank over traces improved effectiveness up to 62%,
  [EMSE 2012](https://link.springer.com/article/10.1007/s10664-011-9194-4)). The kernel's
  recall-then-judge with evidence spans is a modern hybrid instance (LLM judge replacing the
  dynamic-analysis filter). The field's **re-enactment gold sets** transfer directly: closed
  issues/ADRs mapped to the methods their implementing commits actually changed are free
  ground truth for aspect-concept grounding — mine the portfolio's own history for the eval.
  A 2021 baseline study ([PMC8550475](https://pmc.ncbi.nlm.nih.gov/articles/PMC8550475/))
  warns implementation choice alone swings IR results materially — pin and report the exact
  retrieval configuration.

---

## 6. Design implications (summary)

| Feature | Adopt | Avoid |
|---|---|---|
| Merge review queue | Signal-disagreement filtering; pay-as-you-go ordering; OpenRefine three-tier UX; Saga-style persisted verdicts (both polarities: `altLabel` + `distinct-from`); optional EDC-style LLM merge-verifier pre-filter | Auto-promotion without human gate; in-context examples in the verifier prompt; pure-embedding merging |
| Ontology evolution | SKOS discipline (stable IDs, prefLabel/altLabel/**hiddenLabel**, redirects); proposed-kinds holding pen with an evolution-intent gate; batch release commits; keep composed kind-count ≲ low teens per prompt | OWL-weight axiomatization; per-edit vocabulary churn; letting union-add grow a project's prompt past the reliability band |
| Cross-project linking | OpenAPI/manifest StructuredHandlers (contract-anchored edges); project-level `depends-on` from manifests; UMLS-style entity/concept two-level identity (already the shape); re-enactment gold sets for aspect evaluation | Name-based cross-language symbol matching; cross-project embedding merges (the highest-risk namesake case) |

## Open questions for the eventual ADRs

- Where do `distinct-from` (cannot-link) constraints live — ontology overlay (versioned,
  composed) or a separate curation file? Overlay keeps one curation surface; volume may argue
  for separation.
- Does the merge-verifier LLM judge run at ingest (cost on every cold pass) or only when the
  queue view is materialized? (Suggest: queue-time, content-addressed verdicts.)
- Should the proposed-kinds holding pen feed the documentation-gap machinery (a recurring
  out-of-vocabulary kind is itself a vocabulary gap)?
- Contract handler scope: OpenAPI first (FastAPI emits it natively); GraphQL SDL and protobuf
  are the same pattern when needed.
