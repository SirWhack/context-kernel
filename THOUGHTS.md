# THOUGHTS.md — geometry, altitude, and where identity lives

**Status:** scratch / theory-in-progress. Not an ADR. What graduates from here goes to
`THEORY.md` (as a sharpened open question) or to an ADR (as a closed decision). Until a claim
is measured, it stays here. No project-specific data in this file — pure mechanics.

**Current focus (2026-05-29):** working out whether the kernel should carry a *concept layer* above
the code-anchored graph (ADR-0017) — concepts as cross-cutting hubs that bridge implementations
across files and languages, making the kernel "the externalized, queryable theory of the codebase"
(THEORY.md candidate expansion). Reasoned to ~90%; the next move is the spike in
`thoughts-spiked.md` (run locally), **not** more theory.

## The question we keep circling

Three framings of one problem:

1. Is **code** the core of the graph, or **concepts**?
2. If concepts are first-class, **what canonicalizes them** — a maintained vocabulary, or
   extraction + similarity each run?
3. (new lens) Which **geometry** does each job — the model's *latent space* (frozen embedding
   distances) or its *context window* (attention computed live over co-resident tokens)?

These are the same question seen from three sides. The answer that's emerging is not "pick one"
— it's **route each job to the altitude and the geometry that can actually do it.**

## Established results we now hold

- **R1 — cross-modal gap (measured).** concept↔code best-cosine p50 ≈ 0.42, ceiling ≈ 0.76, vs
  code↔code p50 ≈ 0.755. A precision-safe threshold (~0.78) recovers ~0 doc→code links. Embeddings
  cannot *discover* concept↔code edges.
- **R2 — code-anchored within-project identity works (ADR-0017).** Deterministic clustering +
  content-addressed IDs took cross-altitude edges 0 → ~1,016 and code+doc nodes 0 → ~181, with no
  reliance on embeddings except a narrow same-name disambiguation guard (cosine ≥ 0.82).
- **R3 — code-anchoring cannot span languages.** The same concept implemented in Python and C#
  shares no symbol name. Normalization won't bridge them; the collision guard keeps them distinct.
  The *only* node type that can relate them is a concept — which R2 treats as a fallback. So
  within-project code-anchoring delivers the bottom of the altitude tree and leaves the apex
  (cross-project / cross-language *patterns* — the thesis's top altitude) with no node at all.

## The new lens: latent space ≠ context window

Two different geometries, blurred by the word "the model understands."

**Latent space (static embeddings, e.g. `text-embedding-3-large`).** A frozen map from text →
~3072-dim point, trained so that *similar-reading* text lands near. Cosine encodes *distributional
/ surface* similarity — "reads alike" — not identity, not implication, not type. Consequences:

- *Concepts cluster densely and too smoothly.* auth / authz / sessions / tokens co-occur in prose,
  so they pack into one neighborhood. High recall, **mushy identity boundaries** — which is exactly
  why embeddings can't *canonicalize* concepts (`auth` vs `authn` vs `authz` won't separate).
  Relatedness and distinguishability trade off.
- *Code clusters on surface form, not behavior.* Two functions that do the same thing with
  different identifiers land far apart; two that share boilerplate/imports/naming land close though
  behaviorally unrelated. (Our own `__init__`-matched-by-structural-vocabulary result is this.)
  The axis code relates on is nearly orthogonal to the one we care about.
- *concept↔code is the worst case.* Prose-about-a-thing and the code implementing it share almost
  no surface tokens → different regions → R1's 0.42. Not a tuning failure; a modality projection.

**Context window (attention, live forward pass).** Not cosine over a frozen map — attention
recomputes token-pair relationships *contextualized* by neighbors. "broker" beside "credential"
and "confused deputy" gets an activation already carrying the conceptual frame. So a model that
**reads** the concept and the code in one window can link them even when their embeddings are 0.42
apart. The model can *relate* concept↔code in-context far better than it can *retrieve* one from
the other.

**Geometric restatement of the whole architecture:**
> embeddings **point**, attention **bridges**, the deterministic spine **carries identity**.

## Route each job to the geometry that can do it

| altitude | identity mechanism | embedding role | attention role |
|---|---|---|---|
| **leaf** — code, intra-language | AST `(name, source_file)`, content-addressed id (deterministic) | none for identity; same-name disambiguation guard only (≥0.82) | — |
| **mid** — intra-project code↔doc | code-anchored merge + name/path resolution (ADR-0017) + contextual extraction (ADR-0016) | collision-guard 2nd signal | the commit-time link constructor (below) |
| **apex** — cross-project / cross-language *concept* | **curated portfolio ontology**, grounded into via ADR-0016-style injection | **none** (concepts too smooth to separate) | ground each implementation to an ontology concept, in-window |
| **query boundary** — agent orientation (`find`) | — | **ranking** NL-query↔passage (no absolute threshold) — the one regime latent space was built for | the agent's own reasoning, post-retrieval |

The load-bearing line: **keep cosine out of the graph's joints.** It belongs at the query door, not
in construction.

## Worked example: one concept, two languages

A UI panel — call the concept **`panel`** — exists as a rendered **component in a TS frontend**
(`Panel.tsx`) and as a **class in a Python backend** (`panel.py`). Same concept, two mechanically
different implementations. This is the apex problem in miniature — and note it appears **inside a
single project** (a webapp + its backend), not only across projects. The "natural seam" non-goal 2
waited for has therefore *already emerged* the moment a product spans two languages.

**What the graph does today (traced through `entity_resolver.py`):**

1. `normalize` collapses both names to one cluster key.
2. `(name, source_file)` keying yields **2 distinct code defs** → the **collision-guard branch**.
3. The guard *refuses to fuse distinct code symbols* — each stays its own node, **no edge between
   them**.
4. The base is added to `ambiguous_bases` and **withheld from `name_index`**, so any relationship
   naming the panel without a file path is **dropped, never guessed**.
5. Docs either fold into one def or become an **orphan concept node with no edge to either**.

→ **Three islands, zero bridge.** The collision guard is not neutral here; it *actively prevents*
the bridge — correctly, because within one language fusing two same-named classes corrupts identity.

**How it should bridge (concept-as-hub at portfolio scope):**

```
[concept: panel]                    portfolio-scoped, ontology-anchored id (concept|panel)
   ├──implemented-by──> [code: Panel @ frontend/Panel.tsx]  kind=component lang=ts
   ├──implemented-by──> [code: Panel @ backend/panel.py]    kind=class     lang=py
   ├──described-by────> [doc: panel-design.md]
   └──decided-by──────> [ADR-00xx]
```

Two mechanisms draw the `implemented-by` edges, **cosine in neither**:

- **Deterministic alias-grounding (cheap spine).** The ontology entry for `panel` carries a curated
  alias list; a code def whose normalized name matches an alias gets an `implemented-by` edge — no
  LLM, no embedding. The ontology's alias list *is* the canonicalizer (Road B).
- **Attention link-constructor (tail).** When names diverge across languages (`PanelStepper` vs
  `PanelState`) or a doc calls it "the wizard," name-match misses and cosine can't recover (R1). Put
  candidate ontology glosses + the symbol + surrounding prose in one window, constrain output to the
  real concept list, propose-and-drop.

**Why a hub, not a `Panel ←→ Panel` peer edge:** O(N) not O(N²) as implementations multiply; the hub
holds the *meaning* (a peer edge has nowhere to put it); and it is a genuine higher *altitude*, not a
sideways link — which is what "compose context across altitudes" means.

**Concrete code change:** in the resolver's ambiguous branch, when a code def (or a dropped endpoint
name) matches an **ontology alias**, don't drop it — mint an `implemented-by` edge to the
portfolio-scoped concept node. The guard still refuses to fuse the two code defs *with each other*;
both now point *up* to the shared concept. Requires a portfolio concept registry loaded into
`resolve()`. This is also the first real delivery of ADR-0009's cross-scope edges — anchored on a
curated concept, not the entity-merge that measured 0%.

**Reframed density metric (replaces the THEORY:68 / ADR-0009 entity-merge metric):** not "% of
relationships spanning ≥2 scopes" but **"% of ontology concepts with implementations in ≥2
languages/scopes."** `panel` with both a `.tsx` and a `.py` implementer is one bridged concept —
directly measurable, directly falsifiable.

## Two independent roads to one conclusion

The apex needs a *curated, deterministic-ish* concept spine — not an embedded one — and we reach it
from two unrelated directions:

- **Road A (cross-language, R3):** no shared symbol exists, so the concept is the only possible
  bridge between a Python and a C# implementation.
- **Road B (latent geometry):** concepts cluster too smoothly for embeddings to draw identity
  boundaries, so embedding-clustered concepts can never be a clean canonicalizer.

Convergence from two roads is why this is load-bearing and not a hunch. The mechanism: a portfolio
ontology the operator authors (the one vocabulary that can't be derived, because it *is* the
portfolio's point of view), with extraction grounding against it — the ADR-0016 move, but injecting
canonical **concepts** as context the way we now inject code **symbols**.

## The tail-fixer, sharpened: a commit-time link constructor

The conceptual doc→code links that name-matching misses (ADR-0017 dropped ~3,761 relationships
whose endpoints were conceptual phrases) cannot be recovered by **retrieval** (R1: latent space
won't bridge), but can be by **a model reading both in one window** (attention will). The fixer is
therefore not a better embedding — it's a constructor:

> scope-bounded code symbols + the doc chunk → one context window → propose grounded links →
> resolve-or-drop against the real symbol list.

Four things the naive version (and the conversation that prompted this) glossed:

1. **Chicken-and-egg.** You can't co-locate "the right code" with a doc when finding that code is
   the goal. Resolution: **coarse structural recall gathers candidates** (scope membership,
   imports, call graph — cheap, high-recall), **attention does precision**. The embedding isn't
   even the pointer here; *scope attachment* does the gather.
2. **Cost coupling.** This *is* ADR-0016 re-ingest generalized — measured at ~11× cost / ~5× wall
   time on a backend with no prompt caching. Viable only with (a) caching and (b) a tightly scoped
   injected symbol set. Geometrically right, economically constrained.
3. **propose-and-drop vs constrained decoding.** Prompt-instruct + drop-the-unmatched is
   precision-safe (our current resolver behavior). Logit-masking output to the real symbol set buys
   recall but can force *wrong-but-real* links — confabulation (ADR-0009) in a new costume. Lean
   propose-and-drop; revisit only if recall is the measured bottleneck.
4. **It's TODO variant (B) made safe by construction** — confabulation-bounded (output constrained
   to real symbols) and scale-bounded (scope-limited candidate set, not all-pairs LLM judging).

## Falsifiable prediction (the experiment that would settle it)

Take the conceptual relationships ADR-0017 dropped. Run the link constructor (scope symbols + chunk,
constrained output) over a hand-labeled sample. **Prediction:** meaningful recall at high precision,
where θ=0.78 cosine recovered ~0. If it doesn't, either the "attention bridges" claim is wrong or
the structural recall is too coarse to put the right code in the window. Either way we learn which.

## What graduates, and when

- **To THEORY now (no code):** sharpen open-question :56 — *cross-**language** implementations
  share no symbol, so the apex altitude needs a concept-identity mechanism that code-anchoring
  structurally cannot provide.* Candidate new tenet: *route identity to the deterministic spine,
  similarity to the query door, bridging to the context window.*
- **To an ADR when the seam is real** (a 2nd language or 2nd project actually lands — the
  "natural seam" non-goal 2 waits for): the curated ontology + grounding, and the commit-time link
  constructor.
- **Stays scratch here:** everything above until measured. Per the project's own discipline,
  building the ontology speculatively would itself violate the "natural seams" rule.

## Design rule: derived, not annotated

**Annotations may boost the kernel; they must never be load-bearing.** If a concern (e.g.
concurrency) is findable only because an engineer hand-tagged it (`//parallelism …`), the system
collapses into a comment-convention linter that `grep` + team discipline already approximates — and
it depends on human tagging discipline, the exact thing that rots (cf. the HANDOFF incident).

The defensible territory is the knowledge good practice *can't* reach locally: a concern with no
single name (`asyncio` / `Lock` / `FOR UPDATE` / retry are one concern, many mechanisms — naming
names symbols, not concerns), scattered and cross-language, where local clarity doesn't compose into
global concern-navigation (= the thesis). So: derive concept→code from code-as-written + the curated
ontology; **reward** conceptual clarity (good names/docstrings/ADRs → cheaper, sharper
classification) without **requiring** a proprietary syntax. Dependency runs
kernel-derives-from-code, never code-must-feed-kernel. The day it flips, "good practice would just
solve this" becomes true.

## Ontology design — prior-art-informed (2026-05-29)

From a research pass over feature-location, industry code KGs, ontology engineering, AOP, and
LLM-era grounding. Bottom line: the one field that tried our exact problem corroborates our hardest
finding, and the apex pattern is mature in the neighboring field even though no code KG has it.

**What the prior art confirms**

- **Feature/Concept Location** (SE research, ~2005–2019; Dit/Poshyvanyk survey 2013) is *our exact
  problem* — mapping a human concept to scattered code. Its 15-year settled conclusion: text/IR
  similarity alone **fails** on the **vocabulary-mismatch problem** (Furnas: two people name a thing
  the same <20% of the time) and must be fused with structure. **Independent corroboration of our
  0.42.** The **SITIR** pattern (Liu et al., ASE 2007) — IR used only to rank *within* a
  structurally-determined candidate set — is exactly our coarse-recall→precision pipeline.
- **No industry code KG models concepts above symbols** — Kythe, Glean, SCIP/LSIF, CodeQL, Stack
  Graphs are all symbol/reference graphs. Our deterministic spine *is* the state of the art; the
  concept apex is novel (no incumbent to copy, nobody solved our rot/granularity for us). Kythe's
  one-global-schema vs Glean's per-language → for cross-cutting, language-agnostic concepts, use
  **one shared vocabulary**, not per-project dialects.
- **AOP** validates the entity/aspect split: class-vs-aspect = "a symbol IS this" vs "this cuts
  across symbols" (scattering + tangling). An aspect-concept's grounding is a **pointcut** — a
  predicate selecting symbols — which is exactly what `concept_classify.py`'s LLM judge is.
- **Closed-vocabulary constrained generation** is the documented strongest hallucination guard, and
  the best LLM ontology-typing systems (LLMs4OL) constrain output to a candidate set — validating
  the propose-and-drop in `concept_classify.py`.

**Design decisions this drives**

1. **Adopt the SKOS shape** (don't invent a schema): `prefLabel` + `altLabel` (our alias list is
   literally altLabels), `definition`/scopeNote (added to the aspects), `broader`/`narrower`
   (granularity hierarchy), `related`. (w3.org/TR/skos-reference)
2. **Granularity test = separability under grounding** (AOP): "concurrency" is one concept or four
   depending on whether the grounder can select recognizably *different* symbol sets. If the LLM
   judge can't tell `locking` from `async-scheduling`, they're one; if it can, split via `narrower`.
   Operational, not a priori — answers gap 7.
3. **Cold-start = propose-then-curate, mine STRUCTURE not prose.** Seed candidates from identifier
   tokens / path segments / module names (vocab the operator definitely uses) + the doc-mention
   ranking the discovery pass already did; LLM nominates labels + aliases + draft hierarchy; operator
   accepts/edits. Do NOT mine prose for concepts then embed-match (the 0.42 path). Never auto-adopt.
   (AIO / ODK "AI-assisted curation" precedent, arxiv 2404.03044) — answers gap 8 cold-start.
4. **Rot model — make rot visible, don't prevent it:** entity-concepts **auto-heal** (deterministic
   alias-match breaks on rename/delete → surface "concept X grounds to 0 symbols" as a FreshnessGate
   signal); aspect-concepts use content-addressed caching, re-classify only changed symbols; the real
   rot surface is **new-vocabulary drift** → periodically LLM-nominate over newly-added symbols into a
   human review queue. Never auto-mutate the vocabulary — answers gap 8 maintenance.
5. **LLM proposes concepts well, relations poorly** — trust LLM membership (cheap); human-review the
   `broader`/`narrower` taxonomy.

**Caution this sharpens (routing table):** don't let query-time ranking quietly *become* the
concept→code grounding we rejected at index time. Grounding (identity) stays strictly curated;
embeddings only **re-rank within an already-grounded candidate set** (the SITIR discipline).

## H2 measured findings (2026-05-29) — concept kernel vs grep

Gap-1 (does the concept layer earn its keep over prose+grep?) run twice on a real ~7k-entity
single-language corpus, scored against verified ground truth. Corpus-specific numbers live in a
local benchmark; the generic findings:

- **Round 1 (concepts NOT materialized; kernel used find/overview):** kernel pulled ~2× the
  documentation but cost ~40% more tokens *and guessed a wrong file path*. grep was more precise.
  Materialization absent → the kernel is *worse* than grep.
- **Round 2 (concepts materialized as a `resolve-concept` hub surface):** kernel flipped to **~4×
  faster, ~2× fewer tokens, zero hallucinated paths** (exact paths come from the hub). **But grep
  still won accuracy** — 100% recall every question vs the hub's ~67–83% on entity-concepts and
  ~67% recall / ~30% precision on the noisiest aspect-concept.

Conclusions (these temper the candidate thesis — don't overclaim):

1. **Materialization is the unlock.** Unmaterialized, the concept layer loses to grep on every axis.
   Materialized, it wins the axes it can win.
2. **The proven win is speed & cost, NOT accuracy.** Entity-concept hubs are a *fast, cheap, ~80%
   orientation* — excellent for "point me roughly," not yet a replacement for exhaustive search.
3. **"The hub is only as good as what's in it."** Entity-concept hubs (deterministic path +
   governing ADRs) are strong. Aspect-concept hubs lose on **both** axes:
   - *precision* — they inherit the classifier's low precision (false-positive participants);
   - *recall* — keyword-in-description prefilter **misses real participants whose text doesn't
     contain the keyword** (e.g. a shared-state coordinator not named "lock/semaphore");
   - and both are **blind to code-level gotchas** (legacy duplicates, "looks-like-X-but-isn't"),
     which live in code/comments, not the doc-derived hub — exactly where grep (reading source) won.

Experiment 1 — **structural recall** (scan source for the concern's primitives/imports → union with
keyword recall → strict judge). **Result (2026-05-29): didn't move the needle, but diagnosed the real
bottleneck.** Recall gain was narrow (error-handling +4, incl. the `retry.py` miss; concurrency/auth/
eval +0) and precision stayed flat/noisy. Why: structural recall *surfaced* the missing candidates,
but **the judge reasons from name+description, not source**, so it rejected the structurally-evident-
but-description-silent ones (a circuit breaker with a module-level shared `_circuit` wasn't confirmed
as concurrency because its docstring doesn't say so — and it arguably belongs under error-handling
anyway). It *helped* only where a candidate had **both** a structural hit and a confirmable
description (`retry.py`).

**The pinned root cause:** the entire aspect pipeline reasons from **descriptions/docs, not source** —
the same root cause as the H2 finding that the hub was blind to code-level gotchas. More candidates
can't fix a judge that can't see the code.

Experiment 2 — **give the judge source evidence** (pass the matched source lines, not just the
description, and have it emit a code-level gotcha). **Result (2026-05-29): worked on all three axes.**
- *Recall ↑* — the description-silent coordinators the Exp-1 judge rejected now get confirmed
  (a module-level shared circuit breaker); structural-only confirmations rose (auth +5, err +6).
- *Precision ↑ (true)* — the judge, now seeing source, **dropped the empty false positives** (files
  with 0 coordination primitives that Exp-1 kept) and ~75% of confirmed participants now contain a
  real primitive (vs the earlier noise).
- *Gotchas* — genuine source-derived warnings now populate every aspect hub ("cancellation timing
  affects tool ordering", "concurrency limit depends on semaphore scope") — the H2 Q3 capability the
  doc-derived hub structurally lacked. Closed by the judge reading code.

**Lesson:** the bottleneck was never recall — it was that *every stage reasoned from descriptions*.
Putting source at the judge (not just recall) is what "fuse IR with structure" means here, and it's
why grep won: it reads code. The residual imprecision is now a **definition** problem (the judge
can't separate async fan-out from shared-state coordination because the concept definition lumps
them — AOP "separability": split the concept or accept the broad reading), not a pipeline problem.

## Parking lot — capture & move past (2026-05-29)

Ideas worth remembering, deliberately NOT acting on now. Focus stays on aspect structural-recall.

- **Hybrid kernel-then-grep (the H2 resolution).** Don't pit the concept hub against grep — compose
  them. The hub gives fast orientation + exact path + governing ADRs; it then *hands off to
  grep/glob* for the precise call-site and the code-level gotchas it structurally can't carry (H2
  showed each wins a different axis). The production answer is the hub pointing grep at the right
  files, not either alone.
- **Dependency ontology.** Third-party imports (asyncio, numpy, httpx, pydantic, …) as a concept
  axis, each mapping to a capability/field. The *opposite* of aspect-concepts: imports are
  AST-deterministic → **perfect recall and precision, no LLM judge**. And imports ARE the structural
  recall signal (files importing asyncio = the concurrency candidate set) — so dependency-concepts
  both stand alone AND seed aspect-concept recall. Cheap, deterministic; revisit right after
  structural recall.
- **Wire concepts into the graph's vector store**, not just views — so MCP `find` surfaces concept
  hubs directly (today they're only readable as files).
- **Concept materialization into the real ingest→materialize pipeline** (vs the spike scripts) —
  the productionization step, gated on entity-concepts proving out.
- **Code-derived gotchas** — feed hub `gotcha`/notes from implementation (docstrings, top-of-file
  comments, legacy/duplicate markers), the thing grep beat the hub on (H2 Q3).
- **Confidence (ADR-0015) on concept edges** — surface per-edge confidence so low-precision aspect
  participants are visibly hedged rather than asserted.

## Unexamined gaps (2026-05-29)

The remaining ~10%. Most resolve only by measurement, not more reasoning — they are the shoot-list
for the spike spec'd in `thoughts-spiked.md`. Hardest-first.

1. **Does the concept layer earn its complexity over "good AGENTS.md + attention"?** The existential
   one. If attention bridges concept↔code in-window and per-scope prose already names the concerns,
   an agent that *reads + reasons* may answer "where's concurrency" at ~80% for near-zero marginal
   cost. The graph's defense: prose is per-scope and **doesn't compose** (the thesis), isn't
   traversable, and is what *generates* good prose in the first place. But the marginal value over a
   prose+grep baseline is **unmeasured**. The spike must include that baseline as a control.
2. **We solved nodes; the value (and the failures) live in edges.** Five turns on node
   canonicalization, almost none on edges — yet orientation *is* traversal, and ADR-0017 dropped
   **3,761** relationships (conceptual-phrase endpoints). Edge type provenance, edge correctness,
   and traversal density are the harder half and barely touched.
3. **Aspect-classification has no deterministic guard, and no ground truth to catch it.** The link
   constructor could constrain output to a real symbol list; "does this participate in concurrency?"
   has nothing to constrain against, so its precision/recall is unbounded. A false-positive concept
   node is *worse than none* (misleads the bug-chaser). And the correct map is the engineer's tacit
   knowledge — so validation is circular. Resurrects ADR-0015 (confidence), more needed here than at
   the structural layer.
4. **"Kept in sync at commit time" is a far bigger claim for concepts than for code.** Structural =
   deterministic-from-source, re-derive identically. Concept-via-classifier = LLM-derived,
   *non-deterministic*, expensive; re-runs may flip edges unrelated to the change; deleting the only
   implementer silently orphans the concept. The freshness invariant doesn't hold uniformly.
5. **"Resolves immediately" is over-claimed, and query→concept lookup is unsolved.** The real
   question is contextual ("*which* concurrency caused this duplicate write?"), not categorical —
   returning all 14 sites is a smaller haystack, not an answer. And NL-query→ontology-concept is the
   mushy-match problem returning (saving grace: matching against a *small curated set* is the one
   regime embeddings are good at — but the agent must first discover the vocabulary).

Lower-tier (real, won't reshape the thesis):

6. **Topology / many-to-many.** One symbol touches many concepts → dense bipartite symbol×concept
   graph. Hairball or sparse-and-crisp? Measurable, unmeasured.
7. **Granularity.** Is "concurrency" one concept or four? Too coarse → useless 200-node answers; too
   fine → authoring explodes, queries miss. The human author now bears the boundary-drawing cost
   embeddings couldn't do.
8. **Cold-start & whose-theory.** Where does the first ontology come from (high authoring friction
   kills adoption), and — Naur's own point — theory belongs to the *group*; a team has contested
   vocabularies. Out of scope for solo v1, real the moment it isn't.

## Open sub-questions

- Is scope membership enough coarse recall, or is a structural pre-filter (imports / call graph)
  needed to get the right code into the window?
- Measure propose-and-drop vs constrained decoding precision/recall on the dropped tail.
- Would a *code-specialized* embedding narrow the 0.42 gap enough to matter — or is the modality
  gap fundamental, making attention the only right tool? (Suspect the latter.)
- Ontology maintenance: who authors it, how does it stay fresh, does it become the new rot surface
  the way stale docs did (the HANDOFF incident)?
