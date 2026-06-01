# ADR-0027: Resolve-time reference grounding — recall-then-judge for dropped doc→code edges

**Date:** 2026-06-01
**Status:** Rejected (superseded by deterministic `path:Symbol` resolution — see Outcome)

## Outcome — rejected on evidence (live re-ingest, Ticket Agent, 2026-06-01)

Built, shipped behind a judge, and measured on the real graph. **It bound 0 of 412 dropped
semantic edges**, and a per-drop diagnostic (best code candidate + cosine + verdict for all 412)
showed *why* — the premise was wrong on two counts:

- **The judge never even ran.** Nothing cleared the cosine gate: best-candidate cosine maxed at
  **0.769** (an exact-name match that's ambiguous anyway). Embedding-recall of a short name-phrase
  against a verbose code-entity description structurally can't clear threshold. The ~1,491 judge
  calls in the ingest were `judge_aspect` from *concept* grounding, not this pass.
- **95% of the drops are *correctly* dropped.** Categorizing all 412: **304 ambiguous/stoplist**
  (`main` ×161 — *which* `main`? never guess, ADR-0017), 33 no-referent, 26 directory targets,
  24 ambiguous code names, 4 external libs. The premise — "doc *prose* failing to reach code
  *symbols*" — does not match the data; the real failures are **malformed/ambiguous/external
  targets**, which must drop.
- **The genuinely-recoverable 5% (21 edges) is not semantic at all.** They are
  `path.py:Symbol` (13) and file-path (8) targets the doc extractor echoed from the ADR-0016
  code context — recoverable by **deterministic parsing**, not embedding+judge.

**Decision reversed:** the reference-grounding pass, `judge_reference`, the `inferred`/downweight
plumbing, and `DroppedEndpoint`/`groundable_drops` are removed. The recoverable tail is handled by
**deterministic `path:Symbol` / `path:line(-range)` endpoint resolution** in the EntityResolver
(`_resolve_endpoint`): a `path.py:Symbol` resolves to that symbol's definition in that file, a
line ref to the file's module — no embeddings, no LLM, no guessing. This also dovetails with the
line-anchoring/CodeSpan work (`def_line`). The lesson: **diagnose the drop population before
building recovery machinery** — most "lost" edges were never lost, and the rest were a parsing
gap, not a semantic one.

The original proposal is retained below for the record.

---

## Context

The kernel's value is fresh *documentation*, and the doc layer carries the **theory** (why):
`realizes`, `governed-by`, `motivates`, `addresses`. Those edges are authored by the LLM
extractor as **free-text** endpoint names. The EntityResolver (ADR-0017) then binds each
endpoint *deterministically* by normalized-name match — **extract-then-guess**, not
select-from-catalog. When the LLM names a code thing as a **phrase** ("the agent loop", "the
ReAct master loop") rather than a symbol, no node matches and **the edge is dropped, not
phantom-minted**. ADR-0017's own prototype measured **3,761 such drops** ("endpoints are
conceptual phrases") and named recovering them the S3/ADR-0016 target.

Audit of the current Ticket Agent graph (commit `308c7221`) confirms the seam is still open:

- Cross-altitude (code↔doc) typed edges that *did* bind: `realizes` 487, `governed-by` 314,
  `motivates` 184, `manifested-by` 167. These are the theory-to-code links that make the graph
  worth reading — proof the payload is real.
- The embedding safety-net (`semantic_linker`, ADR-0017 Stage 4) was **defined but never wired
  and never tested** — it emitted **0 edges**. So there was **no recovery at all** for dropped
  phrase-edges; doc theory that failed to name a symbol simply vanished. (This ADR removes that
  dead module; its *pure-discovery* intent — linking code↔doc that no edge ever asserted — is a
  separate future feature, distinct from recovering authored-but-dropped edges here.)

Three faces of the binding fragility, in priority order:

1. **Drop** — a doc semantic edge names a phrase → matched no node → dropped. *The big loss.*
2. **Weak-link** — `semantic_linker` would patch some drops as **untyped** `related`, losing the
   `realizes`/`governed-by` the doc actually asserted. (Currently producing nothing anyway.)
3. **Mis-bind** — a structural edge lands on prose. Largely closed by ADR-0026 (methods).

ADR-0017 deliberately kept the LLM *out* of resolution (ADR-0009's "confabulation engine"
risk). But ADR-0025 §4 already crossed that line for aspect-concepts with **recall-then-judge**
— coarse recall gathers candidates, an LLM **judge** confirms each, evidence is recorded. That
machinery (`ground_aspect_concepts`, `LLMSummarizer.judge_aspect`, content-addressed verdicts)
is in production. This ADR points the **same proven pattern** at edge endpoints.

## Decision

Add a **resolve-time reference-grounding pass** that recovers dropped doc→code semantic edges
by recall-then-judge — keeping free-text extraction, grounding only the unresolved tail.

1. **Resolver surfaces drops.** `resolve()` returns the **dropped** `ExtractedRelationship`s
   (today it only counts them). Pure change — no new I/O in the resolver.

2. **Filter to groundable drops.** Keep a dropped edge only when **exactly one endpoint
   resolved** (a real node) and the other is an unresolved phrase, **and the kind is semantic**
   (`realizes`, `governed-by`, `motivates`, `addresses`, `references`). Structural edges
   (`calls`, `imports`, `contains`, `inherits`) are **excluded** — they bind deterministically
   or are correctly dropped (external libs); grounding them would re-open the ADR-0026
   conflation. This bounds both blast radius and cost.

3. **Recall.** Embed the unresolved phrase; cosine top-k against **code-node** embeddings
   (reusing `semantic_linker`'s vectorized k-NN); gate at a cosine threshold. Recall is cheap
   and LLM-free.

4. **Judge.** `LLMSummarizer.judge_reference(kind, edge_description, phrase, candidate_name,
   candidate_evidence) -> bool` — a YES/NO confirm, content-addressed exactly like
   `judge_aspect`. The first candidate the judge confirms binds the **typed** edge
   (`source → candidate`, original kind). Capped per edge; a global cap logs loudly (no silent
   truncation).

5. **Provenance, not identity.** A grounded edge is **tagged** (description suffix + the cosine
   as evidence) so it is distinguishable and auditable, and scored below a deterministic edge
   (it is inferred, ADR-0021's semantic family). The pass **only adds edges — it never merges
   identity** (discovery is too fuzzy; same stance as `semantic_linker`).

6. **Wiring.** Runs in `_apply_concept_layer`'s neighborhood, gated on
   `getattr(summarizer, "judge_reference", None)` — absent judge (tests, headless) → pass is a
   no-op, exactly like aspect grounding. Tests use a fake judge; no LLM in the suite.

### Why this respects "docs take priority" *and* code-anchoring

This is the doc→code seam (ADR-0026's "two axes"). The edge is **authored by the doc** — its
*kind* and *intent* come from the prose (authority axis: docs win). Its *endpoint* is a code
symbol (identity axis: code-anchored). Reference grounding binds a **doc-authored typed claim**
to the **code node it is about** — it is the mechanism by which doc theory *attaches to* code
and thereafter stays fresh against it (drift, ADR-0020). It strengthens both axes at once.

## Considered options

- **Extract-time grounded selection** (feed the LLM the code catalog during extraction, have it
  reference real entities). Higher ceiling — binding happens where the prose is understood — but
  a larger change to the extractor (ADR-0016), per-chunk catalog retrieval, prompt bloat, and
  id-hallucination validation. Deferred; resolve-time is the surgical first move and reuses
  shipped machinery.
- **Revive/lower-threshold the `semantic_linker` instead.** Rejected — it produces *untyped*
  `related` edges (face #2), drowns precision in fuzzy cosine with no judge, and was dead code
  anyway; the "confabulation engine" risk is exactly what the judge exists to gate. Removed.
- **Ground structural edges too.** Rejected — re-opens ADR-0026 conflation; external-library
  calls have no code node and *should* drop.
- **Bind to the top-cosine candidate without a judge.** Rejected — that is the unguarded
  embedding merge ADR-0009/0017 warn against; the judge is the precision half (recall alone was
  0.35 precision in the aspect spike).

## Consequences

- **Recovers typed doc→code theory** that is currently dropped — the graph's read-value rises
  where it matters most (the *why* attached to the *what*).
- **Adds judge calls on the dropped semantic tail only.** Bounded by: semantic-kinds-only,
  top-k recall before judge, per-edge + global caps, content-addressed verdict cache (unchanged
  edge never re-judged). Order of magnitude: the dropped semantic edges, not all edges.
- **A new edge provenance class** (grounded-by-judge) — tagged in the edge description and
  **downweighted** at scoring (`ResolvedRelationship.inferred` → `weight ×
  scoring.INFERRED_EDGE_DISCOUNT`, 0.6), so a judged edge ranks below the same kind asserted
  deterministically.
- **Re-ingest is the migration** (ADR-0008); first real ingest also yields the precise drop /
  recovery numbers (the resolver now returns drops, so they are measurable).

## When this should be revisited

- If grounded edges prove low-precision in audit, raise the cosine gate or strengthen the judge
  prompt (evidence: record cosine + verdict per edge from day one).
- If the dropped-edge volume makes judge cost dominate ingest, **graduate to extract-time
  grounded selection** (the deferred option) so binding happens once, in-context, without a
  separate judged recall pass.
- If **pure-discovery** linking is wanted (code↔doc that no edge ever asserted — the removed
  `semantic_linker`'s intent), add it as a *separate, judged* pass; reference grounding (typed,
  judged) already covers the authored-but-dropped case and should remain the doc→code path.
