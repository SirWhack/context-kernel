# ADR-0024: The ontology as the kernel's type system — vocabulary, policy, projection

**Date:** 2026-05-31
**Status:** Proposed

## Context

The kernel's "type system" — the controlled set of node kinds and edge kinds the graph
speaks in, the families they belong to, the numeric weights/tiers that rank them, and the
rules that classify a source file into a tier — is currently **smeared across six sites**:

- `scoring.py` — `AUTHORITY_TIERS`, `EDGE_WEIGHTS`, `CENTRALITY_KINDS`, and the
  `classify_source` filename heuristics (hardcoded dicts + an if-ladder).
- `source_kinds.py` — `CODE_EXT` / `IAC_EXT` / `OPS_EXT` extension tuples.
- `summarizer.py` — `ENTITY_KINDS`, `RELATIONSHIP_KINDS`, and the prose kind definitions
  baked into `_SYSTEM_PROMPT`.
- The parser handlers — structural kinds (`module`, `class`, `function`, `resource`, …)
  emitted implicitly by whatever each parser yields.
- `concepts.py` — the optional `ontology.toml` concept-grounding loader (today the *only*
  thing called "ontology", and the narrowest consumer of the vocabulary).
- ADRs 0013 / 0015 / 0021 / 0022 — where the *rationale* lives, in prose.

The acute symptom: a single semantic edge kind is declared in **three** places that must be
hand-synchronised — the `_SYSTEM_PROMPT` prose, the `RELATIONSHIP_KINDS` frozenset, and the
`EDGE_WEIGHTS` table. Adding or renaming a kind is a 3–5 file edit plus a cache-version bump,
with no single source of truth and nothing that fails loud when they diverge. ADR-0021 already
named the *families* (structural vs semantic) in prose but did not give them a home in data.

A research pass (2026-05-31, deep-research over LlamaIndex, Neo4j GraphRAG, Microsoft GraphRAG,
Apple ODKE+, and the 2023–2025 LLM-KGC literature, plus the W3C SKOS/OWL/SHACL standards)
established three things relevant here:

1. **Open-vs-closed is a false binary.** Mature LLM-extraction systems converge on
   *open-with-guidance*: a declared vocabulary that **guides** extraction (improving precision
   and consistency) while remaining **advisory** — unknown kinds are retained, not rejected.
   (LlamaIndex `DynamicLLMPathExtractor`; Neo4j GraphRAG "does not impose strict constraints";
   Microsoft GraphRAG closed `entity_types` + `--discover-entity-types`.)
2. **A verification/confidence step — not the schema constraint — is what buys high precision.**
   ODKE+ went from 91% (raw ontology-guided output) to 98.8% via a downstream corroboration
   pass. The kernel already has that pass: confidence scoring (ADR-0015).
3. **Vocabulary, policy, and projection/validation are legitimately distinct layers** that
   should not be overloaded into one term — mirrored by the semantic-web split of SKOS
   (lightweight controlled vocabulary, self-documenting via note properties) vs OWL annotations
   (non-logical metadata on terms) vs SHACL (closed-world conformance/validation).

## Decision

### 1. Posture: closed-structural, advisory-semantic, deterministic-concept

The vocabulary is governed by **family**, which encodes epistemics *and* the open/closed posture:

- **structural** — parser-derived, literal, **closed**. Emitted only by AST/tree-sitter/IaC
  handlers. The LLM never produces these; an undeclared structural kind cannot appear. Highest
  confidence in the graph.
- **semantic** — LLM-inferred from prose, **advisory**. The declared kinds' definitions are
  injected into the extraction prompt to guide the model. Kinds the model surfaces outside the
  declared set are **retained** (descriptive), not rejected — matching today's
  `log.debug("…accepting anyway")` behaviour — but only declared kinds are documented and
  weighted by name; the rest fall to `edge_weight_default`. Precision is recovered downstream
  by confidence scoring (ADR-0015), not by rejecting kinds at extraction.
- **concept** — deterministic ontology grounding via alias match (ADR-0018), **closed**.

### 2. Three layers, kept distinct

- **Vocabulary** — the kinds, their families, and a self-documenting `definition` (SKOS-like).
  This is the curated, slowly-changing layer.
- **Policy** — numeric `weight` / `centrality` per edge kind and the `authority_tiers` map.
  Carried as **annotations** on the vocabulary terms (OWL annotation-property style:
  co-located for ergonomics, but a conceptually separate layer). These are the kernel's
  **defaults**; the existing per-repo / per-sweep override layer (`[ingester.scoring]` in
  `config.toml` + `CK_SCORING_*` env) is unchanged and still wins on top.
- **Projection** — the closed-world classification rules (extension → source-kind, glob →
  tier) that map a raw path to vocabulary. SHACL-like. Replaces the `*_EXT` tuples and the
  `classify_source` if-ladder.

### 3. The vocabulary becomes a single declarative artifact: `ontology.yaml`

One self-documenting file (repo root or `.context-kernel/`, same search as today's
`ontology.toml`) is the source of truth for vocabulary + policy defaults + projection +
concept grounding. The extraction prompt and the kind-validation derive **from it** instead of
from hardcoded constants — the file *is* the documentation (per the kernel's own
materialize-from-source philosophy). YAML is chosen over TOML because block scalars carry
multi-line `definition`s ergonomically and `pyyaml` is already a dependency;
operational/runtime config (endpoints, model choice, parallelism) stays in `config.toml`.

### 4. `scoring.py` stays pure

The ontology is **not** loaded by `scoring.py` (which keeps its no-I/O tenet). An upstream
loader reads `ontology.yaml` and feeds its policy tables into `ScoringConfig.resolve(section,
env)` — the existing pure seam. The current hardcoded tables in `scoring.py` remain as the
**ultimate fallback**, so a portfolio with no `ontology.yaml` still ingests with defined
behaviour (the errors-out-of-existence contract holds).

### 5. The ontology participates in derived-artifact identity

Changing a kind, weight, or tier changes derived output. Therefore the ontology file's content
hash MUST invalidate the things derived from it:

- the **summarizer cache** (fold the ontology hash into `_CACHE_VERSION` / the cache key,
  since the prompt is now derived from it — extends ADR-0016's context-keys-the-cache rule);
- **`graph_commit`** / freshness (ADR-0008), so a weight/tier edit re-materialises rather than
  serving stale-but-fresh-looking files (invariant 2). *(This consequence is derived from the
  kernel's own content-addressing invariant; the research pass found no external precedent for
  the schema-hash → freshness link, so it is asserted as a local design rule, not borrowed.)*

## Consequences

- New/renamed kinds become a **one-file edit**. The 3–5-site sync hazard (prompt prose +
  `RELATIONSHIP_KINDS` + `EDGE_WEIGHTS` + `CENTRALITY_KINDS` + ADRs) collapses to editing
  `ontology.yaml`; the prompt and validation regenerate from it.
- `ENTITY_KINDS` / `RELATIONSHIP_KINDS` / the prompt's kind bullets, `EDGE_WEIGHTS` /
  `CENTRALITY_KINDS`, and the `*_EXT` tuples / `classify_source` heuristics become *derived*
  from the ontology rather than authored in code (with code defaults as fallback).
- Re-ingest remaps per the ADR-0008 migration; the ontology-hash cache bump forces one cold
  extraction pass.
- A change to a policy number is now a config/ontology edit that re-materialises — good for
  eval sweeps (kernel-vs-grep harness) but it means a weight tweak is a graph-affecting change,
  not a free knob.

## Open sub-decisions (to ratify before implementation)

1. **Weights inline vs. separate block.** This ADR proposes inline-on-the-edge-kind (OWL
   annotation style) for ergonomics. Alternative: a separate `policy.edge_weights` block to
   maximise vocabulary/policy separation. Trade-off is readability vs. purity.
2. **Phasing.** Proposed: Phase 1 = vocabulary drives the prompt + validation (high value,
   low risk — no scoring/freshness change); Phase 2 = policy defaults move to the ontology and
   feed `ScoringConfig`; Phase 3 = projection rules replace the `*_EXT` tuples + heuristics.
3. **graph_commit participation** (Decision §5) — confirm the freshness link is wanted now vs.
   cache-invalidation-only for Phase 1.

## Related

- [ADR-0013](./0013-markdown-entity-taxonomy.md) — the entity/relationship taxonomy this lifts into data.
- [ADR-0015](./0015-entity-confidence-scoring.md) — the weights/tiers/centrality this declares; the confidence pass that recovers precision.
- [ADR-0016](./0016-contextual-entity-extraction.md) — context-keys-the-cache; extended here to ontology-keys-the-cache.
- [ADR-0021](./0021-structural-vs-semantic-edge-families.md) — the families, here given a home in data.
- [ADR-0022](./0022-repo-role-assignment.md) — the per-repo override layer that stays on top of ontology defaults.
- [ADR-0008](./0008-content-derived-graph-commit.md) — the graph_commit identity the ontology hash must feed.
