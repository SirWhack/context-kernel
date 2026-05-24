# Switch the Graph backend from fast-graphrag to LightRAG

**Status:** accepted
**Date:** 2026-05-23

Context Kernel's Graph module (per [ARCHITECTURE.md §2.1](../../ARCHITECTURE.md#21-graph)) is built on a third-party GraphRAG library. The original choice, recorded in `docs/design.md` and the pre-Naur handoff briefing, was **fast-graphrag** (Circlemind) — selected for its incremental-upsert algorithm over Microsoft GraphRAG (no first-class incremental), LightRAG (heavier at the time), and nano-graphrag (lighter on incremental).

A re-evaluation in May 2026 — before any code was written against it — found fast-graphrag is functionally dormant: last substantive code commit June 2025, last release April 2025 (never reached 0.1), open bugs in our exact hot paths (vertex IDs, persistence on reload, Ollama integration) sitting unfixed since September 2025. The startup that maintained the OSS project appears to have pivoted.

We are switching to **LightRAG** (HKUDS, MIT). LightRAG is actively maintained (weekly releases through 2026-05, EMNLP'25 paper, official Ollama-compatible server), supports first-class incremental upsert (`ainsert` + delete + merge with a dual-level index), and ships pluggable storage backends (NetworkX / Neo4j / Postgres / Milvus / Qdrant) — preserving our future option for cross-project entity merging (see `THEORY.md` non-goal 2 / open question 1).

## Considered options

- **Stay on fast-graphrag.** Rejected: the open vertex-ID and persistence bugs alone would cost more debugging weeks than a migration. A solo-maintained project needs an upstream that won't disappear.
- **Microsoft GraphRAG (the original).** Rejected: full-rebuild community detection; incremental is bolted on and expensive. Wrong shape for our pull-based JIT regeneration.
- **nano-graphrag.** Rejected: effectively frozen since October 2024. Valuable as a reference implementation, not a base to fork.
- **Graphiti (Zep).** Runner-up. Apache-2.0, very active, bi-temporal incremental is the cleanest conceptual fit for our graph-as-source-of-truth invariant. Rejected for v1 because it requires Neo4j 5.26+ as a hard infrastructure dependency — adding Neo4j-in-WSL2 to the operational story before any code ships is a poor cost/benefit trade.
- **Cognee (topoteretes).** Rejected: broader scope than we need (memory control plane); heavier abstraction; we'd use less of the library than we'd carry.

## Consequences

- The `KnowledgeStore` protocol (per [ARCHITECTURE.md §2.1](../../ARCHITECTURE.md#21-graph)) wraps LightRAG. The Parnas-secret behind the protocol changes from "fast-graphrag's data model" to "LightRAG's data model" — but the protocol shape stays the same, so downstream modules (Materializer, OrientationServer) are unaffected.
- **Pre-fork validation is required.** Before any code is written against LightRAG, run its quickstart against a representative slice of the portfolio on the 7900 XTX. Confirm a 32B-class model (Qwen2.5-32B-Q4 or similar) fits in 24GB VRAM with enough context budget for representative source files. If this fails, the choice flips back to evaluating Graphiti specifically (and accepting Neo4j) or to smaller-model variants of LightRAG. To be sequenced as a slice-zero validation step in `PLAN.md`.
- `HANDOFF.md` and `docs/design.md` both currently name fast-graphrag as the chosen base. Both need updating to point at LightRAG and link this ADR.
- The pluggable-storage benefit of LightRAG reduces the risk on open question 1 — if cross-project entity merging eventually requires a graph backend with stronger query semantics, the storage swap is a config change rather than a fork.

## When this should be revisited

- LightRAG enters its own dormancy phase (release cadence drops to monthly or less for an extended period without a clear successor commitment).
- The 32B-model recommendation proves intolerable on the 7900 XTX during pre-fork validation, *and* a smaller-model configuration (7B–14B) cannot meet quality bars on representative source files.
- A library emerges that combines LightRAG's incremental upsert with Graphiti's bi-temporal model and ships with NetworkX as a viable default storage.
