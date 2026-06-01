# ADR-0025: Ontology composition — a shipped base, per-project overlays, and the end of ontology.toml

**Date:** 2026-06-01
**Status:** Proposed

## Context

ADR-0024 made `ontology.yaml` the kernel's declarative type system (vocabulary + policy +
projection) and folded the hardcoded kind tables into it — but only as a **single file
found at the ingest root**, with the per-project concept layer still living in a separate
`ontology.toml` (`concepts.py`). Two gaps surface the moment the kernel is used as intended
— `ck ingest --portfolio ~/Code` over several repos into **one shared graph**:

1. **The loader does single-file lookup, not composition.** `ontology.py:find_ontology`
   returns the first `ontology.yaml` at `root` or `root/.context-kernel/`. In a portfolio,
   only the file at the portfolio root applies; a per-project `.context-kernel/ontology.yaml`
   is never seen. There is no way to say "the standard type system, **plus** the three extra
   kinds and the concepts this repo needs."

2. **"Ontology" conflates two things with opposite locality.** It is at once the *type
   system* (what KINDS of node/edge exist; how authoritative an ADR is) — which must be
   **global** so a `decision`, a `calls` edge, or the `ADR` tier means the same thing in
   every repo of a shared graph — and *instance data* (the domain concepts: "Turn Panel",
   "Authentication") — which is **per-project**. A single global file can't hold the locals;
   copying the file into each repo rebuilds the exact cross-site smear ADR-0024 killed, now at
   repo scale, and the moment two copies drift the shared graph is incoherent.

3. **The format split is arbitrary.** Kinds/policy/projection live in `ontology.yaml`;
   concepts live in `ontology.toml` (`concepts.py`), with a *third*, implicit schema smeared
   between the loader (reads `prefLabel`/`altLabel`/`definition`) and the spike file (authors
   `recall_keywords`/`structural_patterns`/`broader` that the loader ignores). ADR-0024 §"Concept
   grounding (Phase 3)" already planned a `.toml → .yaml` migration but left it as a naïve
   move, without resolving locality or the schema.

4. **The cache/`graph_commit` coupling is too coarse.** ADR-0024 §5 folds the ontology's
   content hash into the summarizer cache and `graph_commit` **globally** — so editing one
   project's concepts cold-busts re-extraction across the **entire** portfolio.

The governing constraint behind all four is the **shared-graph invariant**: a portfolio ingest
produces one merged graph, so anything that changes the *meaning* of a node/edge/tier must be
global, while anything that is a local *binding* (which file is THEORY, what `.svelte` is, which
concepts this domain has) can be per-project. ADR-0022 already drew this line for tiers — *the
tier number stays global so a role means the same across the portfolio; only role assignment is
local.* This ADR generalizes that one principle — **global meaning, local binding** — to the
whole ontology, and replaces `ontology.toml`.

## Decision

### 1. The ontology is layered by locality, and the file boundary is the locality boundary

| Layer | Locality | Rationale |
| --- | --- | --- |
| Structural kinds (`module`, `class`, `calls`, `contains`, …) | **Global, closed** | Emitted by the parser handlers regardless of any file; a structural kind not in the base would never be emitted. |
| Semantic kinds (`decision`, `invariant`, …) | **Global base + per-project *add*** | A shared kind must extract consistently; a project may *extend* the vocabulary (e.g. `feature-flag`) without redefining shared kinds. |
| Policy (edge weights, tier numbers, centrality) | **Global** (in a shared graph) | Per-project weights would make an edge's weight depend on which repo it came from — incoherent in a merged graph. Run-scoped override stays in `config.toml`/`CK_SCORING_*` (ADR-0022), not the overlay. |
| Projection (extensions, path→tier globs) | **Per-project bindings → global tiers** | Path conventions are local (`proposals/*`→SPEC here, `specs/*`→SPEC there); the tier *number* they bind to stays global. |
| Concepts — cross-cutting aspects (Auth, ErrorHandling) | **Portfolio-global hubs** | They bridge repos; the same aspect should match code in every project (one `project=null` hub — the cross-repo bridge). |
| Concepts — domain entities (Turn Panel) | **Per-project** | Exist in one repo only. |

### 2. `compose_ontology(base, portfolio_overlay, *per_project_overlays)` with layer-specific merge

`find_ontology` (single file) is replaced by composition. The effective ontology **for a given
project P** is `base ⊕ portfolio_overlay ⊕ P_overlay`, with a different merge operator per layer:

| Layer | Operator | Conflict rule (all non-raising — log and continue) |
| --- | --- | --- |
| Structural kinds | base-only (locked) | An overlay declaring/redefining one → ignored + warn. |
| Semantic kinds | union-add | New name → added (its `definition` joins P's extraction prompt). Existing base name → definition **not** overridable (ignored + warn). Two overlays add the same new name with divergent definitions → earlier-in-order wins + warn. |
| Policy | base-only | An overlay `policy:` block → ignored + warn (point the author at `config.toml`/`CK_SCORING_*` for run-scoped overrides). |
| Projection | base extend/override | Extensions union. Per-project tier-globs extend/override base globs, but a glob whose tier name is not defined in base policy → dropped + warn (no inventing tiers — ADR-0022). |
| Concepts | namespaced union | Portfolio-overlay concept → portfolio namespace (`portfolio\|concept\|key`, the existing bridge id). Per-project-overlay concept → project namespace (`project\|concept\|key`). Same namespace + same key → alias/field merge. Optional `scope: portfolio` on a per-project concept promotes it to a bridge. |

Semantic-kind union-add is coherent in a shared graph because **extraction is per-project** (each
file is summarized in its own project's composed prompt) even though the **graph is shared**: a
`feature-flag` kind added in project A simply labels A's nodes and never appears on B's. Only
*redefining a shared kind* breaks coherence, which is why that alone is forbidden.

### 3. The base ships *with the kernel*, as data — completing the de-smear

The base `ontology.yaml` becomes a **package resource** inside `context_kernel` (loaded via
`importlib.resources`), so it "ships with all projects" by shipping inside the installed tool.
This retires the hardcoded fallbacks in `summarizer.py`/`scoring.py` from "the real base" to
genuine emergency-only defaults, finishing what ADR-0024 Phase 1 started (the base is now *data*,
not constants). The `ontology.yaml` committed at the context-kernel repo root stops doing double
duty as "the base" and becomes simply **context-kernel's own overlay** (plus the authored source
of the packaged base during kernel development).

### 4. Concepts fold into YAML; the base defines the schema, overlays carry the instances

`ontology.toml` is **removed**. Concept *instances* move into the `concepts:` block of the
relevant overlay `ontology.yaml`. The base declares the concept **type schema** — this is the
realization of "the type system defines the concept files": the base says what shapes are valid;
the overlays are instances conforming to it.

Base (packaged) — the concept-type schema:

```yaml
concept_types:
  entity:                      # a symbol IS an instance of the concept
    grounding: alias-match     # deterministic: normalize(name|alias) ∈ {prefLabel, altLabel}
    emits: implemented-by      # concept hub → matched code anchor (existing, ADR-0018)
    fields:
      required: [prefLabel]
      optional: [altLabel, definition, broader, related, narrower]
  aspect:                      # a symbol PARTICIPATES IN the concept
    grounding: recall-then-judge   # recall_keywords/structural_patterns gather; LLM judge confirms
    emits: manifested-by       # concept hub → code node (NEW concept-family edge)
    fields:
      required: [prefLabel, definition]
      optional: [altLabel, recall_keywords, structural_patterns, precision_patterns, broader, related]
```

`entity` grounding is the alias-match already in production (`concepts.py`). `aspect` grounding
(recall-then-judge) and its `manifested-by` edge are **implemented**
(`concepts.ground_aspect_concepts` + `LLMSummarizer.judge_aspect`): recall gathers candidates via
`recall_keywords`/`structural_patterns` (capped per `ingester.aspect_max_candidates`), an LLM judge
confirms participation (verdicts cached), and confirmed candidates get a `manifested-by` edge from a
portfolio-global aspect hub. The richer fields the Ticket Agent spike authored (`recall_keywords`,
`structural_patterns`, `precision_patterns`) are first-class instead of silently dropped.

*(Update: the original proposal deferred aspect grounding as "declared, not yet wired"; it was
subsequently implemented and ported from the spike — recall over entity descriptions, not raw
source, with the judge supplying precision. Source-level structural recall remains a future
enhancement.)*

### 5. The content hash becomes composition-aware and per-project — surgical cache busts

ADR-0024 §5's "ontology hash → summarizer cache + `graph_commit`" is refined: the cache key for
project P's extraction is the hash of P's **composed** ontology, `hash(base ⊕ portfolio ⊕ P)`.
Therefore:

- Editing P's overlay re-extracts **only P**.
- Editing the base or portfolio overlay re-extracts **everything** (correct — a base change is
  global).

This turns the portfolio-wide cold-bust friction into a targeted one. Each overlay file is a
reserved kernel file (`ONTOLOGY_BASENAMES`), so it is excluded from extraction yet walked into the
source tree, so an overlay edit still gates freshness per project (invariant 2 / ADR-0008).

### 6. Empty works on day one

A project with **no overlay** ingests fully: the base supplies every kind, weight, tier, and
projection rule, and the structural kinds emit from the handlers regardless. Concepts are simply
absent (no grounding) until authored. Fleshing out an overlay — concepts, projection bindings,
semantic-kind additions — is **additive precision, never a prerequisite**, preserving the kernel's
errors-out-of-existence contract. The natural authoring loop: ingest surfaces candidates
(high-centrality emergent nodes → entity-concepts; recurring keywords → aspect-concepts), the human
promotes them into the overlay.

### Worked example — migrating the Ticket Agent's `ontology.toml`

The existing `Ticket Agent/.context-kernel/ontology.toml` holds eight entity-concepts and four
aspect-concepts. Composition forces a correct **split** by locality:

- **Domain entities stay** in `Ticket Agent/.context-kernel/ontology.yaml` (project-scoped):
  `turn-panel`, `graph-responder`, `query-pipeline`, `session`, `dataset`, `authorization-gate`,
  `loop-detector`, `agent-config`.
- **Cross-cutting aspects move up** to the portfolio overlay (`~/Code/ontology.yaml`, global
  bridges): `error-handling`, `authentication`, `evaluation`, `concurrency` — these should match
  code in every repo, so they become `project=null` hubs.

```yaml
# Ticket Agent/.context-kernel/ontology.yaml  (per-project overlay)
concepts:
  turn-panel:
    type: entity
    prefLabel: Turn Panel
    altLabel: [turn_panel, TurnPanel, TurnPanelResponder]
    definition: The streamed Teams activity that renders an agent turn's lifecycle.
    related: [graph-responder]
  # … the other seven domain entities …
```

## Consequences

- **One format, file = locality.** All ontology is YAML; where a thing is declared determines
  whether it is global or local. `ontology.toml` and its bespoke loader are deleted.
- **Per-project ontologies become real** — and are *overlays*, born empty, never copies of the base.
- **The base is an explicit, versioned, shipped artifact**; the hardcoded tables retire to
  emergency fallback, completing ADR-0024's mission.
- **Cache busts are surgical**: a project's concept edit re-extracts only that project.
- **The aspect concept type is recorded**, giving the spiked recall+judge mechanism a home and a
  declared `manifested-by` edge to wire later.
- **Migration cost:** the one existing `ontology.toml` (Ticket Agent) is split and converted; no
  other repo has one. No dual-format reader is maintained (pre-1.0, internal) — YAML is the only
  going-forward format.

## Open sub-decisions (to ratify before implementation)

1. **Base home:** package resource (`importlib.resources`) vs a conventional path
   (`context_kernel/ontology.base.yaml`). Proposed: package resource — it is what "ships with all
   projects" most literally means.
2. **Concept locality signal:** location-determines-locality (portfolio overlay = global, project
   overlay = scoped) with an explicit `scope:` escape hatch, vs typing it (`aspect`→global,
   `entity`→scoped). Proposed: location, because it keeps the type axis (grounding mechanic) and
   the locality axis independent.
3. **Composition timing:** compose once per project at ingest start vs lazily per file. Proposed:
   once per project (the prompt and cache key are per-project anyway).
4. **Overlay reach:** confirm the source walk descends into each project's `.context-kernel/` for
   the overlay file so freshness gates per project (today `.context-kernel/` may be excluded
   wholesale).

## Related

- [ADR-0024](./0024-ontology-as-type-system.md) — the type system this ADR distributes; resolves
  its open sub-decision #2 (portfolio merge) and supersedes its naïve Phase-3 concept migration.
- [ADR-0022](./0022-repo-role-assignment.md) — "global tier number / local role assignment"; this
  ADR generalizes that principle to every ontology layer.
- [ADR-0018](./0018-evidence-anchored-concept-edges.md) — the concept grounding and `implemented-by`
  edge whose schema is now declared in the base.
- [ADR-0017](./0017-entity-resolution-identity-merging.md) — the project-scoped vs portfolio-scoped
  concept ids the concept namespacing reuses.
- [ADR-0008](./0008-content-derived-graph-commit.md) — the freshness identity the per-project
  composed-ontology hash feeds.
