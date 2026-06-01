<!-- context-kernel-freshness
graph: ce4c30de6021574f8be593ca3ef2c62ccfde5e39118e774477c1d6d76f0f9abe
source-tree: 630ed453a9583370dd0a0d9ec4c32ffbe721a874cc439c1a8047271f1302b571
materialized: 2026-06-01T01:08:19Z
-->

This scope defines the architectural decisions and design rationale for the model-time context kernel. It captures the "why" behind the system's structure — the trade-offs, invariants, and constraints that govern how the kernel ingests, stores, and materializes context for coding agents. The ADRs here are not implementation details but thesis-level documents that name concepts, state invariants and non-goals, and open questions without duplicating definitions or decisions.

The core architectural principle is that **files are the primary interface** for agents to consume context via Read/Grep/Glob, rejecting service APIs, MCP-only approaches, or query DSLs. This drives the entire design: materialization is allowed to be slow, but queries must be cheap. The `ck` CLI serves as the mutation API — agents invoke it via Bash to mutate kernel state rather than editing materialized files directly. A critical invariant is that all mutation must land at the graph, never at materialized files, which are always derivable projections.

Key design decisions documented here include: the **FreshnessGate** (`context_kernel/freshness_gate.py`) enforces the "no stale serve" invariant at read boundaries; the **KnowledgeStore** protocol (`context_kernel/graph/protocol.py`) provides a backend-agnostic shape over the graph with read APIs for all and write API only for the Ingester; the **EntityResolver** (`context_kernel/ingester/entity_resolver.py`) performs code-anchored identity merging to collapse the same logical concept across code definitions, docs, and ADRs into one canonical node; and the **find** tool (`context_kernel/orientation_server/tools.py`) uses hybrid embedding search combining vector similarity with keyword matching per ADR-0012.

The scope also records resolved trade-offs: splitting edges into structural and semantic families, renaming "implements" to "realizes" to avoid conflation with code-level implements; a performance threshold of <60 seconds for first read on a stale scope; and the principle that expensive, query-independent work happens at ingest/materialization time, not at query time. Cross-scope linkage relies on LightRAG's native entity merging plus a post-ingest traversal pass, with the directive to test before discarding. The ADRs explicitly reject runtime synthesis — if a capability seems to need it, the answer is to materialize a new pre-built view instead.

## Recommended documentation

This scope has 11 code entities across 1 files but no reference documentation. To create one: `/init-reference adr`

