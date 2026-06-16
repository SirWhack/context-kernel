# Research: The normative layer — design tenets and design-quality signals

**Date:** 2026-06-09
**Status:** Research notes — input to future ADRs (not a decision)
**Origin:** [REVIEW-FABLE.md](../../REVIEW-FABLE.md) Part II; THEORY.md open question on
encoding Ousterhout's module model; the "kernel as governor" framing
**Companion docs:** [hierarchical materialization](./2026-06-09-hierarchical-materialization-and-importance-ranking.md),
[ontology & entity resolution](./2026-06-09-ontology-and-entity-resolution.md)

Two features motivated this research pass:

- **Feature F — tenets distribution.** Authored design tenets (Philosophy of Software Design
  -derived and project-specific) carried in the ontology and materialized into agent-facing
  context.
- **Feature G — design-quality signals.** Computed from data the graph already holds
  (structural edges, interface/internals splits, LOC, git churn, doc↔code links): module
  depth, pass-through methods, change coupling, hotspots, documentation gaps — surfaced as
  ranked, evidence-anchored attention queues. Flag, never auto-fix; operator-facing first.

Confidence flags: **[HIGH]** verified against primary source by the research pass;
**[MED]** consistent secondaries; **[LOW]** single/vendor source.

---

## 1. Operationalizing PoSD — the field is nearly empty (opportunity and warning)

- **Module depth has essentially no tooling or academic operationalization.** The only direct
  implementation found is [`olahol/deepmodules`](https://github.com/olahol/deepmodules)
  (Go, 2 stars): `depth = total LOC ÷ exported symbols`, with the author's own caveat that all
  exports weigh equally. No peer-reviewed paper measures interface-size-vs-implementation-size
  depth. **[HIGH that the gap exists]** → The kernel's per-module `Interface:`/`Internals:`
  split makes it a genuine first mover — **with no validated thresholds to borrow.** Rank
  relatively within the portfolio (flag the shallow tail with high fan-in); never set absolute
  cutoffs.
- **Ousterhout frames red flags as judgment aids, not metrics.** PoSD's ~14 named red flags
  (Shallow Module, Information Leakage, Pass-Through Method, Temporal Decomposition, …) are
  explicitly symptoms requiring human judgment; complexity "is not directly measurable" in his
  framing. **[MED]** → The kernel's posture must match: signals are attention heuristics with
  receipts, not rules.
- **Pass-through ≈ Fowler's "Middle Man" smell**, which has detector lineage: flag when ~half
  or more of a class's methods merely delegate
  ([refactoring.guru](https://refactoring.guru/smells/middle-man)); per-method detection is
  AST-feasible (body = single call forwarding its own parameters, same/similar name). No
  published precision numbers. **[MED]**
- **Do not import the classic structural metrics.** Henry–Kafura information flow
  ((fan-in × fan-out)²) was dismantled by Shepperd & Ince (JSS 1994); LCOM assigns identical
  values to structurally different classes and spawned five variants without consensus.
  **[HIGH that the critique is mainstream]** → Ratio-style depth and pass-through counts are
  at least as defensible and far more legible.

## 2. Behavioral code analysis — the strongest precedent for Feature G

- **CodeScene "Code Red"** (Tornhill & Borg, TechDebt 2022,
  [arXiv:2203.04374](https://arxiv.org/abs/2203.04374); 39 production codebases, 30,737
  files): low-health code had **15× more defects**, **+124% mean issue-resolution time**, ~9×
  worse worst-case cycle time. **[HIGH]** (vendor-conducted but peer-reviewed; replication
  package public).
- **Hotspots concentrate effort on a power law**: 1–2% of files account for the majority of
  development activity; one case study — 4% of code, 72% of defects (Tornhill, *Your Code as a
  Crime Scene*). **[MED]**
- **Change coupling is the most academically validated graph+git signal planned.** Gall et al.
  1998 (logical coupling) → Zimmermann et al., ICSE 2004/TSE 2005 (ROSE): top-3 co-change
  suggestions contain a correct location ~64–70% of the time, and the signal surfaces coupling
  **invisible to static analysis** — including code↔docs and cross-language. **[MED — exact
  figures approximate]** → This is Ousterhout's *information leakage* made measurable: two
  modules that always change together but share no structural edge are leaking a design
  decision. The kernel's git layer + scope tree makes this one query.
- **Process metrics beat code metrics — near-consensus.** Nagappan & Ball (ICSE 2005):
  *relative* churn highly predictive (absolute churn is not). Rahman & Devanbu (ICSE 2013):
  process metrics outperform product metrics, which are *stagnant* — they re-flag the same
  files release after release. Confirmed at scale by Majumder et al. (EMSE 2022). **[HIGH/MED]**
  → **Churn-anchored composites first; structural-only signals last.**

## 3. Classic complexity metrics — skip them

- Cyclomatic complexity is largely a size proxy (Shepperd 1988; Graylin 2009 stable linear
  CC↔LOC; Landman 2016, 17M Java methods). **[HIGH]**
- Cognitive Complexity (SonarSource): validated for comprehension *time* (Muñoz Barón et al.,
  ESEM 2020, ~24K evaluations) but no significant improvement over plain CC for
  fault-proneness (Lavazza 2023). **[HIGH/MED]**
- → LOC is already in the graph; spend the budget on churn-weighting, not per-function
  complexity.

## 4. Alert fatigue — the governing risk, with hard numbers

From Sadowski et al., "Lessons from Building Static Analysis Tools at Google" (CACM 61(4),
2018) — **[HIGH, verified from paper text]**:

- **"Effective false positive" is behavioral**: a finding the developer takes no action on
  *is* a false positive, even if technically correct. A technically-wrong finding the
  developer fixes anyway is not.
- **The bar: ≤10% effective FPs** for code-review-time checks (compile-time: ~zero); findings
  must be understandable, actionable, easy to fix.
- **The enforcement loop**: a "Not useful" button auto-files a bug; **misbehaving analyzers
  get disabled, not tuned in place.** At scale: >5,000 "Please Fix" vs ~250 "Not useful"
  clicks/day (~5%).
- **FindBugs failed at Google three times** before Tricorder: a nightly **dashboard** nobody
  visited; a fixit where real bugs were "not important enough to fix in practice"
  (true-but-unimportant is its own failure mode — Ayewah & Pugh, ISSTA 2010); and a review
  integration killed by effective FPs plus per-user customization eroding consistency.
- Coverity (Bessey et al., CACM 2010) had to simplify checkers because **correct but
  hard-to-understand reports were dismissed as false positives**.

**The agent-specific twist — over-obedience, not fatigue.** Jin & Chen
([arXiv:2603.00539](https://arxiv.org/abs/2603.00539), Feb 2026): LLM reviewers systematically
**overcorrect** — misclassifying correct code as defective — and richer prompts (explanations +
proposed fixes) *increase* misjudgment. **[HIGH]** The ETH AGENTS.md study (§6 below)
independently found agents respect instructions *to a fault*. → **Design warnings injected
into agent context will be over-obeyed, not ignored** — the opposite failure mode from humans
and arguably worse for a flag-only system. A false "this module is too shallow" in agent
context buys refactor churn, not neglect.

## 5. Architecture conformance — the 30-year-old shape of the tenets feature

- Erosion research is dominated by **consistency-based conformance checking**, yet
  practitioners report effectively no dedicated tooling reaches them (Li & Liang, JSEP 2022
  mapping study, 73 papers). **[HIGH]**
- The foundational mechanism is Murphy & Notkin's **reflexion model** (FSE 1995/TSE 2001):
  hand-author a small high-level model, extract the actual structure, diff them, report
  convergences/divergences/absences. **[MED]** → This is exactly "authored tenets vs.
  extracted graph": a tenet like *"all git I/O goes through `change_detection.py`"* is a
  reflexion-model constraint; a structural edge that violates it is a divergence finding with
  a receipt. The kernel's contribution is keeping the comparison **continuously fresh at
  commit time** — the reflexion model's known weakness was the hand model going stale, and
  staleness management is the kernel's home turf.
- Fitness-function practice (ArchUnit, import-linter, Nx module boundaries): cheap and useful;
  documented failure mode is **over-prescription** — "when every minor decision is enforced by
  a rule, teams treat architecture tests as red tape." **[LOW–MED]**

## 6. Design guidance for AI agents — the novel, riskiest, best-timed part

- **Context-file quality determines the sign of the effect.** Gloaguen et al. (ETH SRI),
  "Evaluating AGENTS.md" ([arXiv:2602.11988](https://arxiv.org/abs/2602.11988), Feb 2026),
  Claude Code/Codex/Qwen on SWE-bench Lite + 138 issues: **LLM-generated context files
  *reduced* success rates** (−0.5 to −2 pts) while **increasing inference cost >20%**;
  **human-written files averaged +4 pts**. The gain comes from *non-redundant, specific*
  information (tool choices, conventions not inferable from code); files restating what the
  code already shows hurt. Agents "tend to respect their instructions" — unnecessary
  specifications made tasks harder. **[HIGH]**
  → Direct constraint on the kernel's materializer: every generated sentence must earn its
  place; redundancy with the code is *negative* value, which independently supports the
  edge-receipts-and-pointers style over prose restatement. And it elevates pinned blocks +
  tenets (human-authored, specific) to the highest-value content class — matching the kernel's
  existing claim that pinned content is "the highest-quality data in the system."
- **The pathology the normative layer targets is real and growing.** LLM-generated code shows
  an average **+63.3% code-smell increase** vs reference solutions
  ([arXiv:2510.03029](https://arxiv.org/abs/2510.03029)) **[MED]**; GitClear's 211M-line 2025
  report: **8× growth in duplicated blocks** in 2024, moved/refactored lines collapsing
  24.1% → 9.5% (copy/paste overtook refactoring for the first time) **[MED]**; Borg &
  Tornhill ([arXiv:2601.02200](https://arxiv.org/pdf/2601.02200)): AI assistants in unhealthy
  code → ≥30% higher defect risk **[LOW–MED, vendor]**.
- **AI code-review precision today ≈ 50%** (CodeRabbit 49.2% on one benchmark; vendor numbers
  vary) **[LOW]** — i.e., 5× worse than Google's 10% bar. State of the art does not clear the
  bar the kernel should hold itself to.
- **Self-critique loops improve correctness, not (provenly) design** — self-repair is
  bottlenecked by feedback quality ([arXiv:2308.03188](https://arxiv.org/pdf/2308.03188));
  no study applies reflection to design quality. **[MED — absence]**
- **Nobody has measured how agents respond to design-quality warnings in context.** The
  closest results (over-obedience, §4; instruction-respect, §6) both point the same direction.
  The kernel's A/B harness would generate the first data of its kind.

## 7. Documentation gaps

- The doc-issue space is mapped (Aghajani et al., ICSE 2019: 162 issue types, dominated by
  outdated/incomplete; ICSE 2020 surveys confirm completeness + currency as top practitioner
  concerns). **[HIGH]**
- Evidence that documentation presence improves maintenance: positive but thin (one controlled
  experiment: −21.5% modification time **[LOW]**; but 39% of API misuses happen *despite*
  correct docs **[MED]** — docs are necessary, not sufficient).
- **No validated "importance × doc-absence" ranking metric exists.** The kernel's
  `centrality × churn × no-doc-link` formulation appears novel; each factor is individually
  grounded. **[MED — absence]**

---

## 8. Design implications

### Feature F — tenets distribution

1. **Adopt, with a hard budget.** Human-authored, specific, non-redundant guidance is the one
   context-file category with a measured positive effect (+4 pts). Cap tenets per scope to a
   handful of lines; never restate what the graph or code already shows (redundant generated
   context measurably hurts: −0.5 to −2 pts, +20% cost).
2. **No PoSD sermons.** Agents over-obey: a blanket "prefer deep modules" risks induced
   over-abstraction. Tenets must be **scope-specific and falsifiable** ("all git I/O goes
   through `change_detection.py`"; "the materializer is the only writer to AGENTS.md") — i.e.,
   reflexion-model constraints the graph can check, not aesthetics.
3. **Ship before signals.** Cheap, evidence-backed, zero inference risk. Home: a `tenets:`
   block in the ontology (overlay-composed per ADR-0025: portfolio tenets + per-project
   tenets), rendered into AGENTS.md by the materializer, participating in the composed-ontology
   hash so a tenet edit re-materializes (ADR-0024 §5 discipline).

### Feature G — design signals

4. **Evidence-strength build order:** hotspots/relative-churn → change coupling → doc gaps →
   module depth / pass-through (pioneering, no validation to borrow). Process×structure
   composites beat pure structure everywhere measured.
5. **Adopt the effective-FP metric and the disable loop.** FP defined behaviorally (operator
   took no action = FP). Target **<10% effective FP** before any signal class goes
   agent-facing — and expect to need better than 10% given agent over-obedience. One-keystroke
   "not useful" in the queue; a signal class that blows the budget is **disabled, not tuned in
   place**.
6. **Queue-in-workflow, never a dashboard.** FindBugs died twice on the standing-report
   pattern. Surface at the `ck materialize`/commit moment, scoped to **files just changed**
   (new-code-only gating, as SonarSource/CodeScene do), not as a global backlog.
7. **Rank by severity × hotspot-ness.** True-but-unimportant findings die (FindBugs fixit). A
   shallow module that never changes is not actionable; one in the top-2% churn band is. This
   single multiplication is the most evidence-backed ranking decision available.
8. **Provisional thresholds (calibrate on the portfolio; all [LOW]):** change coupling — flag
   pairs co-changing in ≥70% of commits touching either, min support ~5; pass-through —
   Fowler's ≥half-delegating at class level + per-method same-signature forwarding; depth —
   relative ranking only, flag bottom-decile depth ∧ high fan-in.
9. **Skip per-function complexity metrics entirely** (CC ≈ LOC; cognitive complexity disputed).
10. **Agent-facing rollout protocol:** operator-only → measure effective-FP per signal class →
    promote individual *classes* that sustain <10% → inject as **evidence-anchored
    observations, not imperatives** ("`turn_panel.py` and `responder.py` co-changed in 12 of 14
    recent commits; no structural edge explains it — see views/design-signals.md"), because
    explanation-heavy directive feedback measurably increases LLM misjudgment. Every signal
    carries a CodeSpan-style receipt (ADR-0018 pattern extends from facts to judgments
    unchanged).
11. **Doc-gap signal: adopt as "missing orientation for hot, central code."** Composes from
    existing data (centrality, churn, doc↔code links); pair every flag with its why (the
    centrality/churn evidence) to clear the actionability bar. The kernel already materializes
    a "Recommended documentation" footer — this is the same motion, ranked.

### The open risk to name in any ADR

There is no published evidence on how coding agents respond to design-quality warnings in
context. Both adjacent results (reviewer overcorrection, instruction over-respect) predict
over-reaction. The promotion gate (operator-measured precision before agent exposure) is not
bureaucracy — it is the difference between the kernel being a design conscience and being a
churn generator. The kernel's eval harness would produce the first data of its kind here;
treat that as a feature, and instrument it (track refactor churn attributable to promoted
signals, not just signal precision).

## Relation to existing kernel structure

| New thing | Existing seam it lands on |
|---|---|
| Tenets | `ontology.yaml` overlay composition (ADR-0024/0025); materializer templates; composed-ontology hash → freshness |
| Hotspots / change coupling | `change_detection.py` (churn, commit_of); scope tree; `views/` (ADR's view machinery) |
| Module depth / pass-through | StructuredHandler `Interface:`/`Internals:` + LOC; `calls` edges (ADR-0026 method nodes) |
| Effective-FP loop | Operational journal (verdict log); pinned-block-style operator input |
| Evidence receipts | CodeSpan (ADR-0018) — same node kind, new claiming concepts |
| Doc gaps | Documentation-gap concept (CONTEXT.md) + centrality (ADR-0015), now churn-ranked |
