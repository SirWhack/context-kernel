# Research: Hierarchical scope summarization & graph-aware materialization

**Date:** 2026-06-09
**Status:** Research notes — input to future ADRs (not a decision)
**Origin:** [REVIEW-FABLE.md](../../REVIEW-FABLE.md) Part I, priorities 1, 2, and 4
**Companion docs:** [ontology & entity resolution](./2026-06-09-ontology-and-entity-resolution.md),
[design signals / normative layer](./2026-06-09-design-signals-normative-layer.md)

Two features motivated this research pass:

- **Feature A — hierarchical scope summarization.** Today every scope's summary is generated
  independently from its own entities; a parent directory's AGENTS.md does not compose its
  children's. The altitude-composition thesis is asserted but not built.
- **Feature B — graph-aware materialization + importance ranking.** Today the materializer
  renders only the prose summary; the edges (cross-scope dependencies, `realizes`/`governed-by`
  links to ADRs) never deterministically appear in AGENTS.md, and selection of what fits a
  token budget uses `confidence × (1 + centrality)` with no reference-graph importance signal.

All findings below carry primary-source citations; low-confidence claims are flagged.

---

## 1. What the literature says about hierarchical summarization

### 1.1 RAPTOR — recursive summarization works and does not snowball

RAPTOR ([arXiv:2401.18059](https://arxiv.org/abs/2401.18059), ICLR 2024) recursively embeds,
clusters (UMAP + soft GMM, BIC-chosen cluster count), and summarizes text chunks bottom-up.

- Compression per level: mean summary/children ratio **0.28** (~72% compression), average
  summary ≈ 131 tokens.
- Headline result: QuALITY **82.6% vs 62.3%** prior best with GPT-4. Retriever-only deltas are
  modest (+2% over DPR); most of the win comes from *having multi-level abstraction available
  at all* for whole-document questions.
- **The error-compounding fear is measured and small:** a manual audit of 150 summary nodes
  found **4% contained any hallucination, and none propagated to parent layers** or measurably
  affected QA. At 2–4 levels of depth with faithful per-level summarization,
  summaries-of-summaries do not snowball.
- Operational: the **"collapsed tree" beat tree traversal** for retrieval — flatten all levels
  into one pool and retrieve across levels by similarity. The tree is valuable as a *summary
  generator*, not as a *retrieval path*. (This matches the kernel's hybrid corpus design:
  scope summaries and entity descriptions in one vector index, ADR-0012.)

### 1.2 Microsoft GraphRAG — hierarchy compresses hard and retains orientation value

GraphRAG ([arXiv:2404.16130](https://arxiv.org/html/2404.16130v2)) builds hierarchical Leiden
communities and pre-generates a summary at every level; leaf summaries assemble element
summaries **prioritized by node degree** until the token budget, higher levels substitute
child-community summaries.

- Root-level summaries are **2.3–2.6% of corpus tokens** yet win **72%** of comprehensiveness
  comparisons vs vector RAG — high compression at the top of the hierarchy retains most of the
  orientation value, needing 9–43× fewer query tokens.
- The cost problem is indexing (LLM summarization of everything). Microsoft's responses:
  dynamic community selection (−77% query cost,
  [MSR blog 2024-11-15](https://www.microsoft.com/en-us/research/blog/graphrag-improving-global-search-via-dynamic-community-selection/))
  and LazyGraphRAG (defer all summarization to query time; indexing at **0.1%** of full
  GraphRAG cost,
  [MSR blog 2024-11-25](https://www.microsoft.com/en-us/research/blog/lazygraphrag-setting-a-new-standard-for-quality-and-cost/)).
- **LazyGraphRAG's lesson does not transfer to the kernel:** deferring summarization is optimal
  only when an LLM at read time is allowed. The kernel's no-LLM-at-read invariant (THEORY
  invariant 3) plus amortization across many agent reads puts it squarely in the eager regime —
  but borrow Lazy's *cost discipline*: budget summary tokens per level; skip re-summarizing
  scopes whose child-set hash is unchanged.

### 1.3 Code-specific hierarchical summarization (2024–2026)

- Hierarchical repo-level summarization with local LLMs
  ([arXiv:2501.07857](https://arxiv.org/abs/2501.07857), LLM4Code@ICSE 2025): deterministic
  syntax analysis isolates symbols (the kernel's StructuredHandler pattern), LLM summarizes,
  summaries aggregate **function → file → package** bottom-up.
- Repository understanding via hierarchical summarization
  ([ICCSA 2025](https://link.springer.com/chapter/10.1007/978-3-031-97576-9_6)): summaries at
  project/directory/file levels + top-down search; Pass@10 0.89 on industrial issues
  *(numbers from secondary abstract — medium confidence)*.
- **Meta-RAG** ([arXiv:2508.02611](https://arxiv.org/abs/2508.02611), JPMorgan 2025): code
  summaries as the retrieval index compress codebases **79.8%** while reaching **84.67%
  file-level** bug localization on SWE-bench Lite — a compact NL summary layer over code is a
  competitive localization index in its own right.

### 1.4 Cluster-derived vs structure-given trees

RAPTOR clusters because prose has no given structure; GraphRAG derives communities because its
corpus has no given tree. **Code has an authoritative given hierarchy — the directory/scope
tree** — and every successful repo-level system above composes over it. No paper shows
semantic clustering beating native structure for code orientation. Agentless
([arXiv:2407.01489](https://arxiv.org/pdf/2407.01489)) showed the bare directory tree alone is
a top-tier localization signal. Reserve clustering for cross-cutting `views/by-topic` style
projections.

### 1.5 Incremental recomputation

GraphRAG's `update` command re-summarizes only edited communities
([Issue #741](https://github.com/microsoft/graphrag/issues/741)); HIT-Leiden
([arXiv:2601.08554](https://arxiv.org/pdf/2601.08554)) dynamically maintains communities so
only updated ones re-summarize. The directory tree makes this trivial by comparison: **the
dirty set for a change is exactly the ancestor chain of changed files.** The kernel's
content-addressed summarizer cache already provides the no-op property — if a child summary's
text is unchanged, the parent's input hash is unchanged and the parent re-summarization is a
cache hit — *provided parent prompts are built from child summary content (hashes), not from
raw file lists.*

### 1.6 Verifying summaries mechanically

The production mitigation for summary hallucination is decompose-then-verify (Factored
Verification, [arXiv:2310.10627](https://arxiv.org/pdf/2310.10627)). Code has a cheaper
verifier than any prose system: **the deterministic symbol table.** A generated scope summary
that names an entity or path absent from the scope's entity set is mechanically detectable —
reject/regenerate on failure. This extends the kernel's propose-and-confirm posture (ADR-0018)
to summaries.

---

## 2. Importance ranking for code graphs

### 2.1 Aider's repo map — the production recipe (verified against source)

From [repomap.py](https://raw.githubusercontent.com/Aider-AI/aider/main/aider/repomap.py) and
[docs](https://aider.chat/docs/repomap.html):

1. tree-sitter `def`/`ref` tags per file (Pygments lexing backfills refs).
2. NetworkX **MultiDiGraph, files as nodes**; per identifier, edges from referencing files to
   defining files, `weight = mul × sqrt(num_refs)` — sqrt damping stops high-frequency
   identifiers from dominating. Never-referenced definitions get a 0.1 self-edge.
3. Edge multipliers encode "public API beats plumbing": ×10 well-named identifiers
   (snake/camel-case, length ≥ 8), **×0.1 `_private`**, **×0.1 defined in >5 files**
   (ambiguous); session-specific boosts (×10 mentioned in chat, ×50 referencing file in chat)
   via the PageRank personalization vector.
4. File rank is **redistributed across outgoing edges** proportional to weight, accumulating
   into `(file, identifier)` scores — definitions get ranked, not just files.
5. **Budget fitting: binary search over included-tag count**, rendering and counting tokens per
   iteration, 15% tolerance. Default budget **1k tokens**.

The kernel analog: personalization is session-dependent in aider; a pre-materialized AGENTS.md
has no query. The substitute is **scope-local personalization** — when materializing scope S,
place personalization mass on S's files, so ranking is "important *from S's vantage point*."

### 2.2 HippoRAG — two transferable graph refinements

HippoRAG ([arXiv:2405.14831](https://arxiv.org/abs/2405.14831), NeurIPS 2024; HippoRAG 2
[arXiv:2502.14802](https://arxiv.org/pdf/2502.14802)):

- **Node specificity** — reweight by the inverse of how many passages/scopes a node appears in
  (an IDF analog favoring rare, discriminative entities). Kernel use: down-weight entities
  appearing in many scopes so each AGENTS.md surfaces what is *distinctive* about that scope.
  *(Exact formula medium confidence; principle well-supported.)*
- **Synonymy edges** — embedding-similarity edges between entities above a cosine threshold,
  fixing literal-match brittleness. Kernel use: connect a doc's mention of "freshness gate" to
  `freshness_gate.py` when no explicit edge exists. NOTE: this overlaps the rejected
  `semantic_linker` (ADR-0027) — if revisited, it must be a *judged* pass per that ADR's
  closing guidance, not raw cosine.

### 2.3 Evidence quality on centrality measures — honest gaps

- ComponentRank ([ICSE 2003](https://dl.acm.org/doi/abs/10.5555/776816.776819)): PageRank over
  component use-relations matches developer intuition of importance.
- He et al. 2013 ([Math. Probl. Eng.](https://onlinelibrary.wiley.com/doi/10.1155/2013/869356)):
  nine network metrics over class dependency networks correlate with bug proneness; **no single
  dominant metric**.
- **Flagged gap:** there is no published head-to-head showing PageRank beats plain in-degree
  *for selecting code context for LLMs*. Aider's choice is engineering judgment validated by
  adoption, not an ablation. → Make the importance measure a `CK_SCORING_*` knob and A/B it
  (both are cheap to compute at ingest).

Relationship to ADR-0015 centrality: the existing distinct-source in-degree over
doc-linkage kinds answers "what is well-grounded / what is a documentation gap." Reference-graph
PageRank answers "what does the code itself treat as load-bearing." Keep both; they feed
different consumers (health vs materialization selection).

---

## 3. Rendering graph structure into LLM-consumable markdown

Directly applicable to the edge-derived AGENTS.md sections (review priority 1):

- **Format moves accuracy a lot.** "Talk like a Graph"
  ([arXiv:2310.04560](https://arxiv.org/abs/2310.04560), Google): graph-encoder choice moves
  reasoning accuracy **4.8–61.8%** by task; natural-language relation statements with
  meaningful node names beat abstract adjacency formats. KG-LLM-Bench
  ([arXiv:2504.07087](https://arxiv.org/html/2504.07087)): structured JSON/YAML/edge-lists
  cluster near the top, **RDF Turtle and JSON-LD are the worst** (up to 17.5 points absolute
  format effect); subject-grouped formats win aggregation-style questions.
  → Render per-entity blocks with subject-grouped sublists — "depends on: …", "used by: …",
  "documented in: …" — in markdown; never triple dumps or semantic-web serializations.
- **Position effects are real.** Lost in the Middle
  ([arXiv:2307.03172](https://arxiv.org/abs/2307.03172), TACL 2024): U-shaped accuracy
  (75.8% first / 53.8% middle / 63.2% end — middle placement fell *below the closed-book
  baseline*). → Most load-bearing content (scope purpose, invariants, top-ranked entities)
  first; consider end-anchoring critical warnings; never bury invariants mid-file.
  *(Frontier models attenuate but don't eliminate — medium confidence on current magnitude.)*
- **Context rot favors small files.** Chroma report
  ([trychroma.com/research/context-rot](https://www.trychroma.com/research/context-rot), 2025):
  reliability degrades with length across 18 models even on trivial tasks; distractors
  compound; a focused ~300-token prompt beat the same question over a full ~113k context.
  Anthropic's context-engineering guidance
  ([2025-09-29](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)):
  "smallest set of high-signal tokens," markdown-header sectioning, **lightweight identifiers
  (file paths) + just-in-time retrieval** — progressive disclosure over pre-loading.
- **Token budget:** no published hard threshold. Convergent practice: aider's 1k default for a
  whole-repo map; Chroma's degradation curves; Anthropic's minimal-but-sufficient. A per-scope
  file at **~1–3k tokens** is well-supported; >5k increasingly costly. *(Exact cutoff low
  confidence — measure with the eval harness.)* Note the bridge-file multiplier: Claude Code
  auto-loads every CLAUDE.md on the walked path, so nested-scope budgets are additive — budget
  the *path*, not just the file.

---

## 4. Evaluation methodology (prerequisite for both features)

- **The bar to beat is agentic grep, and it's high.** GrepRAG
  ([arXiv:2601.23254](https://arxiv.org/abs/2601.23254)): naive lexical retrieval is comparable
  to graph-based baselines for repo-level completion. A kernel-vs-grep A/B with a weak grep arm
  is a straw man — the H2 eval's agentic-grep arm was the right design; keep it.
- **Localization hit-rate is the cheap, sensitive proxy.** SWE-bench's own analysis
  ([arXiv:2310.06770](https://arxiv.org/pdf/2310.06770)): retrieval, not generation, was the
  dominant bottleneck (1.96% resolved with BM25 vs 4.8% with oracle files). Score
  file/function hit-rate against known answers before running end-to-end agent tasks.
- **Suites to borrow shapes from, not to adopt wholesale:** RepoQA
  ([arXiv:2406.06025](https://arxiv.org/abs/2406.06025)) — find-the-function-from-description,
  closest to "orientation QA"; CodeRAG-Bench
  ([arXiv:2406.14497](https://arxiv.org/html/2406.14497v2)) — retrievers struggle most on
  repo-level tasks, gold context worth +27.4%; Loc-Bench (LocAgent). Public benchmarks carry
  contamination and task-defect risk — SWE-bench Verified showed **59.4% of o3-failed problems
  had material test/spec defects**
  ([OpenAI](https://openai.com/index/why-we-no-longer-evaluate-swe-bench-verified/)).
  → Build a **private, portfolio-specific paired eval** (~50–100 questions across the three
  repos, multiple altitudes).
- **LLM-judge discipline:** position/verbosity/self-enhancement biases are documented
  ([arXiv:2306.05685](https://arxiv.org/abs/2306.05685)); randomize/swap order, reference-guided
  grading, blind the judge to which system produced what, one fixed judge config.
- **Statistics:** pair every question across conditions; paired bootstrap over tasks (10k
  resamples, 95% CIs) ([arXiv:2511.19794](https://www.arxiv.org/pdf/2511.19794)); track tokens,
  tool calls, wall-clock per outcome (the `LLMMetrics` accumulator covers ingest; add the read
  side).

---

## 5. Design implications for the kernel

1. **Use the directory tree as the summary hierarchy** (structure-given, not clustered).
   Compose parent scope summaries from child summaries + parent-local entities, bottom-up.
   Target ~3–4× compression per altitude (RAPTOR 0.28 ratio; GraphRAG 2.3–2.6% roots winning
   72%). Incremental cost = ancestor chain of changed scopes; build parent prompts from child
   summary hashes so the content-addressed cache gives no-ops for free.
2. **Verify summaries against the symbol table** (decompose-then-verify, mechanized): any
   entity/path named in a summary must exist in the scope's entity set; regenerate on failure.
3. **Adopt aider's ranking recipe minus session personalization**: defs/refs →
   sqrt-damped weighted graph → PageRank with scope-local personalization → distribute rank to
   definitions → binary-search the token budget. Keep the `_private` ×0.1 / multi-definer ×0.1
   / well-named boost heuristics. Add HippoRAG-style node specificity so scope files surface
   what is distinctive, not what is ubiquitous.
4. **Render edges subject-grouped in markdown** ("depends on / used by / documented in /
   governed by" per entity or per scope), with file-path pointers for progressive disclosure;
   never RDF-ish dumps. Order sections by importance (invariants and purpose first); budget
   ~1–3k tokens/scope and budget the auto-loaded *path*, not just the file.
5. **PageRank vs in-degree is unproven for context selection** — ship both behind a
   `CK_SCORING_*` knob and let the eval decide.
6. **Build the private paired eval first** (localization hit-rates + blinded paired LLM
   judging + paired bootstrap; strong agentic-grep baseline). Both features above land as
   measurable deltas against it, or they don't land.

## Open questions for the eventual ADRs

- Does hierarchical summarization change the freshness model? (A parent's freshness header
  must hash over child summaries, not just its own scope's sources — extends ADR-0008.)
- Where does scope-local PageRank personalization live — `scoring.py` (pure, fed adjacency) or
  a materializer-side pass? (Tenet: scoring stays no-I/O.)
- Do edge-derived AGENTS.md sections count against the same token budget as the prose summary,
  and who yields when the budget is tight? (Suggest: invariants/dependencies are
  non-negotiable, prose compresses.)
- Synonymy edges re-open ADR-0027's territory — if wanted, they must be judged, not raw cosine.
