# FEAT02 — Ontology as the kernel's declarative type system

Implementation plan for **ADR-0024** (the ontology as vocabulary / policy / projection).
Read the ADR first — this doc is *how*, it is *why*. Grounded in a deep-research pass
(2026-05-31: LlamaIndex, Neo4j GraphRAG, Microsoft GraphRAG, Apple ODKE+, the 2023–2025
LLM-KGC literature, and the W3C SKOS/OWL/SHACL standards; 24/25 verified claims).

> Status: **Phase 1 merged** (`32e581e`, +13 tests, full suite 524 green). The vocabulary
> drives the extraction prompt + validation. Phases 2 (policy) and 3 (projection + concept
> migration) are planned below. ADR-0024 is **Proposed** — ratify after Phase 2/3 or sooner.

## 1. What we're building

A single declarative `ontology.yaml` that is the source of truth for the kernel's *type
system*, replacing tables hand-maintained across six sites (scoring.py, source_kinds.py,
summarizer.py's prompt + frozensets, the parser handlers, concepts.py, and prose ADRs). It
holds three layers, kept distinct (SKOS/OWL/SHACL precedent — vocabulary ≠ policy ≠ validation):

- **Vocabulary** — node + edge `kind`s, each with a `family` and a self-documenting
  `definition`. `family` encodes the open/closed posture: **structural** (parser-only, CLOSED),
  **semantic** (LLM-inferred, ADVISORY — definitions feed the prompt; unknown kinds retained,
  not rejected), **concept** (deterministic grounding, CLOSED).
- **Policy** — `weight` / `centrality` per edge kind (inline, OWL-annotation style) + the
  `authority_tiers` map. Numeric, tunable.
- **Projection** — extension → source-kind and glob → tier rules. Closed-world classification.

The posture (advisory-semantic) is only safe because precision is recovered downstream by the
**confidence pass** (ADR-0015), not by rejecting kinds — the ODKE+ finding (91% → 98.8% via
corroboration, not schema constraint). The kernel already has that pass.

**The governing mechanism (every phase):** each layer replaces a hardcoded code table with
YAML, but the code table stays as a **never-fail floor** (errors-out-of-existence: no/broken
`ontology.yaml` → defaults, never raises). Each phase ships an **anti-drift guard test** that
asserts the committed YAML reproduces that floor value-for-value — so the single-source-of-truth
claim is enforced, not aspirational. Phase 1 already does this (`build_system_prompt(ontology)
== _SYSTEM_PROMPT`, byte-for-byte).

## 2. Module map

| Module | Role | Phase | Status |
|---|---|---|---|
| `ontology.yaml` | the artifact — vocabulary (P1) + policy (P2) + projection/concepts (P3) | 1·2·3 | **new (P1)** |
| `context_kernel/ontology.py` | loader: `Ontology`/`Kind`; `entity_bullets`/`entity_kinds` (P1); `policy_defaults()` (P2); `projection()`/`concepts()` (P3). File I/O, never raises. | 1·2·3 | **new (P1)**, extended P2/P3 |
| `ingester/summarizer.py` | prompt + validation + cache key derive from ontology, hardcoded fallback | 1 | **done (`32e581e`)** |
| `ingester/__init__.py` | `is_ontology_file()` excludes the file from extraction (still walked → commit) | 1 | **done (`32e581e`)** |
| `agent_cli.py` | load `ontology.yaml`, inject into summarizer (P1) and into config resolution (P2/P3) | 1·2·3 | **done (P1)**, changed P2 |
| `scoring.py` | `ScoringConfig.resolve(section, env, *, ontology_defaults=…)` overlays policy floor; `classify_source` reads projection from `cfg` | 2·3 | changed |
| `source_kinds.py` | `*_EXT` tuples become the floor; extension classification sourced from `cfg` | 3 | changed |
| `config_store.py` | thread ontology policy (P2) + projection (P3) into the `ScoringConfig` resolution chain | 2·3 | changed |
| `ingester/concepts.py` | load `concepts:` from `ontology.yaml` (was `ontology.toml` `[concepts.*]`) | 3 | changed |
| `tests/test_ontology.py` | per-phase guards (vocab parity P1; policy parity P2; projection parity P3) | 1·2·3 | **+13 (P1)** |

**Invariant (preserved across all phases):** `scoring.py` and `source_kinds.py` stay **pure
(no filesystem/git/clock)**. The ontology file is read by an *upstream* loader and its tables
passed in as plain dicts via the existing pure `ScoringConfig.resolve(section, env)` seam. The
modules never `import` and read the YAML themselves.

## 3. The `ontology.yaml` shape + `ontology.py` interface

```yaml
version: 1
nodes:                                   # vocabulary
  - {kind: module,  family: structural, definition: …}          # CLOSED (parser-only)
  - {kind: decision, family: semantic,  definition: …}          # ADVISORY (feeds prompt)
  - {kind: stale-claim, family: semantic, prompt: false, …}     # valid kind, not a bullet
  - {kind: concept, family: concept, definition: …}             # CLOSED (grounding)
edges:
  - {kind: governed-by, family: semantic, weight: 0.95, centrality: true, definition: …}
policy:                                  # P2 — numeric, tunable
  authority_tiers: {THEORY: 1.0, …, EPHEMERAL: 0.2}
  authority_default: 0.3
  edge_weight_default: 0.5
projection:                              # P3 — path → source-kind / tier
  code_ext: [.py, .ts, …]
  iac_ext:  [.tf, …]
  ops_ext:  [.yaml, .yml]
  tiers: {THEORY: ["theory.md"], ADR: ["docs/adr/*", …], …}
concepts:                                # P3 — SKOS keys, migrated from ontology.toml
  knowledge_store: {prefLabel: KnowledgeStore, altLabel: […], definition: …}
```

```python
# context_kernel/ontology.py — file I/O, never raises (None → caller uses its floor)
def is_ontology_file(path: Path) -> bool          # reserved names; excluded from extraction
def find_ontology(root: Path) -> Path | None      # root/ontology.yaml or root/.context-kernel/
def load_ontology(root: Path) -> Ontology | None   # None if absent/malformed/empty

class Ontology:
    content_hash: str                  # sha256 of raw bytes — keys caches, gates graph_commit
    def entity_kinds() -> frozenset[str]            # P1 — semantic node kinds (validation)
    def relationship_kinds() -> frozenset[str]      # P1
    def entity_bullets() -> str                     # P1 — prompt bullets (prompt:true only)
    def relationship_bullets() -> str               # P1
    def policy_defaults() -> dict                   # P2 — {authority_tiers, edge_weights,
                                                    #       centrality_kinds, *_default}
    def projection() -> Projection                  # P3 — ext tuples + tier glob map
    def concepts() -> tuple[ConceptSpec, ...]       # P3 — grounding specs
```

## 4. The hard part — feeding scoring without breaking purity (P2/P3)

`scoring.py`'s defining tenet is "pure, total, no I/O." The whole feature would violate it if
the file were loaded *inside* scoring. It isn't. The resolution chain becomes a **four-layer
overlay**, each layer pure, the ontology slotted between the hardcoded floor and the local config:

```
hardcoded floor (scoring.py / source_kinds.py)   # never-fail; ships with the code
  → ontology.yaml policy/projection               # the project source-of-truth default (P2/P3)
    → config.toml [ingester.scoring] / [ingester]  # per-repo override (ADR-0022)
      → CK_SCORING_* env                            # sweep override, highest (the eval harness)
```

Mechanics: `ScoringConfig.resolve(section, env, *, ontology_defaults=None)` gains one optional
dict param. The upstream loader (`config_store` / `agent_cli`, which already do I/O) reads
`ontology.yaml`, calls `Ontology.policy_defaults()` / `.projection()`, and passes the dict in.
`resolve` overlays it on the hardcoded tables before applying `section` then `env`. `scoring.py`
imports the `Ontology` *type* under `TYPE_CHECKING` only — no runtime read. Downstream is free:
`_apply_concept_layer` and the ingest scoring pass already call `scoring.authority(…, cfg)` /
`scoring.edge_weight(…, cfg)`, so once `cfg` carries the ontology values they propagate with zero
new wiring.

`classify_source` (P3) is the fiddliest: today it's an ordered if-ladder (roles → theory/arch/adr
→ code-ext → ops-ext → context/reference/spec/ephemeral → default). P3 must reproduce that exact
**resolution order** from data — `cfg.roles` (per-repo, most-specific glob, unchanged) still wins,
then the ontology `projection.tiers` globs and `*_ext` in the current precedence. Order parity is
the risk, and the guard test enforces it (every current classify_source case → same tier from data).

**graph_commit / freshness is satisfied for free.** `ontology.yaml` lives at repo root, so it's
walked into `source_tree_hash` and `_compute_graph_commit` (Phase 1). A policy/projection edit
changes the stored `confidence`/`centrality`/`weight`/`source_tier` (materialized at ingest, ADR-0019),
hence the commit, hence re-materialization — no stale-but-fresh-looking serve (invariant 2). The
trade-off (ADR-0024 §5): a weight tweak is now a graph-affecting change requiring re-ingest, not a
free knob. The `CK_SCORING_*` env layer remains the no-commit path for eval sweeps.

## 5. Build sequence (phases; slices within each ship + test independently)

### Phase 1 — Vocabulary drives the prompt + validation  ·  **DONE (`32e581e`)**
Lowest-risk-first: no scoring/freshness change. The extraction prompt and the entity/relationship
validation sets derive from `ontology.yaml`; the ontology content-hash keys the summarizer cache
(`_CACHE_VERSION` v4→v5); `ontology.yaml` is excluded from extraction but walked into the commit.
Hardcoded `_SYSTEM_PROMPT` / `ENTITY_KINDS` / `RELATIONSHIP_KINDS` remain the floor. Guard test:
the committed YAML rebuilds `_SYSTEM_PROMPT` byte-for-byte.

### Phase 2 — Policy defaults feed `ScoringConfig`
The numeric tables (`AUTHORITY_TIERS`, `EDGE_WEIGHTS`, `CENTRALITY_KINDS`, the two defaults) become
ontology-sourced *defaults*, with scoring.py's tables as the floor and config/env still overriding.

- **Slice 2.1 — `Ontology.policy_defaults()`** (pure): build `{authority_tiers, edge_weights
  (from inline edge `weight`), centrality_kinds (from inline `centrality: true`), authority_default,
  edge_weight_default}` from the loaded ontology. Unit-tested off a fixture.
- **Slice 2.2 — `ScoringConfig.resolve(…, ontology_defaults=None)`**: overlay between floor and
  `section`; allow `centrality_kinds` to be ontology-sourced (today it's hardcoded in `resolve`).
  Tests: precedence — ontology overrides floor; config overrides ontology; env overrides config.
- **Slice 2.3 — wire the loader**: `config_store` (or `agent_cli`) loads `ontology.yaml` policy at
  config-resolution time and passes it to `resolve`. Needs the portfolio/repo root (already known).
- **Slice 2.4 — anti-drift guard**: assert `Ontology.policy_defaults()` for the committed file
  equals scoring.py's hardcoded tables (the YAML floor ≡ the code floor), mirroring P1's guard.
- Migration: re-ingest (scores are materialized at ingest; ADR-0008).

### Phase 3 — Projection replaces the hardcoded classifiers + concept migration
The most mechanical, the most test surface. Extension tuples and `classify_source` heuristics
become data; concept grounding moves from `ontology.toml` to the `ontology.yaml` `concepts:` block.

- **Slice 3.1 — `Ontology.projection()` / `.concepts()`** (pure): parse the `projection:` and
  `concepts:` blocks into typed structures (`ConceptSpec` reused from `concepts.py`).
- **Slice 3.2 — projection into `cfg`**: `ScoringConfig` carries `code_ext`/`iac_ext`/`ops_ext`
  and a `tier_globs` map; `classify_source` consults `cfg` instead of module constants + the
  if-ladder, **preserving the exact resolution order** (roles → projection tiers → ext → default).
  `source_kinds.py` keeps its tuples as the floor; `is_code_path`/`is_ops_path` take the ext set
  from `cfg` where they're on the classification path. Sweep the call sites that use them without
  a `cfg` (e.g. `concepts.py`) — the documented risk.
- **Slice 3.3 — concept migration**: extend the `ontology.py` loader to surface `concepts:`;
  `concepts.load_ontology` reads YAML (YAML wins; `ontology.toml` still honored for transition,
  then deprecated). Update the `ontology.toml → CONTEXT` special-case to `ontology.yaml`.
- **Slice 3.4 — anti-drift guard**: assert the committed projection reproduces *every* current
  `classify_source` outcome and the `source_kinds` tuples (parity table), + concept grounding from
  YAML matches the prior TOML behaviour.
- Migration: re-ingest; move concept entries `ontology.toml` → `ontology.yaml`.

## 6. Migration

Each phase that changes materialized values needs a **re-ingest** (`rm -rf .context-kernel &&
ck ingest`, per ADR-0008). Phase 1 already forced one cold extraction pass (cache v5 + ontology
hash). Phase 2 re-materialises confidence/weights; Phase 3 re-materialises tiers + remaps concept
sources. Floors are additive — a portfolio with no `ontology.yaml` keeps working at every phase.

**Operational caveat (carried from Phase 1):** `ontology.yaml` is committed at the model-time repo
root, so it's loaded when model-time is the ingest root. The documented portfolio dogfood uses
`--portfolio ~/Code`, where the loader looks for `~/Code/ontology.yaml`. For portfolio-wide use the
file must live there, **or** the Phase 2 loader must merge a portfolio-root ontology with per-repo
ones (precedence: per-repo overlays portfolio). Pick one when wiring Slice 2.3.

## 7. Risks / open implementation details

- **`classify_source` order parity (P3)** — the single highest-risk item: the if-ladder's order is
  load-bearing (ADR before code-ext; code before ops). Encode order explicitly; the guard test must
  cover every branch, not a sample.
- **`is_code_path`/`is_ops_path` call-site sweep (P3)** — used outside the `cfg` path (e.g.
  `concepts.py`, ingester walk). Decide: thread `cfg`, or keep the floor tuples for non-scoring
  callers and only data-drive the classification path. Avoid two divergent ext sets.
- **`centrality_kinds` override (P2)** — `ScoringConfig.resolve` currently hardcodes
  `centrality_kinds=CENTRALITY_KINDS` (no config/env override exists). Sourcing it from the ontology
  is new surface; confirm nothing depends on it being immutable.
- **Concept dual-format window (P3)** — supporting `ontology.toml` *and* `ontology.yaml` `concepts:`
  during transition risks two sources of truth; keep the window short and YAML-wins, with a one-shot
  deprecation note in the log.
- **Portfolio vs repo placement** — see §6; unresolved, decided at Slice 2.3.
- **Advisory-kind sprawl** — semantic posture retains unknown kinds (by design). Watch for the LLM
  inventing near-duplicate edge kinds that dilute the weight table; the confidence pass mitigates,
  but a periodic "kinds observed but not declared" report (cheap, off the graph) would catch drift.

## 8. Definition of done

- Phases 1–3 merged; full suite green; ADR-0024 flipped Proposed → Accepted.
- All three hardcoded tables (prompt/kinds, scoring numbers, projection rules) are *derived* from
  `ontology.yaml`, each with a passing anti-drift guard equating the YAML to the code floor.
- A real `ck ingest` with an edited `ontology.yaml` (e.g. a new semantic edge kind + weight)
  produces the new kind in the graph and re-materialises affected `AGENTS.md` files — no manual
  sync, no stale serve.
- A no-`ontology.yaml` portfolio still ingests identically to pre-FEAT02 (floors hold).
- Portfolio-placement decision recorded; the `CK_SCORING_*` sweep path confirmed still
  commit-free for the eval harness.

## 9. Task tracking

Phases gate each other (2 depends on the P1 loader; 3 depends on the P2 resolution seam).
Suggested PR cadence: Phase 1 (done) → `2.1+2.2` → `2.3+2.4` → `3.1+3.2` → `3.3+3.4`.

- [x] **P1 · Vocabulary → prompt + validation** — `32e581e`
  - [x] `ontology.yaml` (vocabulary + policy/projection blocks loaded-not-authoritative)
  - [x] `ontology.py` loader; `summarizer` derives prompt/kinds/cache; `_CACHE_VERSION` v4→v5
  - [x] `is_ontology_file` extraction exclusion; `agent_cli` injects ontology
  - [x] guard: committed YAML rebuilds `_SYSTEM_PROMPT` byte-for-byte; +13 tests, suite 524 green
- [ ] **P2 · Policy defaults → `ScoringConfig`**
  - [ ] 2.1 `Ontology.policy_defaults()` (pure)
  - [ ] 2.2 `resolve(…, ontology_defaults=…)` overlay; `centrality_kinds` ontology-sourced
  - [ ] 2.3 loader wiring (resolves the portfolio-vs-repo placement)
  - [ ] 2.4 anti-drift guard: `policy_defaults()` ≡ scoring.py floor
- [ ] **P3 · Projection + concept migration**
  - [ ] 3.1 `Ontology.projection()` / `.concepts()` (pure)
  - [ ] 3.2 `classify_source` reads `cfg` projection, order-parity preserved; `source_kinds` floor
  - [ ] 3.3 concepts from `ontology.yaml` (YAML wins, TOML transitional); `CONTEXT` special-case
  - [ ] 3.4 anti-drift guard: projection parity table + concept-grounding parity
- [ ] **P4 · Close-out**
  - [ ] re-ingest shows ontology-driven kinds/scores end-to-end; ADR-0024 → Accepted
