# Eval run — first foreign-corpus observational baseline

**Date:** 2026-05-30
**Corpus:** `full-stack-fastapi-template` @ `38302d7` (upstream clone; `release-notes.md` changelog excluded)
**graph_commit / source-tree hash:** `29aba8449b9ae1fd6139337e040ebcb7f4159f2fe43ed3d455fe8d2fbd0428e0`
**Models:** summarizer `deepseek-v4-flash` (api.deepseek.com), embedder `@cf/qwen/qwen3-embedding-0.6b` (Cloudflare Workers AI)
**Pipeline build:** `main` @ `88f228b` (scoring mechanism #4/#6 merged)

This is the **first run of the real pipeline against a third-party corpus** (EVALS.md
"observational baseline"). No gold set exists for this repo, so the oracles are
structural (graph density, scoring distributions) + spot-checked `find`, not
precision/recall. It is the regression anchor: a later build is a regression iff these
numbers move on this fixed corpus.

## Ingest metrics

| Metric | Value |
|---|---|
| Files processed | 200 |
| Entities | 701 |
| Relationships | 56 |
| Wall clock | 29.3 s |
| Chat calls (DeepSeek) | 128 (95 cache-miss) |
| Embed calls (Cloudflare) | 41 |
| Chat input / output tokens | 321,439 / 27,253 |
| Prompt-cache hit rate | 39.3% |
| **Estimated cost** | **$0.0353** |
| Contradictions flagged | 0 |

## Scoring distributions (the #6 oracle)

Per-class confidence / centrality:

| Class | n | source_tier (med) | confidence (med) | centrality>0 | centrality max |
|---|---|---|---|---|---|
| code | 500 | 0.850 | 0.850 | 6 | 0.500 |
| doc | 199 | 0.300 | 0.300 | 16 | 1.000 |
| code+doc | 2 | 0.850 | 0.850 | 1 | 0.500 |

source_tier histogram: `0.20 → 88` (EPHEMERAL: README/CONTRIBUTING), `0.30 → 111`
(catch-all: deployment.md, development.md), `0.85 → 502` (CODE).

Edge-kind histogram: realizes 18, governed-by 12, motivates 9, inherits 8, imports 4,
addresses 3, supersedes 2.

## Findings

1. **Authority discriminates crisply, but is calibrated to model-time's own doc
   taxonomy.** Code lands at 0.85, docs at 0.2–0.3. But `classify_source` recognizes
   none of this repo's architectural docs — `deployment.md` and `development.md` are
   genuine references yet fall to the 0.30 prose catch-all, and README/CONTRIBUTING hit
   the 0.20 EPHEMERAL floor. On a foreign repo, virtually all prose is under-trusted.
   The catch-all-leans-low design (ADR-0015) is working as intended; the gap is that the
   tier table keys on *our* filenames (THEORY/ARCHITECTURE/ADR/CONTEXT), not portable
   doc roles. **Open question:** should authority infer tier from doc *content/role*
   rather than filename, or is per-repo tier config the answer?

2. **Drift produced zero signal (0/56 edges, 0 entities).** By construction drift needs a
   code referent that churned *after* a doc's claim commit; a freshly cloned, synchronized
   template has none, and only 13 cross-altitude edges exist to carry it at all. This
   **confirms EVALS.md**: drift cannot be exercised on a pristine corpus — the real drift
   eval *requires* the planted-defect corpus (a doc claim + a subsequent referent rewrite).

3. **Centrality's top nodes are doc concepts, not code.** The cen=1.0 leaders
   (Docker Compose deployment, Mailcatcher, compose.yml, .env config) are all docs at
   conf=0.30 — intra-doc `realizes` edges inflate doc-concept in-degree above real code
   anchors (crud, models, UserBase at cen=0.50). The central-but-low-confidence combo is
   **correctly surfaced** (exactly the #8 health-rollup signal ADR-0015 said to keep
   visible), but it means raw centrality ≠ code importance on a doc-heavy ingest.

4. **Edge sparsity is the limiting factor.** 56 relationships / 701 entities; 13
   cross-altitude. Both drift and code-centrality are starved by how few doc↔code
   semantic edges the extractor mints. This is the lever to watch.

5. **`find` retrieval is strong.** Top hit for each spot-check query was the exact file a
   human would pick: JWT→`core/security.py`, CRUD→`crud.py`, client-gen→`sdk.gen.ts`
   scope. The confidence/proximity rerank did not distort obvious matches.

## What this run does NOT prove

Discrimination (rank correlation vs a gold ordering), drift calibration, and knob
sensitivity — all three need a **planted-defect gold corpus** (EVALS.md issue-#6 case
study, step 1). This run motivates building it: items 2–4 above can only be measured
against planted churn + planted lexicon-inflation hubs, not a clean upstream template.

## Follow-up: repo roles applied (ADR-0022)

Finding #1 (authority calibrated to model-time's taxonomy) was fixed by **repo-local role
assignment** — a 6-line `[ingester.scoring.roles]` map declaring `README → OVERVIEW`,
`deployment/development → OPS`, component READMEs → `REFERENCE`. Re-ingest on the same
corpus (cost $0.005, summarizer cache hit):

| | Baseline (heuristic only) | With roles |
|---|---|---|
| source_tier values | degenerate: 0.20 / 0.30 / 0.85 | graded: 0.50 / 0.60 / 0.80 / 0.85 |
| doc confidence (median) | 0.300 | 0.600 |
| all-entity mean confidence | 0.681 | **0.807** |
| README's 42 entities | 0.20 (floor) | 0.85 (OVERVIEW, capped at code) |
| central ops-doc hubs | cen 1.0 @ conf 0.30 | cen 1.0 @ conf 0.60 |

**`find` interaction (the design finding).** Capping `OVERVIEW` at `CODE` (0.85) was chosen
after the eval showed the doc-vs-code ordering is a *similarity* story, not an authority one:
a README chunk out-similars a code chunk for NL queries (0.75 vs 0.61 on "JWT verification"),
and the original code-first results were an artifact of flooring README at 0.2. Probing 5
query intents showed `find` already routes correctly by similarity (symbol queries →
code-first on their own; concept/ops/how-to → doc-first, which is correct), and returns a
**mixed packet** with the relevant code entity reliably in the top-k. A kind-aware reranker
was therefore rejected as YAGNI. See ADR-0022.
