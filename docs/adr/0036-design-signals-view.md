# ADR-0036: Design-signals view — an evidence-anchored attention queue with an effective-FP loop

**Date:** 2026-06-09
**Status:** Proposed

## Context

The kernel's normative layer (REVIEW-FABLE.md Part II) needs its computed half: design-quality
signals derived from data the graph already holds — structural edges, per-module
interface/internals splits and LOC, git churn (`change_detection.py`), doc↔code links,
centrality. The mapping to Ousterhout is direct (complexity = dependencies + obscurity;
unknown unknowns = undocumented load-bearing nodes), but the evidence ranks the signals very
unevenly, and the governing risk is not signal computation — it is **alert fatigue** for the
operator and **over-obedience** for agents
(docs/research/2026-06-09-design-signals-normative-layer.md):

- Strongest validation: churn-anchored composites (CodeScene "Code Red": 15× defects, +124%
  resolution time in low-health code; process metrics beat code metrics — near-consensus).
- Change coupling (Gall 1998; Zimmermann ICSE 2004) is information leakage made measurable and
  catches what static analysis cannot (including code↔doc, cross-language).
- Module depth and pass-through have **no published validation** — the kernel pioneers, so it
  may only rank relatively, never against absolute thresholds.
- Classic complexity metrics are not worth computing (cyclomatic ≈ LOC; LCOM/Henry–Kafura
  empirically dismantled).
- Google's Tricorder discipline (CACM 2018): effective false positive defined
  *behaviorally* (no action taken = FP, even if technically correct); **≤10% effective-FP
  bar**; misbehaving analyzers **disabled, not tuned in place**; FindBugs failed twice at
  Google on the standing-dashboard pattern; true-but-unimportant findings die (ISSTA 2010).
- Agents **over-obey** review-style feedback (arXiv:2603.00539) — a false design flag in agent
  context buys refactor churn, not neglect. Nobody has measured agent response to
  design-quality warnings; the kernel would generate the first data.

## Decision

1. **Five signals, built in evidence order**, computed at ingest by pure functions in a new
   `context_kernel/signals.py` (fed by the ingester; no I/O in the module — the `scoring.py`
   tenet):
   - **Hotspot** — `relative_churn(file) × (1 + importance(module))` (ADR-0031); top decile
     flagged. *(Strongest evidence; ships first.)*
   - **Change coupling / information leakage** — pairs co-changing in ≥70% of commits touching
     either, support ≥5, **and no structural edge between their scopes** — the no-edge
     condition converts co-change into a leakage claim. Receipt: the commit shas.
   - **Documentation gap, churn-ranked** — `centrality × relative_churn × [no
     realizes/governed-by in-edge from a doc node]` — the existing gap concept (CONTEXT.md),
     now ranked by heat.
   - **Depth outlier** — `interface_count / internals_loc` per module (both already
     extracted); flag bottom decile **∧** fan-in top quartile. Relative ranking only.
   - **Pass-through** — AST detection in the Python/TS handlers (method body = single call
     forwarding its own parameters, same/similar name); flag classes ≥50% delegating
     (Fowler's Middle Man rule). Receipt: the forwarding line as a CodeSpan (ADR-0018).
   All numeric thresholds are explicitly provisional `CK_SCORING_*`-style knobs — no published
   calibration exists; the portfolio calibrates them.
2. **`change_detection.py` gains `co_change(window=200)`** — parse `git log --name-only`,
   return pair co-occurrence and per-file counts; safe `{}` on failure like the rest of the
   module (drift falls to zero, never raises).
3. **One ranking rule: `severity × hotspot-ness`.** A shallow module that never changes is not
   actionable; one in the top churn band is. This single multiplication is the
   best-evidenced ranking decision available (power-law effort concentration) and is the
   defense against the true-but-unimportant failure mode.
4. **Queue-in-workflow, never a dashboard.** `views/design-signals.md` renders in two modes:
   `--changed-only` at the pre-commit/materialize moment (findings touching the current diff —
   the in-workflow surface, mirroring new-code-only gating), and the full ranked view on
   demand. Every finding = score — claim — **receipt** (files:lines, numbers, commit shas) —
   suggested action.
5. **The effective-FP loop is part of the feature, not an afterthought.** Findings carry
   stable ids; operator verdicts land in `.context-kernel/signal-verdicts.toml`
   (`id = "fixed" | "not-useful" | "later"`) and feed the journal. A signal class exceeding
   **10% `not-useful`** over a trailing window is **auto-disabled with a loud log line**
   (Tricorder's policy: disable, don't tune in place).
6. **Operator-facing only at adoption. Agent-facing promotion is per-class, gated, and
   observational.** A signal class may enter agent-facing AGENTS.md only after (a) its
   effective-FP rate holds under the bar and (b) an ADR-0029 eval run shows non-negative
   effect — and then only as **evidence-anchored observations, never imperatives**
   ("`a.py` and `b.py` co-changed in 12 of 14 recent commits; no structural edge explains it —
   see views/design-signals.md"), because explanation-heavy directive feedback measurably
   increases LLM misjudgment. The eval instruments refactor-churn attributable to promoted
   signals, not just precision.

## Considered options

- **Per-function complexity metrics (cyclomatic, cognitive, LCOM).** Rejected on the validity
  record; LOC + churn + structure carry the signal.
- **A standing portfolio health dashboard.** Rejected — the FindBugs pattern failed twice at
  Google scale and fails faster for one operator; the commit moment is the hook.
- **Agent-facing from day one.** Rejected — over-obedience evidence plus zero published data
  on agent response to design warnings; the promotion gate is the difference between a design
  conscience and a churn generator.
- **Auto-fix.** Rejected outright — flag, never fabricate/never fix is the kernel's posture
  (invariant 1's spirit applied to judgment).

## Consequences

- The PoSD layer ships as ranked, receipted attention — extending "flag, never fabricate;
  evidence, never vibes" (ADR-0018) from facts to judgments unchanged.
- New: `signals.py`, `co_change()`, pass-through detection in handlers, one view, the verdict
  file + journal plumbing. Depth/pass-through pioneering is bounded by relative-only ranking.
- The kernel becomes self-measuring about its own normative quality: the verdict log *is* the
  precision record that promotion decisions cite.
- Two findings consumers exist from day one: the operator (view) and ADR-0032 phase-2 tenet
  checks (divergences land in the same view, same receipt format).

## When this should be revisited

- The operator stops reading the view → that *is* the effective-FP signal at the whole-feature
  level; cut signal classes until it earns attention again, don't add.
- A class sustains >90% `fixed` verdicts → candidate for promotion review (the inverse of the
  disable rule).
- Depth/pass-through flags prove noisy even ranked → drop them before they erode trust in the
  validated classes (churn composites must not pay for the pioneers' false positives).

## Related

- [ADR-0018](./0018-evidence-anchored-concept-edges.md) — the receipt pattern extended to judgments.
- [ADR-0031](./0031-structural-importance-pagerank.md) — hotspot ranking input.
- [ADR-0032](./0032-tenets-authored-design-rules.md) — phase-2 conformance divergences land here.
- [ADR-0029](./0029-private-paired-eval-harness.md) — the promotion gate.
- [ADR-0015](./0015-entity-confidence-scoring.md) — centrality (gap signal) and the knob precedence.
- docs/research/2026-06-09-design-signals-normative-layer.md.
