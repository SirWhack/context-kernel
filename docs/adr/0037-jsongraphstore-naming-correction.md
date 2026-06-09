# ADR-0037: Retire the LightRAG claim — JsonGraphStore as the honest v1 backend

**Date:** 2026-06-09
**Status:** Proposed (corrects ADR-0004's realized state; amends ARCHITECTURE §1.1/§2.1)

## Context

ADR-0004 selected LightRAG as the graph backend, and ARCHITECTURE.md still records it as
settled tradeoff 1, including "pluggable storage (NetworkX default; Neo4j / Postgres / Milvus
available without code changes)." The shipped reality, established by ADR-0017's measurement,
is different: `LightRAGStore` is a **hand-rolled JSON + NetworkX store** — LightRAG's
extraction, merging, and storage machinery were never used, and the pluggable-storage claim
does not describe the code. The class name and the architecture document now assert a
dependency that doesn't exist.

This is doc drift inside the system built to prevent doc drift. The research record says
nothing of value was lost — LightRAG's native dedup is documented as exact-key-match-only
(LightRAG issue #1631; arXiv:2510.14271 finds LightRAG/GraphRAG/HippoRAG all leave duplicates
unresolved), and the kernel's own EntityResolver (ADR-0017) replaced exactly that weakest
link. But the record should say what is true.

One adjacent implementation fact belongs in the same correction: `_cosine_sim` is pure-Python
`struct.unpack` + loops over every chunk per query, in the `find` hot path, ahead of ~37%
entity growth from method nodes (ADR-0026).

## Decision

1. **Rename `LightRAGStore` → `JsonGraphStore`** (module `lightrag_adapter.py` →
   `json_store.py`), keeping an import alias for one release. The `KnowledgeStore` protocol —
   the actual Parnas seam — is untouched.
2. **Amend ARCHITECTURE.md** §1.1 settled tradeoff 1 and §2.1: the v1 backend is a hand-rolled
   JSON + NetworkX store behind the `KnowledgeStore` protocol; LightRAG was evaluated
   (ADR-0004) and its selection is **superseded by the shipped store** — backend swaps remain
   possible through the protocol, but no pluggable-storage adapters exist today. ADR-0004
   gains a status note pointing here (the decision record stays; its realized state is
   corrected).
3. **Vectorize similarity while touching the file:** load chunk embeddings into one
   L2-normalized `float32` numpy matrix at store init; `search_similar` becomes a single
   matvec + `argpartition(k)`. Behavior-identical (same scores), removes the only
   hot-path scaling cliff.
4. **Record the drift-coverage limit** (small, adjacent honesty item): ADR-0020's drift is
   measured on doc→code edges only; doc→doc claims (an ADR superseding analysis, THEORY
   referencing ADRs) accrue no drift. Recorded as a known limit in ADR-0020's revisit
   section — not fixed here.

## Considered options

- **Actually adopt LightRAG now.** Rejected: the kernel's resolver already outperforms the
  capability LightRAG would add (its dedup is the documented weak point), and a real
  dependency would re-couple the kernel to an external project's churn for no measured gain.
- **Keep the name, fix only the docs.** Rejected: the class name is itself a false claim that
  every future reader pays for; renames are cheap pre-1.0.
- **Build a second backend to make "pluggable" true.** Rejected: no need exists (the JSON
  store with a numpy index is comfortably inside budget at portfolio scale); backend swap
  stays a deferred mechanism behind the protocol.

## Consequences

- Names, architecture document, and code agree again; the settled-tradeoffs table stops
  asserting unbuilt capabilities.
- `find` similarity becomes O(matvec) — survives method-node growth without a backend change.
- ADR-0004 is partially superseded (backend *choice* record stands; realized backend
  corrected). The "validation required before forking" clause of settled tradeoff 1 is moot.
- No protocol change, no migration: the on-disk format is unchanged; only the class/module
  name and the in-memory index change.

## When this should be revisited

- The portfolio outgrows brute-force-with-numpy (graphs well past 10⁵ entities or
  multi-portfolio service use) → a second `KnowledgeStore` implementation becomes a real
  decision; grill it then, against measured load, not before.

## Related

- [ADR-0004](./0004-switch-to-lightrag.md) — the selection this corrects the realized state of.
- [ADR-0017](./0017-entity-resolution-identity-merging.md) — where the hand-rolled reality was established.
- [ADR-0020](./0020-staleness-as-structural-drift.md) — drift-coverage limit recorded.
- [ADR-0026](./0026-methods-as-first-class-nodes.md) — the entity growth motivating (3).
- ARCHITECTURE.md §1.1, §2.1.
