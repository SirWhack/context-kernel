# ADR-0017: Code-anchored within-project entity resolution (identity merging)

**Status:** Accepted
**Date:** 2026-05-29

## Context

[ADR-0009](./0009-cross-scope-relationships-via-source-id.md) specified cross-scope linkage via LightRAG's *native cross-document entity merging* (mechanism A) plus source-ID traversal (B), and named it "the single biggest thesis risk" — tracked by THEORY.md's thesis-load-bearing open question, with an S0 exit criterion of **≥15% cross-scope edge density (<5% = stop)**.

Measurement on a real corpus (Ticket Agent: 7,973 entities, 7,666 relationships) found that density is **0%**. Root causes:

1. The shipped `LightRAGStore` is a hand-rolled JSON+NetworkX store — it never implemented mechanism A's entity merging. `_derive_entity_id = sha256(name:kind:source_file)` does the *opposite*: the same symbol in two files becomes two nodes (e.g. `query_tickets` ×8, `TurnPanelResponder` ×7).
2. Relationship resolution in `_resolve_raw_entities` is **per-chunk**; cross-file targets fall back to `_derive_entity_id(target_name, "unknown", target_name)`, a phantom ID that matches nothing. `get_neighbors` looks up strictly by ID, so the edge is dead.
3. ADR-0015 (confidence) and ADR-0016 (contextual extraction) were accepted but never implemented — so the doc extractor is blind to code entities and emits descriptive relationship targets; only **~5%** of doc relationship targets name a real code symbol.

By the project's own criterion (0% < 5%), this is a stop-and-adjust. The fix is the deferred `EntityResolver` (ARCHITECTURE §6), which ADR-0009's revisit-clause #3 anticipated.

## Decision

Introduce an **EntityResolver** pass that runs after all raw entities/relationships are collected (across structured + chunk phases) and before embedding/upsert. It performs **code-anchored, within-project identity merging**:

1. **Cluster** raw entities by a conservative normalized name (casefold; collapse non-alphanumerics; drop articles). Aggressive suffix-stripping ("Protocol"/"ABC") was measured to add ~nothing (534 vs 536 cross-edges) and is rejected as added risk.
2. **Code-anchored canonical node.** When a cluster contains exactly one code definition, it is the canonical node (authoritative `kind`); doc/ADR/test entities fold in as `aliases` + `sources` (provenance) + secondary `kinds`. Pure-doc clusters become concept nodes. A *distinct code definition* is a unique **(name, source_file)** — so a module `root` and a class `Root` in the same file remain separate nodes and are never collapsed by case-folding.
3. **Collision guard (precision over recall).** When a normalized name has **>1 distinct code definition** (e.g. two `Client` classes in different modules, or a module + same-named class), each definition stays its own qualified node. Non-code members attach to a specific definition **only when a second signal agrees** — embedding cosine ≥ θ (primary) or shared scope — otherwise they remain a concept node. No blind bare-name fusion of distinct symbols.
4. **Relationship resolution** maps every endpoint name to a canonical ID via the merged index (exact surface → normalized → same-source-file disambiguation for ambiguous names). A **file-path-shaped target** (`src/bot/agent.py`, or a unique basename) resolves deterministically to that file's module node — no LLM, no embeddings — recovering the slice of the tail where the LLM cited code locations verbatim. Endpoints that were never an entity, or that stay ambiguous, are **dropped, not phantom-minted**. Stoplist (`__init__`, `main`, `run`, `setup`, `__call__`, `conftest`) never merges across files.
5. **Within-project only**, per THEORY non-goal 2. Canonical IDs are identity-derived, which ARCHITECTURE §6 explicitly sanctions ("entity resolution may regenerate IDs — only `graph_commit` is stable").

Staged rollout: **S1+S2** (merge + resolve on current extractions, this ADR) → **S3** implement ADR-0016 (re-ingest docs with code context, recovering the ~5%→higher target-match tail) → **S4** ADR-0015 confidence + embedding-assisted linking for the long tail.

## Measured evidence (S1+S2 prototype, no re-ingest)

| | shipped | after merge+resolve |
|---|---|---|
| nodes spanning code **and** docs | 0 | **142** |
| cross-altitude edges (code↔doc) | 0 | **534** |
| canonical nodes | 7,946 | 7,040 (12% collapse) |

`TurnPanelResponder` correctly unifies `src/bot/turn_panel.py` + CONTEXT.md + docs/16 + ADR-0011 + ADR-0012 + plans — code, glossary, prose, and two decisions as one node. 3,761 relationships still drop (endpoints are conceptual phrases) — the S3/ADR-0016 target.

## Considered options

- **Bare-name merge (no collision guard).** Maximum connectivity but fuses distinct symbols (`Client`/`Client`). Rejected — corrupts identity, the opposite of "authority on context."
- **Concept-hub separate from code.** A concept node relating-to a separate code node. Rejected — creates concept/symbol pairs to keep in sync; code-anchoring is simpler and keeps code as ground truth.
- **Embedding/LLM semantic merge as the primary mechanism.** Rejected as primary — ADR-0009's "confabulation engine" risk. Confined to the collision guard's second signal and S4, behind thresholds + recorded evidence.

## Consequences

- `Entity` gains `aliases`, `sources`, and reconciled `kind` (code-authoritative + tags); IDs become identity-derived. Touches `protocol.py`, `lightrag_adapter.py` (serialization + name index), `ingester` (collect-then-resolve restructure), `materializer` (render super-nodes + cross-scope relationships — where the thesis finally shows in AGENTS.md).
- Re-ingest is the migration (`rm -rf .context-kernel`), consistent with ADR-0008.
- Mechanism B (source-ID traversal feeding scope summaries) becomes implementable for free once nodes carry `sources`.

## When this should be revisited

- The collision guard's second signal proves too lossy (many correct doc↔code links deferred) → bring S4 embedding linking forward.
- After S3, if target-match recovery is still low, re-grill ADR-0016's prompt design.
