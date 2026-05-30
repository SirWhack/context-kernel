# FEAT01 — Confidence / Relevance / Drift scoring system

Implementation plan for GitHub issue #6. Implements **ADR-0015** (axes), **ADR-0019**
(materialize-at-ingest / compose-at-query), **ADR-0020** (drift), **ADR-0021** (edge
families). Read those first — this doc is *how*, they are *why*.

> Status: **mechanism complete** (Slices 0–6 merged, 358 tests green). Design locked at
> `9196093`. Remaining: the planted-corpus `CK_SCORING_*` sweep (the deferred "large eval",
> batched with #4) and a real `ck ingest` confidence-spread check on this repo.

## 1. What we're building

A per-record trust signal that makes `find` and `summarize_scope` prefer current,
authoritative, structurally-central claims over stale, ephemeral, peripheral ones — and that
feeds the health rollup (#8).

- **Confidence** (intrinsic, ingest-time, stored): `authority × (1 − drift)`, with
  `centrality` stored beside it.
- **Drift** (the centerpiece): git-measured structural divergence on edges, directional,
  no clock.
- **Relevance** (query-time, never stored): `similarity × confidence × proximity`.

## 2. Module map

| Module | Role | New / changed |
|---|---|---|
| `context_kernel/scoring.py` | **NEW.** Pure, total, no I/O. Owns every table + formula. | new |
| `context_kernel/change_detection.py` | git churn (numstat) + node last-commit. The *only* git I/O. | changed |
| `context_kernel/graph/protocol.py` | `Entity` += `source_tier, centrality, confidence`; `Relationship` += `weight, drift` | changed |
| `context_kernel/graph/lightrag_adapter.py` | round-trip the new fields in `state.json` | changed |
| `context_kernel/ingester/summarizer.py` | rename semantic `implements`→`realizes` (ADR-0021) | changed |
| `context_kernel/ingester/__init__.py` | post-resolution scoring pass: authority, centrality, edge weight, drift, confidence | changed |
| `context_kernel/orientation_server/tools.py` | `find` composes relevance via `scoring` | changed |
| `context_kernel/graph/protocol.py` (`SearchResult`) | += `entity_id`, `confidence` so `find` can compose | changed |
| `context_kernel/config_store.py` | `[ingester.scoring]` knobs + `CK_SCORING_*` env resolution | changed |

**Invariant (PoSD / ADR-0019):** `scoring.py` owns all tables and formulas; `ingest` and
`find` orchestrate and *call* it — neither inlines a tier number or a formula. `change_detection`
owns all git I/O; `scoring` never touches the filesystem.

## 3. The `scoring.py` interface (pure, total, never raises)

```python
# Tables (resolved: hardcoded default → config [ingester.scoring] → CK_SCORING_* env)
AUTHORITY_TIERS: dict[str, float]   # THEORY 1.0, ARCHITECTURE .95, ADR .9, CODE .85, CONTEXT .8, REFERENCE .8, SPEC .5, EPHEMERAL .2
AUTHORITY_DEFAULT = 0.3             # unmatched prose, lean low
EDGE_WEIGHTS: dict[str, float]      # governed-by .95, implements/inherits/realizes .9, supersedes .85, addresses .7, motivates .5, imports .3
CENTRALITY_KINDS = {"implements", "inherits", "realizes", "governed-by"}

def authority(sources: tuple[str, ...]) -> float          # max tier over a node's source paths; default 0.3
def edge_weight(kind: str) -> float                       # static f(kind); unknown → 0.5
def centrality(entity_ids, relationships) -> dict[str, float]
    # distinct-source in-degree over CENTRALITY_KINDS, normalized to [0,1] by graph max

def edge_drift(lines_changed: int, referent_size: int) -> float   # min(1, lines/size); size 0 → 0
def node_drift(edges: list[tuple[float, float]]) -> float          # edge-weighted mean of (drift, weight); no edges → 0
def confidence(authority: float, node_drift: float) -> float       # authority × (1 − node_drift)

def proximity(candidate_id, seed_ids, adjacency) -> float          # 1 + max edge_weight to a 1-hop seed, else 1
def find_score(similarity, confidence, proximity) -> float         # similarity × confidence × proximity
def ranking_weight(confidence, centrality) -> float                # confidence × centrality  (summarize ordering)
```

Errors-out-of-existence (ADR-0019 §10 lens): missing data never raises — no sources → default
authority; size 0 → drift 0; no edges → node_drift 0; unknown kind → mid weight.

## 4. Drift computation (the hard part — ADR-0020)

Lives in `ingest()`, orchestrating `change_detection` (git) + `scoring` (formula). Per edge:

1. Classify ends: **referent** = the described/depended-upon (code is always the referent vs a
   doc); **claimant** = the describer/dependent. v1 = doc↔code edges only.
2. `since = change_detection.commit_of(claimant.source)`  — claimant's last commit.
3. `lines = change_detection.churn(referent.source, since=since, until="HEAD")` — numstat lines
   changed to the referent in that interval.
4. `edge.drift = scoring.edge_drift(lines, change_detection.size(referent.source))` — loaded on
   the claimant side; the referent's own edges are unaffected.
5. `node_drift(doc) = scoring.node_drift([(e.drift, e.weight) for e in doc's claimant edges])`.

`change_detection` additions (the only git I/O):
```python
def commit_of(path: str) -> str | None                       # git log -1 --format=%H -- path ; None if untracked
def churn(path: str, since: str | None, until: str = "HEAD") -> int   # sum |added|+|removed|, numstat; 0 if since is None
def size(path: str) -> int                                   # current line count (cached)
```
All cached per (path, …) like the ADR-0008 source-hash cache; all return safe defaults on git
failure (untracked / not a repo) so drift falls to 0 — never raises.

## 5. Build sequence (vertical slices, each shippable + tested)

Drift is the heaviest piece; it is isolated in Slice 3 *after* the scaffold exists, so the
system delivers a working confidence signal before drift lands.

### Slice 0 — Taxonomy rename (independent prep) — task #7
- `summarizer.py`: `RELATIONSHIP_KINDS` and prompt `implements`→`realizes` (semantic sense).
- Tests: extractor emits `realizes`; structural `implements` from handlers untouched.
- Ships alone; no dependency on the rest.

### Slice 1 — Schema + serialization — task #2
- `protocol.py`: `Entity` += `source_tier: float = 0.0`, `centrality: float = 0.0`,
  `confidence: float = 1.0`; `Relationship` += `weight: float = 0.5`, `drift: float = 0.0`.
  Additive, neutral defaults (unscored = neutral).
- `lightrag_adapter.py`: `_load`/`_save` round-trip the new fields (back-compat: `.get(...)` with defaults).
- Tests: round-trip; old `state.json` without the fields loads with defaults.

### Slice 2 — `scoring.py` + knobs (pure, fully unit-testable) — tasks #1, (config part of #4)
- Implement every function in §3; `config_store` knob resolution (`CK_SCORING_*` → config → default).
- `centrality`, `authority`, `edge_weight`, `confidence`, `proximity`, `find_score`, `ranking_weight`.
- Drift *formula* (`edge_drift`, `node_drift`) here; drift *magnitude* (git) is Slice 3.
- Tests: table-driven per function — authority precedence/catch-all, distinct-source centrality
  (incl. lexicon-inflation case), proximity boost-not-gate, env-override precedence.

### Slice 3 — Drift via git churn — task #3 (the centerpiece)
- `change_detection.py`: `commit_of`, `churn`, `size` (§4), cached, safe defaults.
- `ingest()`: post-resolution, classify referent/claimant for doc↔code edges, compute per-edge
  `drift`, aggregate `node_drift`. Store on `Relationship.drift`.
- Tests: temp git repo fixture — doc references code, code churns → edge drift on doc side;
  doc edited → drift resets; untracked → drift 0; stable code + doc edit → code drift 0.

### Slice 4 — Ingest scoring pass wires it together — task #4
- `ingest()`: after resolution + drift, set `Entity.source_tier` (max authority over sources),
  `Entity.centrality`, `Entity.confidence = scoring.confidence(authority, node_drift)`;
  `Relationship.weight = scoring.edge_weight(kind)`.
- `summarize_scope` ordering: sort entities by `scoring.ranking_weight(confidence, centrality)`.
- Tests: end-to-end ingest with `_FakeStore` — stale-referent doc gets low confidence; central
  code ranks first; HANDOFF-class node near-zero confidence.

### Slice 5 — Relevance in `find` — task #5
- `SearchResult` += `entity_id`, `confidence`; `search_similar` populates them (stays a pure
  similarity mechanism — no policy).
- `tools.find`: pick top-3 seeds, compute `proximity` (1-hop, via `store.get_neighbors`), rank by
  `scoring.find_score`. `CK_SCORING_CENTRALITY_IN_FIND` off by default.
- Tests: confidence-weighted rerank; proximity lifts a seed-adjacent hit; unconnected strong hit
  not zeroed.

### Slice 6 — Eval hooks — ties to EVALS.md
- A drift/confidence eval: planted-defect corpus (stale-referent docs, low-authority hubs) scored
  against the rollup; sweep `CK_SCORING_*`. Records `(knobs, corpus hash, model)`.
- Adds the "confidence/drift" and "documentation gap" rows' harnesses to EVALS.md.

## 6. Migration

Confidence/drift are materialized at ingest, so a scoring change needs a **re-ingest**
(`rm -rf .context-kernel && ck ingest`), per ADR-0008. The `implements`→`realizes` rename
(Slice 0) also requires a re-ingest to remap stored edges. Schema fields are additive — old
`state.json` loads with neutral defaults until the next ingest.

## 7. Risks / open implementation details

- **Centrality timing** — needs the full resolved relationship set; compute after resolution,
  before Entity construction. Confirmed feasible (resolution is global per ingest).
- **Drift edge classification** — v1 only handles doc↔code (code = referent). Code↔code
  dependency drift (dependency = referent) is the documented fast-follow; until then code nodes
  carry drift 0.
- **Context-cache churn (ADR-0016)** — adding a code entity invalidates all doc-chunk caches
  (context is the known-code list), so a code change already re-extracts dependent docs. Good for
  drift correctness; watch ingest cost on large code changes.
- **`git log` cost** — per-file `commit_of`/`churn` over many files; cache aggressively, consider
  a single `git log --numstat` sweep if per-file calls dominate ingest time.
- **Merged nodes (ADR-0017)** — a doc mention that merges *into* a code node creates no doc↔code
  edge (it's absorption); drift only flows on edges that survive resolution as distinct
  doc-concept↔code links (the KnowledgeStore↔ADR case). Note in tests.

## 8. Definition of done

- All slices merged; full suite green.
- A real `ck ingest` on this repo produces non-trivial confidence spread (THEORY invariants high,
  ephemeral notes low) and non-zero drift on docs whose referents churned.
- `find` results visibly reranked by confidence + proximity, not similarity alone.
- Slice 6 eval baseline recorded so future scoring changes are measurable regressions.
- Issue #6 closed; #8 (health) unblocked to read stored axes.

## 9. Task tracking

Slices map 1:1 to tasks. Two refinements folded in: the config-knob layer is an explicit item
in T3 (not a footnote), and the `summarize_scope` ranking change is broken out in T5 (only path
that alters materialized output — needs a golden-file test).

Suggested PR cadence: `T1` solo → `T2+T3` → `T4` → `T5+T6` → `T7`. Five PRs.

- [x] **T0 · Commit FEAT01.md** — `b305193`
- [x] **T1 · Slice 0 — rename `implements`→`realizes`** — `1f7bffc`
  - [x] `summarizer.py`: `RELATIONSHIP_KINDS` + `_SYSTEM_PROMPT`; `_CACHE_VERSION` v3→v4
  - [x] tests: extractor emits `realizes`; structural `implements` untouched
- [x] **T2 · Slice 1 — schema + serialization** — `6c0e895`
  - [x] `protocol.py`: `Entity += source_tier, centrality, confidence`; `Relationship += weight, drift`; `SearchResult += entity_id, confidence`
  - [x] `lightrag_adapter.py`: round-trip via `.get(..., default)`; legacy `state.json` loads neutral
- [x] **T3 · Slice 2 — `scoring.py` (pure) + config knobs** — `e843ee0`
  - [x] `scoring.py`: all §3 functions + tables
  - [x] `config_store.py`: `[ingester.scoring]` + `CK_SCORING_*` resolution *(refinement #1)*
  - [x] tests: 60 table-driven — authority catch-all, lexicon-inflation centrality, proximity boost-not-gate, env precedence
- [x] **T4 · Slice 3 — drift via git churn** (centerpiece) — `d4698ac`
  - [x] `change_detection.py`: `commit_of`, `churn`, `size` — cached, safe defaults
  - [x] tests: temp-git-repo — code churn→doc drift; doc edit→reset; untracked→0; stable code→0
- [x] **T5 · Slice 3b/4 — ingest scoring pass** — `807d78b`
  - [x] `ingest()`: referent/claimant drift, `source_tier`, `centrality`, `confidence`, `Relationship.weight`
  - [x] `summarize_scope` sort by `ranking_weight` *(refinement #2)*
  - [x] tests: e2e over real git repo — stale doc < authority, stable doc full, code→2 docs central
- [x] **T6 · Slice 5 — relevance in `find`** — `fed5f26`
  - [x] `search_similar` populates `entity_id/confidence`
  - [x] `tools.rank_by_relevance`: top-3 seeds, 1-hop proximity, rank by `find_score`; centrality off by default
  - [x] tests: confidence rerank; proximity lift; unconnected strong hit not zeroed; centrality on/off
- [x] **T7 · Slice 6 — eval hooks** *(mechanism + harness spec; sweep deferred)*
  - [x] confidence/drift + documentation-gap rows + case study in EVALS.md; knob defaults resolved
  - [ ] planted-defect corpus + `CK_SCORING_*` sweep — **deferred to the batched large eval (#4 + #6)**
- [ ] **T8 · Close-out**
  - [x] full suite green (358)
  - [ ] real `ck ingest` on this repo shows confidence spread + non-zero drift *(needs LLM servers — manual)*
  - [ ] close #6 (comment: mechanism done, sweep pending); unblock #8
