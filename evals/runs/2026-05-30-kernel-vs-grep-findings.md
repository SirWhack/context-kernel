# Kernel-vs-grep eval — findings (2026-05-30)

First end-to-end evaluation of the Context Kernel MCP against a plain grep baseline, run as
headless Claude Code (sonnet) sessions over real third-party repos. The campaign's lasting
value was **diagnostic**: it surfaced two production defects (fixed) and pinpointed the
kernel's core unrealized capability — cross-altitude (doc↔code) linking.

## Method

- **Harness** (`evals/harness/run_eval.py`): two headless `claude -p --model sonnet` arms
  answer the same numbered question battery for one repo.
  - **kernel** arm — only `mcp__ck__find` / `mcp__ck__overview` / `Read` via a per-repo stdio
    `ck mcp` (the connected MCP is the cloud worker = wrong graph).
  - **grep** arm — only `Grep` / `Glob` / `Read` / `Bash`.
  - Strict tool isolation (escape hatches like `Workflow`/`Task` hard-denied — without it the
    grep arm orchestrated hidden sub-agents and was no baseline at all).
- **Scoring** (`scripts/h2_eval.py`): COST (tool calls/tokens), HALLUCINATION (claimed paths
  that don't resolve), RECALL (gold files named), **GROUNDED** (gold files actually opened —
  memory-proof), **RUBRIC** (key-fact answer correctness, knowledge round).
- **Two validity traps handled:** tool isolation (above); and *memorized public repos* — the
  prompt forbids citing un-opened files and the GROUNDED axis only credits files actually
  read, so an arm can't "answer" a famous repo from training.

## Results

**Location battery** ("name the files for X" — grep's home turf):

| repo | kernel | grep | verdict |
|---|---|---|---|
| fastapi-template (142 files) | 13/19 @ 40 calls | 15/19 @ 22 | grep wins |
| open-webui (2.8k entities) — before find-fix | 12/15 @ **47** | 15/15 @ 26 | grep wins big |
| open-webui — after find-fix | 13/15 @ 32 | 14/15 @ 32 | **parity** |

**Knowledge / synthesis battery** (rubric-scored answer correctness, no greppable anchor):

| repo | kernel | grep |
|---|---|---|
| open-webui | **30/30 facts** @ 19–23 calls | 30/30 facts @ 21–31 |

Tied on correctness, kernel modestly more efficient. Both near-perfect partly because the
repo is memorized — the rubric measures whether the *answer* is right, and the model already
knows open-webui.

**What the final eval (knowledge round re-run *after* the edge fix) taught us — the key
result.** We re-ran the identical knowledge battery on the now-connected graph (1,220 edges
vs 96). The score **did not change**: kernel 30/30, grep 30/30; kernel 23 calls vs the 19 of
the pre-fix run — within session-to-session noise. **Wiring up 1,126 code↔code import edges
produced no measurable eval improvement.** That non-result is the most informative outcome of
the whole campaign:
- The graph fix was *necessary but not sufficient*. `find`'s proximity rerank now has edges to
  use, but it only **reorders** the vector top-k — it never **expands** to pull in a neighbor
  the query missed, so connecting the code half changed almost nothing an agent sees.
- The lever that *would* move the needle isn't code↔code; it's **doc↔code + traversal**. A
  question like "why is the vector layer built this way / what decision governs it" can only
  beat grep if the graph can hop from `VectorDBBase` to the *decision that motivated it* — and
  that edge doesn't exist (see next section). The flat eval result, after a 12× edge increase,
  is the empirical proof that the remaining value is locked behind cross-altitude linking, not
  more code structure.
- Corollary on method: single sonnet runs are noisy (kernel 19 vs 23 calls across two
  identical configs). Future regression should average ≥3 runs/arm before reading small deltas.

**Headline:** on a memorized corpus the kernel is competitive but not dominant. It is not
*better at locating* (grep excels) and only marginally more efficient at *synthesis*. The
reason is structural — see below.

## Defects found and fixed

1. **`find()` scope handling** (commit `e5feeaf`, +10 tests). Scoped queries silently
   returned "No results found": `search_similar` matched `chunk.scope` by exact string, but
   chunks are keyed portfolio-relative (`backend/open_webui/routers`); a repo-name or
   absolute scope never matched, and the empty read as "nothing relevant." The agent burned
   ~10 calls before dropping scope. Fixed: normalize scope (absolute/repo-name → relative),
   prefix-match (a scope = its subtree), and fall back to unscoped instead of silent-empty.
   Took open-webui from a 47-vs-26-call blowout to 32-vs-32 parity.

2. **Edgeless graph / dependency resolution** (commit `ed23cc7`, +4 tests). The "knowledge
   graph" was **95% isolated nodes** (open-webui: 96 edges / 2821 entities, only 3 `imports`)
   despite handlers emitting `imports`/`inherits` (ADR-0021 first-class edges). Cause: an
   import target is a dotted path (`open_webui.retrieval.vector.main.VectorDBBase`) and
   `normalize()` folds the whole path into one token-blob that never matches a bare entity
   name, so the resolver dropped every internal import. Fixed: resolve a dotted target by its
   imported **symbol** (last segment) then **module** (penultimate), keeping ADR-0017's
   "never guess an ambiguous base." Result: **edges 96→1220, imports 3→1126, connected
   4.8%→25%**; real hubs surface (`db`, `UserModel`, `VectorDBBase`, `get_verified_user`).
   NB: `find`'s proximity rerank (1-hop adjacency to top hits) was *inert* before this and is
   live now — but it only reorders the vector top-k; it does not yet *expand* to pull in
   neighbors the vector search missed.

## The core unrealized capability: doc↔code linking

After the import fix the graph connects **code↔code** but still not **doc↔code**:

```
142 doc concepts · 0 merged with code · 1 doc↔code edge · 18/142 doc nodes touch any edge
```

**Why:** doc entities are prose concepts (`"Advanced Vector Database Support"`, a `decision`),
code entities are symbols (`VectorDBBase`). They share **zero** names, so name-merge
(ADR-0017) can't bridge them, and the LLM extractor emits ~0 cross edges. The two altitudes
sit in one vector space but nothing connects them.

This is the kernel's actual differentiator over grep — *"this code realizes ADR-X / is
governed by this invariant"* — and it is effectively **not built**. It is also why the eval
shows parity: with no cross-altitude edges and no traversal, `find` is semantic search and
`overview` is a text blurb, a feature set grep-with-good-names matches.

**Prototype** (`scripts/cross_altitude_link.py`) — a naive embedding cosine doc→code linker is
**too noisy to ship**:
- The single highest-similarity pair is a false positive:
  `[constraint] "Role-Based Access Control (RBAC)"` → `OllamaModel` / `fetch_ollama_models`
  (cosine **0.74**, unrelated). Threshold tuning can't fix a wrong top-1.
- Some links are right (`"Ollama server reachability…"` → `get_ollama_url`; `"Enterprise
  Authentication"` → `scim`), but precision overall is poor.

**Two requirements a real linker must meet** (design notes, not yet built):
1. **A stronger signal than raw cosine** — e.g. embedding-candidate → **LLM-confirm**
   ("does this code realize this concept? y/n"), or mutual nearest-neighbor + **scope-level**
   linking (concept → subsystem, not a random function).
2. **A corpus whose docs describe its code.** open-webui's docs are governance/security prose
   (`"CVE Program REJECT request"`, `"Code of Conduct"`) with no code referent — any link is
   wrong by construction. **model-time itself** (ADRs / THEORY / reference docs written about
   the code, plus an existing `realizes` vocabulary and `ontology.toml`) is the right corpus
   to both build and measure against.

## Open work (deferred)

- Build the doc↔code linker with LLM confirmation, validated on model-time.
- Add neighbor **expansion** to `find` (traversal, not just proximity rerank) to expose the
  now-connected graph at query time.
- Re-run these batteries as regression once the linker lands. Harness + scorer are reusable;
  transcripts live (gitignored) under `evals/runs/sessions/`.

## Artifacts

- Harness: `evals/harness/` (runner, README, `tasks/*.json` with gold + rubric).
- Scorer: `scripts/h2_eval.py` (COST/HALLUCINATION/RECALL/GROUNDED/RUBRIC, ontology-optional).
- Graph oracles: `scripts/scoring_distribution.py`, `scripts/verify_graph.py`,
  `scripts/cross_altitude_link.py` (linker prototype / cross-altitude probe).
