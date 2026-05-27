# Authored reference documents as root nodes for subsystem understanding

**Status:** accepted
**Date:** 2026-05-27

Complex subsystems (Ingester, Graph, Materializer) get a hand-authored reference document under `docs/reference/<subsystem>.md` that describes what the subsystem IS — its pipeline, its decisions, its operational shape. These documents are **source** (input to ingestion), not **materialized** (output of the graph). When ingested, they produce high-centrality entities that become the natural first result for orientation queries — the "root node" an agent reaches when asking about a subsystem.

This fills a gap between ARCHITECTURE.md (module contracts, years shelf-life) and AGENTS.md (auto-materialized scope summaries). ARCHITECTURE.md says what each module *owns*; reference docs say how each module *works today*. AGENTS.md is a graph-derived view — it can only be as rich as the entities in the graph. Reference docs are what make the graph rich in the first place.

## The two-layer entry point

An agent encountering a complex subsystem gets understanding through two complementary layers:

1. **AGENTS.md** (via CLAUDE.md bridge) — auto-loaded into the system prompt. Orientation: what entities are here, what cross-scope relationships exist, where to look next. Always present, always current, auto-materialized. Contains a pointer: "for operational understanding, see `docs/reference/<subsystem>.md`."

2. **Reference doc** (via `find` or direct `Read`) — authored understanding of the subsystem end-to-end. Returned by `find` as the highest-relevance result for subsystem queries because its entities are the most semantically aligned. Describes what the subsystem is, what decisions shaped it, how the parts fit together. Not a list of graph entities — a narrative a human wrote and maintains.

AGENTS.md is the index card; the reference doc is the chapter. AGENTS.md tells the agent where it is; the reference doc tells the agent what's going on.

## Why authored, not materialized

The Materializer could, in principle, generate a subsystem overview from graph state — list the entities, show the relationships, summarize the scope. But that produces a *report*, not *understanding*. A graph-derived document about ingestion would say "contains MarkdownHandler, PythonHandler, TypeScriptHandler, ChunkHandler protocol, StructuredHandler protocol..." — which is what AGENTS.md already does. What it can't produce is "the ingester dispatches files by suffix to one of two handler protocols; markdown goes through heading-aware chunking then LLM-based entity extraction, while Python and TypeScript go through deterministic AST parsing." That's authored understanding of the design, not a traversal of the graph.

Reference docs are the source material that, when ingested, enriches the graph with conceptual entities ("ingestion pipeline", "handler dispatch", "change detection") that connect code entities to each other. Without them, the graph has structural entities (classes, functions, imports) and decision entities (from ADRs) but no connective tissue between the two.

## Gap detection

When the Materializer renders AGENTS.md for a scope, it compares code-entity density against documentation-entity density. If a scope has high structural complexity (many code entities, many relationships) but no reference doc coverage, AGENTS.md includes a recommendation:

```
## Recommended documentation

This scope has N code entities across M files but no reference
documentation. To create one: /init-reference <subsystem>
```

The recommendation is surfaced through the same channel the agent already reads (CLAUDE.md → AGENTS.md), closing the loop: the kernel identifies its own documentation gaps and tells the agent how to fill them.

## Formatting for ingestion quality

Reference docs are structured to maximize the quality of entities the MarkdownHandler and Summarizer extract:

- **Heading hierarchy is load-bearing.** The MarkdownHandler's `[heading: Ingestion Pipeline > Handler Dispatch > Markdown]` prefix is our contextual retrieval mechanism. Each H2/H3 section becomes one chunk with full ancestry context. Sections target ~256-512 tokens (within `_CHUNK_SIZE`).
- **CONTEXT.md terms as entity anchors.** Using "ingestion pass", "scope", "hybrid corpus" consistently creates cross-reference relationships to entities from other documents.
- **Explicit cross-references.** "The Embedder (see [types](../reference/types.md)) produces vectors stored in the Graph (see [graph](../reference/graph.md))" — these produce relationship entities when the Summarizer processes the chunks.
- **A `/init-reference` skill** generates the skeleton (heading structure, section placeholders, CONTEXT.md terms, ADR cross-references) from ARCHITECTURE.md and the code. The content is then authored — by a human, an agent, or both.

## Document hierarchy (updated)

| Doc | Altitude | Consumer | Side of graph | Lifecycle |
|---|---|---|---|---|
| `THEORY.md` | Trunk | Human | — | Years |
| `ARCHITECTURE.md` | Structure | Human + Agent | — | Years |
| `CLAUDE.md` | Bridge | Agent harness | Materialized (output) | Auto |
| `AGENTS.md` | Orientation | Agent (system prompt) | Materialized (output) | Auto |
| **`docs/reference/`** | **Understanding** | **Agent (via Read/find)** | **Source (input)** | **Months** |
| `docs/adr/` | Decisions | Human + Agent | Source (input) | Forever |
| `PLAN.md` | Roadmap | Human | — | Months |
| Specs | Leaves | Human + Agent | — | Weeks |

## Considered options

1. **Enrich AGENTS.md materialization to include operational detail.** Rejected: AGENTS.md can only contain what's already in the graph. Richer AGENTS.md requires richer source documentation — which is what reference docs provide. Circular dependency.

2. **Expand ARCHITECTURE.md with operational detail.** Rejected: ARCHITECTURE.md is at the contract altitude (years, revised on module-boundary changes). Operational understanding changes at the months timescale as implementation evolves. Different shelf-lives mean different documents.

3. **Use ADRs for operational understanding.** Rejected: ADRs record decisions (why we chose X over Y), not current operational state (how X works today). A decision is forever-localized; operational understanding is living.

4. **Auto-generate reference docs from graph state.** Rejected: produces reports (entity lists, relationship tables), not understanding (narrative, design rationale, pipeline flow). AGENTS.md already does graph-derived summarization. The gap is authored understanding, not more summarization.

## Consequences

- New document altitude: `docs/reference/<subsystem>.md`. One per complex subsystem. Authored and maintained like code — PRs, reviews, updates when implementation changes.
- New skill: `/init-reference` generates the skeleton; content is authored.
- AGENTS.md template gains a "Recommended documentation" section when gap detection triggers.
- AGENTS.md template gains pointers to relevant reference docs when they exist.
- The document hierarchy in project CLAUDE.md is updated to include the reference altitude.
- Reference docs become the highest-relevance `find` results for subsystem orientation queries — not by ranking engineering, but because their entities are the most semantically aligned with those queries.

## When this should be revisited

- If AGENTS.md materialization becomes rich enough (through better summarization or graph density) that authored reference docs add no information an agent can't get from AGENTS.md alone.
- If the reference docs drift out of sync with implementation frequently — may indicate the shelf-life assumption (months) is wrong, or that a refresh skill is needed.
- If gap detection produces too many false positives (recommending docs for scopes that don't need them) — threshold tuning needed.
