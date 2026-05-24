# The materialized markdown tree is the agent's primary interface; MCP is a narrow orientation aid

**Status:** accepted
**Date:** 2026-05-23

Context Kernel exposes the agent two surfaces: a tree of materialized markdown files (`AGENTS.md` at every scope plus cross-cutting views under `.context-kernel/views/`), and a read-only MCP server with two tools (`overview`, `find`). The architectural commitment is that **the markdown tree is the primary surface**; MCP is a narrow orientation aid that exists to *point at* the right files for a given question, not to *replace* file reads.

This is recorded as Settled Tradeoff 2 in [ARCHITECTURE.md](../../ARCHITECTURE.md#11-settled-tradeoffs), and is enforced by Tenet 2 ("work belongs in materialization, not query time"). It constrains every module decision through the rule that any answer MCP can give, a file could also give — and where in doubt, the answer is a new pre-materialized view rather than a new runtime path.

## Considered options

- **Service API as the primary surface.** Rejected: would require building a graph-query language or a tool-schema-rich MCP surface, and the agent's working loop would shift from "read files" to "issue queries." `Read` / `Grep` / `Glob` is universal across coding agents; a graph query interface would be Context-Kernel-specific. The filesystem-as-interface choice scales across agent tools without per-agent bridges.
- **MCP-only surface, no materialized tree.** Rejected: makes Context Kernel a service the agent must integrate with. Loses Claude Code's directory-walking auto-load (which `AGENTS.md` + `@AGENTS.md` bridge per scope exploits, per [ADR-0002](./0002-materialize-agents-md-with-claude-code-bridge.md)). Loses the property "remove the MCP server and the file tree still answers every question (slower)" — the file tree as a fallback orientation surface is load-bearing for resilience.
- **DSL or custom query language.** Rejected: same failure mode as service-API, plus the cost of designing and maintaining a query language. The current `find(query, scope_path)` MCP tool delivers semantic search without inventing a syntax.
- **Hybrid with peer status (MCP and files equally authoritative).** Rejected: if MCP and files are peers, the kernel has to keep them consistent in both directions — changes via one surface visible through the other. Designating files as primary and MCP as a read-through cuts that bidirectional consistency problem entirely.

## Consequences

- The OrientationServer module ([ARCHITECTURE.md §2.5](../../ARCHITECTURE.md#25-orientationserver)) is constrained to be a pure read-through over the on-disk tree. No independent state, no runtime synthesis (also enforced by `THEORY.md` invariant 3). Future MCP tools that would require runtime work answer the design question by materializing a new view, not by adding a runtime path.
- The set of cross-cutting views (`.context-kernel/views/*.md`) is the kernel's expressive surface. Adding a view is a config change (ConfigStore in [ARCHITECTURE.md §3.1](../../ARCHITECTURE.md#31-configstore)); the MCP `find` tool gets more useful as more views exist but never *requires* a view to exist.
- The bridge pattern in [ADR-0002](./0002-materialize-agents-md-with-claude-code-bridge.md) (`@AGENTS.md` import in each materialized `CLAUDE.md`) is only possible because files are the primary surface — there is nothing to bridge if the canonical content lives in a service.
- Removing the kernel from a portfolio is `rm -rf .context-kernel/` plus uninstalling the hook (per [ADR-0003](./0003-pull-based-jit-regeneration.md) Consequences). The materialized tree itself can be left in place as static documentation; the portfolio degrades to "no auto-regen, no orientation MCP" rather than to "no usable context at all."
- Modules that propose runtime work (e.g. a future `synthesize(query) → markdown` MCP tool that calls an LLM at request time) violate Tenet 2 by default and require explicit re-litigation. OrientationServer's `Does not own` row calls this out as a non-feature.

## When this should be revisited

- A second-class agent emerges that does *not* speak `Read` / `Grep` / `Glob` natively — at which point the file-as-interface assumption breaks for that consumer and the architecture must either ship a per-agent bridge or accept that some consumers only get MCP.
- The materialized tree size grows to the point where filesystem-as-namespace becomes a bottleneck (very unlikely for a personal portfolio — likely a multi-million-file scale problem).
- A research-grade synthesis capability (live LLM call producing a fresh, query-specific answer) becomes the agent's primary working loop — at which point Tenet 2 itself may need revisiting, not just this ADR.
