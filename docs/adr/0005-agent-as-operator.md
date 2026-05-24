# Agent is the operator of `ck`; human delegates and browses

**Status:** accepted
**Date:** 2026-05-23

The original `docs/design.md` framing said: *"`ck` is an operator CLI, never invoked by the agent."* The intended privilege boundary: the human runs `ck` directly to mutate kernel state; the agent only reads materialized files and calls the read-only MCP tools. Mutation and reading lived on opposite sides of a hard wall.

In practice this is wrong. The agentic engineer's working loop is: state intent in natural language → delegate to a coding agent → review the result. The human does not run `ck ingest` after editing a source file; the agent does (via Bash, which the agent already has). Treating the human as the operator forces a manual step the human will skip — and the freshness gate then has to carry the entire integrity story alone.

**Inverting the framing:** the coding agent is the primary operator of `ck`. The human delegates tasks and browses the materialized tree (via Obsidian or directly). `ck` is the agent's mutation API. Per `THEORY.md` invariant 1 (mutation lands at the graph, never at materialized files), the agent's privilege boundary is unchanged at the invariant layer — *how* it mutates (via `ck`, never via direct edits to materialized files) is what matters, not *who* invokes `ck`.

This reframe was made explicit during `/grill-architecture` Pass 1 and is recorded as Settled Tradeoff 4 in [ARCHITECTURE.md](../../ARCHITECTURE.md#11-settled-tradeoffs).

## Considered options

- **Original framing: human-as-operator, agent read-only.** Rejected because it breaks at first contact with the agentic working loop. Humans don't manually re-ingest after every edit; the silent failure mode (stale graph, then the gate eventually catches it on next read) defeats the gate's purpose by making it the only integrity mechanism. The framing was a vestige of an earlier conception where `ck` was a heavyweight admin tool, not a routine working surface.
- **Hybrid: agent can invoke read-only `ck` commands (`ck check`); only the human runs write commands (`ck ingest`, `ck materialize`).** Rejected: same failure mode, just smaller. The human still won't manually ingest after edits. Adds boundary complexity without resolving the underlying issue.
- **Add MCP write tools so the agent invokes the kernel through MCP rather than Bash.** Considered but deferred. The Bash invocation path works today and requires no new code; MCP write tools are tracked as a deferred mechanism (ARCHITECTURE.md §6 row "MCPWriteTools") to be added when there's a concrete reason Bash is insufficient. Invariant 1 keeps the door open: write tools, when they arrive, mutate the graph and trigger materialization — they do not edit materialized files directly.

## Consequences

- The kernel's "primary caller" framing changes. AgentCLI's module description ([ARCHITECTURE.md §2.6](../../ARCHITECTURE.md#26-agentcli)) names the coding agent as primary caller; the human is the secondary, delegating caller.
- A `PostToolUse` hook in the harness can plausibly auto-run `ck ingest <changed-path>` after the agent writes a source file — making ingest discipline mostly automatic rather than mostly explicit. Implementation detail for the slice that wires the hooks, not an architectural decision.
- `docs/design.md` says "`ck` is never invoked by the agent" — this line is now wrong; needs updating. `CONTEXT.md`'s **ck** entry says "never invoked by the agent" too — also needs updating.
- The FreshnessGate's role becomes a safety net rather than the sole integrity mechanism. The agent actively keeps things fresh via routine `ck ingest`; the gate catches the cases where the agent forgets or where edits happened outside the agent's view. Still load-bearing, but no longer the only thing standing between the agent and a stale chunk.
- An early THEORY.md draft included "agent cannot mutate via MCP" as a candidate invariant; it was dropped during `/grill-theory` after pushback. This ADR records the equivalent reframe at the policy layer (where it belongs — whether the agent invokes `ck` is policy, not invariant; invariant 1 already covers what actually matters: writes go graph-first).

## When this should be revisited

- A second class of consumer emerges (e.g. a CI agent that ingests but never reads, or a non-Claude-Code agent with a different mutation pattern) — the privilege model may need finer granularity than "anyone with `ck` access can mutate."
- MCP write tools are added and Bash invocation is deprecated — the framing shifts from "Bash-invokes-`ck`" to "MCP-tool-invokes-internals," and AgentCLI's role narrows accordingly.
- A multi-user or shared-portfolio scenario emerges (currently out-of-scope per ARCHITECTURE.md §8) — identity becomes a real concern, and "the agent" must be disambiguated from "which agent, acting on whose behalf."
