# ADR-0026: Methods as first-class nodes; bare-leaf call resolution with code precedence

**Date:** 2026-06-01
**Status:** Proposed

## Context

ADR-0017 made the graph **code-anchored**: the finest code entity is an AST symbol, and a
`calls` edge is a structural fact read straight off the tree. But the structured handlers
stopped at **module / class / top-level function**. A class's *methods* were never emitted as
nodes — their signatures were folded into the class entity's `Interface:` / `Internals:`
description text, and **every method body's `calls` were attributed to the enclosing class**
(`handlers.py`: *"methods are not standalone entities, so a method body's calls hang off the
enclosing class node"*).

An audit of the Ticket Agent graph (commit `308c7221`, 8,145 entities) measured the cost:

- A call site names a method by its **bare leaf** — `self.handle_message()` yields
  `handle_message` (the receiver is lost; ADR-0021). With no code node for the method, the
  resolver bound that call to whatever *same-named* entity existed — and that was usually a
  **doc-derived `workflow` node** describing the method in prose.
- **155 of 3,309 `calls` edges (4.7%)** from a code entity terminated on a **doc-only** node;
  for `imports` it was **198 / 1,735 (11.4%)**, dominated by external libraries (`anthropic`,
  `pydantic`) modeled only as `constraint` prose.
- Worst cases crossed semantic boundaries outright: `_memoized_render --calls--> /clear
  [decision]` (a slash-command record), `OpenAIChatClient --calls--> #chat [element]` (an HTML
  DOM node). These assert a call to something that is not callable.

Reassuringly, the feared *code→code* misresolution did **not** occur: of 1,642 cross-file
call edges, **zero** landed on a name-collision group — the resolver declines to guess an
ambiguous code callee (ADR-0017) rather than binding the wrong file. The damage was confined
to **code→doc binding**, and its root cause was singular: **methods are not nodes, so a
structural call edge falls through to the prose that happens to share the name.**

## Decision

Emit methods as **first-class entities** and teach the resolver to bind bare method-call leaves
to them, with code precedence.

1. **Method nodes.** Each class method becomes a `function`-kind entity named **`Class.method`**
   (qualified). The base ontology already defines `function` as *"a top-level function or
   method"* (ADR-0024), so no new kind is introduced. The folded `Interface:`/`Internals:`
   text stays in the class description as a human-readable summary.

2. **Qualified, not bare.** Naming is the load-bearing choice. **Bare** names are unworkable:
   two `__init__`s in one file share `(name, source_file)` and would collapse to one node (data
   loss), and bare names collide portfolio-wide. **`Class.method`** is unique per method, so
   the resolver's existing `(name, source_file)` identity (ADR-0017) keeps every method
   distinct with no new collision machinery.

3. **Calls relocate to the method.** A method body's `calls` hang off the **method** node, not
   the class. Class-body-level calls (decorators, field initializers) stay on the class. The
   class no longer absorbs every callee its methods touch.

4. **Bare-leaf resolution with code precedence (ADR-0017 extension).** The resolver builds a
   **leaf index**: each *unique* code-method leaf (`handle_message`) → that method's canonical
   id. In endpoint resolution the order is: exact `(name, file)` → unambiguous **top-level
   code** symbol → **code-method leaf** → doc concept. So a bare call binds to the real method,
   and **code wins over a same-named doc node** — which is what closes the conflation. A leaf
   shared by ≥2 methods (or a stoplist name like `__init__`) is **ambiguous → dropped, never
   guessed**, exactly the stance ADR-0017 already takes for ambiguous bases.

5. **Symmetric across handlers.** Applied to `PythonHandler` (`ast`) and `TypeScriptHandler`
   (tree-sitter). Method nodes are excluded from the module-`contains` blanket edge — they are
   `contains`ed by their class.

### The two axes — why "code precedence" here does not demote docs

The kernel's thesis is *documentation that stays fresh*, and ADR-0015 makes **high-tier docs
outrank code on authority** (THEORY invariant 1.0 > code 0.85; *"code says nothing about
why"*). This decision does **not** touch that axis. Two orthogonal priorities are in play:

| Axis | Question | Winner | Governing ADR |
|---|---|---|---|
| **Authority / trust** | Whose *claim* do I believe and surface? | high-tier **docs** | ADR-0015 |
| **Identity / structure** | Which node *is* this thing; what calls what? | **code** | ADR-0017 |

A `calls` edge is a structural fact; its target is the callable code *by definition*. A doc
`workflow` named `handle_message` is a *description of* the method, not the callable — so the
old behavior bound a structural edge to prose. "Code precedence" fixes the **endpoint of a
structural edge**; it changes nothing about which source's claims rank highest. And it is the
*mechanism of freshness*, not its opponent: drift (ADR-0020) is only measurable when a doc's
claim is pinned to the code symbol it describes. Anchor identity on prose and you can no longer
detect that the code moved out from under the doc.

## Considered options

- **Bare method names + global merge.** Maximal code↔doc linking, but collapses same-file
  same-named methods and re-creates the portfolio-wide collision explosion ADR-0017 designed
  out. Rejected.
- **Method nodes, no resolver change.** Emit nodes but leave bare calls ambiguous (drop). Safe,
  but leaves the cross-file doc-twin conflation intact. Rejected as half a fix — the user
  explicitly chose the full resolution.
- **Merge the doc-leaf concept *into* the method node** (code-anchored, doc as a `source`).
  This is the truest "code-anchored so docs stay fresh": the prose description of
  `handle_message` would fold into `Class.handle_message` as provenance, its drift tracked
  against the code. **Deferred, not rejected** — names differ (bare leaf vs qualified), so it
  needs a leaf-aware merge rule (a doc concept whose name matches exactly one method leaf folds
  into that method). Flagged as the natural follow-up (see *When revisited*).
- **Suppress doc binding for `calls`/`imports` entirely** (a structural edge may only land on a
  code node). Simpler and kills the residue, but throws away legitimately useful links and
  needs no method nodes — orthogonal. Worth pairing with the merge option later.

## Measured evidence (deterministic re-extraction, no re-ingest)

Re-extracted all 443 Ticket Agent `.py` files with the new handler, reconstructed the existing
doc entities as resolution targets, and ran the new resolver:

| | before (audit) | after |
|---|---|---|
| method entities | 0 (folded) | **2,993** |
| `calls` from code → **code** | ~94% | **99.6%** |
| `calls` from code → **doc-only** (conflation) | 155 (4.7%) | **28 (0.4%)** |

An **82% reduction** in code→doc call conflation. The residual 28 are the irreducible class —
calls to symbols with **no code definition in the repo** (external libs: `anthropic`,
`DefaultAzureCredential`, `TracerProvider`; a callback *parameter* `token_callback`; and 3
`/clear`-decision normalize-collisions). Method extraction cannot bind these because there is
no code node to bind to; closing them needs the *merge* or *suppress-doc-binding* options
above. Full suite: **535 passed, 16 skipped.**

## Consequences

- **Entity count grows** (~2,993 method nodes on the Ticket Agent, ~+37%). Each method is
  embedded at ingest — a real but small cost (doc summaries are content-addressed and cached;
  only new method entities embed). The graph stays well within the v1 store's brute-force
  budget.
- **The call graph becomes traversable at method granularity** — `who calls X` reaches a real
  method, and intra-class calls (`self._foo()`) now resolve. This is the orchestration depth
  ADR-0021's `calls` family was meant to carry.
- **Re-ingest is the migration** (`rm -rf .context-kernel` per ADR-0008); `graph_commit`
  changes, materialized AGENTS.md files regenerate.
- **The class entity is no longer the calls super-sink.** Centrality (ADR-0015) redistributes
  from classes to methods — expected, and more honest.

## When this should be revisited

- **Bring the leaf-aware merge forward** if the audit shows many orphaned doc concepts that
  name exactly one method (the prose description should fold into the method node as a `source`,
  so its drift is tracked — the strongest form of "docs stay fresh against code").
- If the residual external-library conflation on `imports` matters, decide the *suppress
  doc-binding for structural edges* option — modeling third-party libraries as their own node
  kind, or dropping structural edges that can only reach prose.
- If method-granularity inflates the graph or embedding cost beyond budget on a large
  portfolio, reconsider emitting only **public** methods as nodes (private folded), trading
  recall for size.
