# Context Kernel

The shared language of this project. A glossary, not a spec — no implementation details, no decisions, no roadmap. Decisions live in [docs/adr/](./docs/adr/); the project's thesis and invariants live in [THEORY.md](./THEORY.md).

> Starter glossary seeded by `/grill-theory` on 2026-05-23. `_Avoid_:` aliases, example dialogue, and flagged ambiguities will be sharpened the first time `/grill-with-docs` runs on an MVP slice.

## Language

### Roles and operating surface

**Agentic engineer**:
A developer whose primary working loop delegates code production to coding agents rather than typing each line themselves; the operator of Context Kernel.
_Avoid_: (to be sharpened via /grill-with-docs)

**Portfolio**:
The multi-project root directory containing every project an agentic engineer works across; the operating surface of Context Kernel.
_Avoid_: (to be sharpened via /grill-with-docs)

**Context Kernel**:
The system being built — a knowledge graph plus materialized markdown tree plus read-only MCP orientation surface that gives coding agents altitude-appropriate context across a portfolio.
_Avoid_: (to be sharpened via /grill-with-docs)

**ck**:
The operator CLI (`ck ingest`, `ck materialize`, `ck check`, `ck mcp`); the only writer to `.context-kernel/`. Invoked by the coding agent on the operator's behalf (per [ADR-0005](./docs/adr/0005-agent-as-operator.md)) — today via Bash, in future via MCP write tools.
_Avoid_: "ck is human-only" (superseded — see ADR-0005).

### Composition model

**Altitude**:
A level of context detail along the axis from cross-project patterns (high) down to an individual Python file (low); Context Kernel's job is to compose context across altitudes.
_Avoid_: (to be sharpened via /grill-with-docs)

**Scope**:
The unit a single materialized file covers; in v1, coterminous with a directory (whether scope can span or group directories arbitrarily is an open question).
_Avoid_: (to be sharpened via /grill-with-docs)

### Knowledge store

**Graph**:
The knowledge store at the heart of Context Kernel — entities, relationships, and per-scope summaries derived from the portfolio's source files; the single source of truth from which every materialized file is derived (per [THEORY.md](./THEORY.md) invariant 1). v1 backend: LightRAG with pluggable storage; wrapped behind a thin `KnowledgeStore` protocol.
_Avoid_: (to be sharpened via /grill-with-docs)

### Materialized surface

**Materialized file**:
A markdown file (`AGENTS.md` at a scope, or a view) projected from the graph by `ck materialize`; never a source of truth, always derivable.
_Avoid_: (to be sharpened via /grill-with-docs)

**View** (cross-cutting view):
A materialized file under `.context-kernel/views/` that aggregates information across multiple scopes (e.g. `by-topic/auth.md`); each view is a `(graph_query, template) → file` spec.
_Avoid_: (to be sharpened via /grill-with-docs)

**Pinned block**:
A `<!-- pinned -->`-wrapped section inside a materialized file whose contents survive the next regeneration and feed into the next materialization prompt; the only place free-form human input persists.
_Avoid_: (to be sharpened via /grill-with-docs)

### Pipeline and safety

**Ingestion pass** (`ck ingest`):
The operation that reads source files, updates the graph, and writes content-addressed embeddings and summaries; idempotent, incremental.
_Avoid_: (to be sharpened via /grill-with-docs)

**Materialization pass** (`ck materialize`):
The operation that projects the current graph state into the markdown tree — `AGENTS.md` files at each scope plus configured views; a pure function of `(scope, graph_commit, view_spec)`.
_Avoid_: (to be sharpened via /grill-with-docs)

**Freshness gate**:
The read-time check that compares a materialized file's freshness header (`graph` plus `source-tree` hashes) against current state; triggers regeneration on mismatch before allowing the read; enforces THEORY.md invariant 2.
_Avoid_: (to be sharpened via /grill-with-docs)

**OrientationServer**:
The stdio MCP surface (`ck mcp`) that exposes two read-only tools — `overview` and `find` — pointing coding agents at the right materialized files for a given question; a pure read-through over the materialized tree with no independent state or runtime synthesis (per THEORY.md invariant 3).
_Avoid_: (to be sharpened via /grill-with-docs)

## Relationships

- A **Portfolio** contains many **Scopes**.
- Each **Scope** has one **Materialized file** (today: `AGENTS.md` per directory).
- A **View** aggregates across multiple **Scopes**.
- An **Agentic engineer** operates the **Context Kernel** via the **ck** CLI.
- A **Pinned block** lives inside a **Materialized file** and survives the next **Materialization pass**.
- The **Freshness gate** runs before any read of a **Materialized file**.
- An **Ingestion pass** updates the **Graph**; a **Materialization pass** projects the **Graph** into **Materialized files**.
- An **Agentic engineer** typically delegates tasks to a **Coding agent**; the **Coding agent** invokes **ck** and reads the materialized tree.
- The **OrientationServer** is a read-through over the materialized tree; the **Freshness gate** runs inside it before any chunk is returned.

## Example dialogue

<!-- To be filled in during the first /grill-with-docs session on an MVP slice. The dialogue should demonstrate the terms above interacting naturally in prose — e.g. an agentic engineer talking through what happens when they edit a source file and then ask the agent a question. -->

## Flagged ambiguities

<!-- To be filled in as ambiguities surface during /grill-with-docs sessions. -->
