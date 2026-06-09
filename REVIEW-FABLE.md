# Review — Context Kernel architecture, theory, and approach

**Date:** 2026-06-09
**Reviewer:** external architecture review ("Fable" session), grounded in a code-level audit of the
repository and a literature survey (GraphRAG 2024–2026, code knowledge graphs, ontology
engineering, docs-for-agents practice).
**Inputs:** THEORY.md, ARCHITECTURE.md, CONTEXT.md, PLAN.md, ADRs 0001–0027, and a full read of
`context_kernel/` (ingester, entity resolver, scoring, graph adapter, materializer, ontology).

This document records the review verbatim-in-substance so it can be grilled, contested, and
mined for ADR candidates. Part I is the architecture review; Part II is the strategic
assessment of the approach itself (positioning vs. Sourcegraph/Potpie, and the proposed
normative/PoSD layer). Citations are as reported by the research pass; low-confidence items are
flagged inline.

---

## Part I — Architecture review

### Overall assessment

The theory is sound and, unusually, the evidence supports its riskiest-looking choices. The
project's discipline — measured ADRs, reversals on evidence (ADR-0027 is exemplary: built,
measured 0/412 recovered, rejected, replaced with deterministic parsing), pure-function seams —
is better than most published systems in this space. The structural weaknesses are not in the
graph's *construction* but in how little of the graph survives into what agents actually read,
and in a handful of places where the design ignores the one importance signal with the most
production precedent (reference-graph centrality).

### What the research validates

**The output format is the right bet.** AGENTS.md is the only empirically validated
docs-for-agents format — a 124-PR study across 10 repos (arXiv:2601.20404) found ~28.6% median
runtime reduction and ~16.6% lower output-token consumption at equal task-completion rates;
i.e., orientation files save exploration cost rather than improving success rate. The contrast
case is llms.txt: ~844K sites publish it and no major AI system reads it (Google's John Mueller:
server logs show crawlers don't request it). A docs-for-agents format only matters if the
consuming harness loads it — AGENTS.md/CLAUDE.md are loaded. Pre-materialized orientation plus
Read/Grep/Glob for depth is also exactly the hybrid Anthropic's context-engineering guidance
(Sep 2025) endorses for Claude Code.

**Structural extraction for code, LLM only for prose, is where the field landed.** Every
code-graph success story is deterministic-structural: Agentless (27.3% SWE-bench Lite from a
bare directory tree + hierarchical localization, $0.34/issue), LocAgent (92.7% file-level
localization from a deterministic import/invoke/inherit graph, arXiv:2503.09089), RepoGraph
(+32.8% relative on SWE-bench, ICLR 2025), GraphCoder (ASE 2024), Aider's repo map. The
documented noise — 1.5–1.9% hallucinated edges even with top-tier LLMs, 23–77% extraction
completeness across frameworks, rampant duplicate entities — lives in LLM-extracted graphs over
prose. The kernel's closed-structural / advisory-semantic / deterministic-concept split
(ADR-0024) matches the LlamaIndex / Neo4j GraphRAG / Microsoft GraphRAG convergence on
"open-with-guidance," and recovering precision downstream via confidence scoring rather than
schema rejection mirrors ODKE+ (91% → 98.8% via a corroboration pass, not constraints).

**No runtime synthesis matches the winners.** Zep/Graphiti (arXiv:2501.13956) makes no LLM
calls at retrieval and credits that for a 90% latency reduction alongside accuracy gains
(94.8% DMR; up to +18.5% LongMemEval). Letta's sleep-time compute is the kernel's pre-commit
materialization with a different scheduler. The kernel's pre-commit hook is sleep-time compute
with git as the scheduler.

**Wrapping LightRAG behind `KnowledgeStore` and doing custom entity resolution was prescient.**
LightRAG's native dedup is documented as exact-key-match-only (LightRAG issue #1631; "Less is
More: Denoising Knowledge Graphs for RAG," arXiv:2510.14271, finds LightRAG, MS GraphRAG, and
HippoRAG all leave duplicates unresolved). The backend's weakest link is exactly the part the
kernel re-implemented upstream (ADR-0017).

**Drift over recency (ADR-0020) is more principled than the field norm.** Most systems either
ignore staleness or use time-decay; git-measured structural divergence with code as the
reference frame is effectively a bi-temporal model where git supplies the clock (cf. Zep's
bi-temporal edges — the kernel's `commit_of()`/`changed_since()` is a defensible git-native
simplification).

**The Naur framing appears genuinely novel.** The 2024–2026 thread applying "Programming as
Theory Building" to agents (Goedecke; Nutrient; Bowen) names per-session theory loss as *the*
problem — agents rebuild a working theory every session and cannot retain it. No published
system was found that operationalizes Naur for agent context the way the concept layer +
CodeSpan evidence anchoring (ADR-0018) does. Closest analogues: A-MEM's linked notes
(arXiv:2502.12110 — Zettelkasten-style linked memory beat flat memory, 85–93% token reduction),
Letta's learned context.

### Where the design is under pressure

**1. The graph is nearly inert where agents read.** ADR-0023 diagnosed this at query time
("the edges we pay to extract do most of their work at ingest and almost none at retrieval") —
but it is equally true at *materialize* time, which matters more since files are the primary
interface. The materializer queries `get_summary(scope)` and renders prose; the scope summary
itself is built by handing ranked entity *descriptions* to the LLM (`summarize_scope` receives
no relationships). The cross-altitude edges, the cross-scope dependencies, the
`realizes`/`governed-by` links to ADRs — the thesis-load-bearing structure — never
deterministically appear in AGENTS.md. The thesis says graphs compose altitude; the
materialized output is currently a per-directory bag of summarized entities.

*Recommendation (highest value, no invariant violated):* render edge-derived sections
deterministically in each scope's AGENTS.md — "Depends on" / "Used by" from cross-scope
structural edges, "Governing decisions" from `governed-by`/`realizes` edges into ADRs with file
paths, concept hubs with their CodeSpan receipts. A graph read at materialize time; makes the
differentiator over grep visible to the reading agent.

**2. No hierarchical composition — the altitude axis is asserted, not built.** Every scope
summary is generated independently from its own entities; a parent directory's AGENTS.md does
not compose its children's. Microsoft GraphRAG's one durable contribution is exactly this —
hierarchical community summaries at multiple abstraction levels. The kernel does not need
Leiden communities: the directory tree *is* the hierarchy (and Agentless showed the bare tree
is a top-tier localization signal). Summarize leaves from entities, then parents from child
summaries + parent-local entities, bottom-up. This also bounds incremental cost: a change
re-summarizes only the ancestor chain. Today, "context at one altitude doesn't compose into
another" is still true *inside the kernel's own output*.

**3. Centrality ignores the reference graph.** `CENTRALITY_KINDS` counts distinct-source
in-degree over `implements`/`inherits`/`realizes`/`governed-by`/`implemented-by`, excluding
`calls` (0.6) and `imports` (starved at 0.3). But the importance signal with the most
production precedent — Aider's PageRank over tree-sitter defs/refs, HippoRAG's Personalized
PageRank (+20% multi-hop QA, NeurIPS 2024), LocAgent — is computed over precisely the
call/import reference graph being excluded. The lexicon-inflation defense (distinct-source
capping) is right for doc edges; for *code* entities, "what does everything call" is the
proven what-matters signal. *Recommendation:* compute weighted PageRank over structural edges
at ingest (pure; fits `scoring.py`'s no-I/O tenet) and use it for materialization selection —
what makes the cut in a scope summary's token budget. Keep ADR-0015 centrality for the
docs-gap/health use case; the two answer different questions.

**4. Cross-project relation is concept-hubs-only, thinner than the thesis needs.** Per-project
namespaces with portfolio concept hubs as the sole bridge is a defensible v1 cut, but real
portfolios have *deterministic* cross-project structure currently left on the floor:
dependency manifests (`pyproject.toml`/`package.json` naming a sibling project), shared
schemas, frontend→backend API surfaces. A manifest handler emitting project-level `depends-on`
edges is structural-family work — no LLM, no entity merging, no violation of non-goal 2 — and
lets the portfolio-root view answer "what breaks downstream if I change project X."
Relatedly, ADR-0026's residual conflation (11.4% of `imports` landing on doc prose) is
dominated by external libraries having no node; an `external-package` structural kind would
absorb those edges deterministically and double as the manifest handler's vocabulary.

**5. Deterministic-only ER will leave duplicates — solve with a review queue, not fuzzier
matching.** The canonicalization literature (CESI, WWW 2018; EDC "Extract, Define,
Canonicalize," arXiv:2404.03868) is unanimous that exact/normalized matching under-merges. But
embedding-based merging is non-deterministic and collides with the idempotency invariant —
don't do it inline. The fit with the curated-overlay model (ADR-0025) is a *materialized
candidate-merge view*: at ingest, list high-cosine cross-cluster pairs and orphaned doc
concepts whose name matches exactly one method leaf (ADR-0026's deferred merge), ranked; the
operator promotes accepted pairs into ontology aliases. The merge becomes deterministic
(alias-driven), auditable, and idempotent. ADR-0025 §6 already sketches the promotion loop for
concepts — generalize it to entity aliases and ship it as a view.

**6. The amortization assumption is load-bearing and unmeasured.** The industry retreat from
upfront LLM summarization is real — LazyGraphRAG indexes at ~0.1% of full GraphRAG's cost by
moving synthesis to query time (Microsoft Research, Nov 2024; >700× lower query cost than
GraphRAG Global at comparable quality), and GraphRAG-skeptic results (GraphRAG-Bench,
arXiv:2506.05690: "GraphRAG models frequently underperform traditional RAG on many real-world
tasks"; Han et al. 2025: −13.4% vs vanilla RAG on NaturalQuestions) show the LLM-extracted
prose graph earns modest, task-dependent gains. The kernel's bet survives via amortization
(many agent reads per ingest) plus content-addressed caching — supported by its own numbers
($0.115/full-portfolio ingest, 74% cache hit) — but the deferred EvalHarness is now the
bottleneck for several *accepted* decisions: edge weights are load-bearing for retrieval
(ADR-0023's own words), expansion knobs are uncalibrated, expansion itself showed zero gain on
the only corpus tested, and the target corpus (doc-thin agentic repos) has never been measured.
Promote `ck eval` above any new graph feature: at least four surfaces are tuned by intuition
(edge weights, hop decay, similarity threshold 0.82, authority tiers) and the A/B harness
pattern (`h2_eval.py`, `expansion_ab.py`) is already proven.

**7. Housekeeping.**
- The docs have drifted from the code in the system built to prevent doc drift:
  ARCHITECTURE.md §1.1/§2.1 still describe "LightRAG with pluggable storage (Neo4j / Postgres /
  Milvus available without code changes)," but ADR-0017 establishes the shipped `LightRAGStore`
  is a hand-rolled JSON+NetworkX store that never used LightRAG's machinery. Rename the adapter
  and amend the settled tradeoff — nothing was lost (LightRAG's dedup was the weak link), but
  the record should say what is true.
- `_cosine_sim` is pure-Python `struct.unpack` + loops over every chunk per query; at portfolio
  scale (8K+ entities, +37% with method nodes) this needs numpy batch matmul. Trivial fix, hot
  path (`find`).
- Drift only covers doc→code semantic edges; a doc describing another doc (ADR superseding
  analysis, THEORY referencing ADRs) accrues no drift. Probably acceptable; worth a line in
  ADR-0020's revisit clause.

### Priority order

1. **Edge-derived sections in AGENTS.md** (deterministic dependencies/decisions/concepts per
   scope) — smallest change with the most thesis leverage.
2. **Hierarchical scope summarization** up the directory tree — this *is* the
   altitude-composition thesis, currently unimplemented.
3. **EvalHarness** (`ck eval`, kernel-vs-grep on a doc-thin corpus) — too many accepted
   decisions rest on uncalibrated numbers.
4. **PageRank over structural edges** for materialization selection.
5. **Candidate-merge review view → ontology aliases** (ER stays deterministic; under-merging
   gets a human-in-the-loop escape).
6. **Manifest-derived project `depends-on` edges + `external-package` nodes.**
7. Doc/naming corrections (LightRAG claim) and numpy-ifying similarity.

### A caveat on framing

The literature supports the diagnosis behind ADR-0001 (agents rebuild theory from scratch every
session) but also Naur's own ceiling — theory is not fully documentable; tacit knowledge
resists materialization. The kernel should keep claiming "a partial theory at session start
beats none," not "the theory, externalized." The candidate thesis expansion (2026-05-29)
currently says the latter ("any question posed in concepts resolves to precise code"); soften
before promoting.

---

## Part II — Approach and positioning

*Prompted by: "Sourcegraph and Potpie already build graphs as knowledge for agents — is this
the right approach for a personal tool, and can a Philosophy of Software Design lens be baked
into the kernel (guidance on structure, missing documentation), beyond context-for-fewer-tokens?"*

### The competitive framing is a category error (in the kernel's favor)

Sourcegraph and Potpie are **descriptive** systems. Sourcegraph builds a precise symbol graph
(SCIP) and answers "what is this code, where is it referenced" at enterprise scale. Potpie
builds a code knowledge graph and runs generic worker agents (debug, test, Q&A) on top. Both
are read paths: code in, facts out. Critically, both must be **opinion-neutral** — they are
sold to organizations with heterogeneous codebases and conflicting engineering cultures, so
they cannot encode a view of what good software looks like.

The kernel has three jobs, and only the first overlaps with them:

1. **Orientation** — better context for fewer tokens. The descriptive job, the validated one,
   and the one that will commoditize. Tree-sitter symbol graphs are table stakes; agent-native
   search keeps improving. This job alone is a worse Sourcegraph.
2. **Theory capture** — the why-layer. ADRs, invariants, decisions linked to code with
   `realizes`/`governed-by`, with authority/drift/confidence epistemics. Nobody else does this.
   Enterprise tools treat all indexed content as equally true; the kernel knows a stale handoff
   note from a load-bearing invariant.
3. **Judgment** — the PoSD layer. Not "what is the code" but "is the code becoming what I
   want, and what's missing."

Jobs 2 and 3 require something an enterprise product structurally cannot have: **the
operator's opinions as input**. `AUTHORITY_TIERS` is an opinion. The tenets in ARCHITECTURE.md
are opinions. A PoSD lens is an opinion. For a sellable product, opinionation is a liability;
for a personal kernel, it is the moat. Invest where curation compounds; treat the descriptive
layer as plumbing. (Taken to its conclusion: the structural layer could eventually be ingested
from SCIP indexers instead of hand-maintained per-language handlers, keeping only the
semantic/epistemic/normative layers as the product.)

### The PoSD layer isn't bolted on — the kernel already measures Ousterhout's terms

Ousterhout's central definition is **complexity = dependencies + obscurity**, with three
symptoms: change amplification, cognitive load, unknown unknowns. Mapped onto what the kernel
already computes:

| Ousterhout | Already in the kernel |
|---|---|
| Dependencies | The structural edge layer (`imports`, `calls`, `inherits`, cross-scope edges) |
| Obscurity | The doc-gap signal — high centrality with no grounded documentation is literally "important and unexplained" |
| Change amplification | `change_detection.py` churn + commit history; change-coupling (files co-changing across scope boundaries) is one query away |
| Cognitive load | Tokens-to-orientation — the exact quantity the kernel exists to minimize |
| Unknown unknowns | Undocumented load-bearing nodes — the Documentation Gap concept, verbatim |

The handlers already emit `Interface:`/`Internals:` splits and LOC — the raw material for
**module depth** (interface surface vs. functionality concealed). Pass-through methods fall out
of call edges plus signature comparison. The closest prior art is Adam Tornhill's behavioral
code analysis (hotspots = churn × complexity, change coupling from git) — and the kernel
already owns the git layer he builds on. "Bake PoSD into the kernel" is not a new subsystem;
it is a new *projection* of data the graph already holds. THEORY.md's open question about
encoding Ousterhout's module model first-class can be answered: yes — as computed signals over
the existing schema, not as new schema.

### The deeper unification: the kernel is a governor, not a cache

The three jobs compensate for the same loss. Delegating code production to agents means three
things that lived in the typing engineer's head stop being applied continuously: the codebase
theory (Naur), the design taste (Ousterhout), and the documentation discipline.
Sourcegraph-class tools assume humans still hold all three and need lookup. The kernel's
workflow assumption is the opposite — and the pre-commit hook means it is not a read path at
all. It is a **feedback loop with commit-time sampling**:

> agent reads AGENTS.md → writes code → hook re-ingests → signals recompute → *next* session's
> context says "depth degraded in this scope; `FooManager` added last commit is a pass-through;
> this hub gained 12 callers and has no reference doc" → the agent or operator corrects.

That loop is the product category. Not "externalized theory of the codebase" (descriptive) but:
**the engineer's theory and standards, made ambient and self-correcting, for an organization
whose ICs are agents.** Orientation is the loop's feed-forward path; design signals and doc
gaps are its error terms.

### Pushback

**Normative output needs higher precision than descriptive output — stage it accordingly.**
The HANDOFF.md incident proved the failure mode: agents *believe* their context, so a wrong
claim in AGENTS.md propagates. A miscalibrated "this module is too shallow" in agent-facing
context is worse than nothing — agents either ignore the channel (linter fatigue) or
refactor-churn against false positives. Ousterhout frames red flags as attention heuristics,
not rules. The staging discipline the project already invented applies: design signals launch
as an operator-facing view (`views/design-signals.md`, ranked attention queue, every flag
carrying a CodeSpan-style receipt). They graduate into agent-facing AGENTS.md only after
measured precision — the ADR-0017/0018 posture. "Flag, never fabricate; evidence, never vibes"
extends from facts to judgments unchanged.

**The cheapest "guide how code should be structured" is distribution, not computation.** The
kernel is already a guaranteed-fresh distribution system for context. Authored design tenets
belong in the ontology (a `tenets:` block in `ontology.yaml`, per ADR-0024's one-file
philosophy), materialized into every scope's AGENTS.md: zero inference risk, immediate behavior
change in agents, and the normative layer becomes *data* like everything else. Computed signals
are phase two.

**Guard against building three products.** Orientation is validated; theory-capture is built
and partially validated; judgment is hypothesis. They share a substrate and a delivery surface,
so marginal cost is genuinely low — but each needs its own eval, and the eval harness does not
exist yet. EvalHarness is the bottleneck for the whole expansion, because the normative layer
raises the precision bar precisely where there is currently no measurement.

### Verdict

The approach is right, and the instinct to differentiate on philosophy rather than graph
mechanics is correct — the graph is becoming commodity infrastructure; an opinionated,
epistemics-aware, commit-time feedback loop for a one-person agentic shop is not something
Sourcegraph or Potpie can become without unbecoming themselves. The PoSD layer is more native
to the existing design than it first appears (the kernel has been computing Ousterhout's
complexity terms all along), but it must enter through the same gates as everything else in
this codebase: derived not authored, evidence-anchored, operator-first, measured before
agent-facing. The thesis candidate in THEORY.md should absorb this: the kernel isn't just the
externalized theory — it's the standards too, applied at every commit, which is the part of the
engineer that doesn't fit in a context window.
