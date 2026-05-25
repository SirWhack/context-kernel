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

**Cross-scope relationship**:
A Relationship in the Graph whose endpoint Entities have source files in different Scopes; the bridge that lets a Scope's `AGENTS.md` name its dependencies elsewhere in the portfolio. Derived from LightRAG's native cross-document entity merging plus a source-ID traversal pass at the end of ingest, per [ADR-0009](./docs/adr/0009-cross-scope-relationships-via-source-id.md). Surfacing these at sufficient density is what differentiates Context Kernel from flat vector RAG — see [THEORY.md](./THEORY.md) open question 4.
_Avoid_: "external relationship" (too generic); "import relationship" (implies code-only).

### Materialized surface

**Materialized file**:
A markdown file (`AGENTS.md` at a scope, or a view) projected from the graph by `ck materialize`; never a source of truth, always derivable.
_Avoid_: (to be sharpened via /grill-with-docs)

**View** (cross-cutting view):
A materialized file under `.context-kernel/views/` that aggregates information across multiple scopes. Two kinds in v1: `index` (all-scope listing with summaries and `AGENTS.md` paths) and `by-topic` (entities/summaries matching a configured tag, grouped by scope). Each view is a `(ViewSpec, graph_state) → file` projection. Configured via `[[materializer.views]]` in `.context-kernel/config.toml`.
_Avoid_: "report" (implies one-off generation); "dashboard" (implies live state).

**Pinned block**:
A `<!-- pinned -->` / `<!-- pinned:label -->`-wrapped section inside a per-scope materialized file (`AGENTS.md`) whose contents survive regeneration. The highest-quality data in the system — deliberately authored human context that the kernel preserves with the same care as graph state. Represented internally as `PinnedBlock(label, content)`; rendered as markdown but tracked as structured data. Labels are optional but provide identity for dedup and future positional anchoring. Not supported in cross-cutting views (views are pure projections with no side inputs).
_Avoid_: "annotation" (too generic); "comment" (implies non-functional).

### Pipeline and safety

**Ingestion pass** (`ck ingest`):
The operation that reads source files, updates the graph, and writes content-addressed embeddings and summaries; idempotent, incremental.
_Avoid_: (to be sharpened via /grill-with-docs)

**Materialization pass** (`ck materialize`):
The operation that projects the current graph state into the markdown tree — `AGENTS.md` files at each scope plus configured views; a pure function of `(scope, graph_commit, view_spec)`.
_Avoid_: (to be sharpened via /grill-with-docs)

**Freshness gate**:
The mechanism that keeps materialized files in sync with their source. In v1, enforced by a git `pre-commit` hook that runs `ck ingest && ck materialize` before every commit — documentation is committed alongside code. `ck check` remains available for manual verification. Enforces THEORY.md invariant 2.
_Avoid_: "read-time gate" (superseded by ADR-0010); "file watcher" (no daemon).

**OrientationServer**:
The stdio MCP surface (`ck mcp`) that exposes two read-only tools — `overview` and `find` — pointing coding agents at the right materialized files for a given question. `overview` reads a scope's `AGENTS.md`; `find` performs embedding-similarity search over the hybrid corpus. Calls the Embedder at query time for vector computation — this is infrastructure, not runtime synthesis (per THEORY.md invariant 3 and [ADR-0012](./docs/adr/0012-find-retrieval-via-hybrid-embedding-search.md)).
_Avoid_: "search server" (it points; files deliver); "RAG endpoint" (no LLM generation in the response path).

**Hybrid corpus**:
The combined set of entity descriptions (from StructuredHandlers) and per-scope summaries that `find` searches over. Entity descriptions provide fine-grained results (individual classes, functions); scope summaries provide coarse orientation (what a directory does). Both are embedded at ingest time and stored in the same vector index. Per [ADR-0012](./docs/adr/0012-find-retrieval-via-hybrid-embedding-search.md).
_Avoid_: "search index" (implies a separate artifact — the hybrid corpus lives inside the Graph's vector store).

**Asymmetric prompting**:
The Qwen3-Embedding requirement that query-time and passage-time embeddings use different prompt formats. Passages are embedded as plain text; queries are prefixed with `Instruct: {task}\nQuery: {text}`. Omitting the prefix costs 1–5% retrieval accuracy. The `Embedder` interface exposes this via a `mode` parameter (`"passage"` or `"query"`).
_Avoid_: "query prefix" (too vague — the format is specific to the model).

## Relationships

- A **Portfolio** contains many **Scopes**.
- Each **Scope** has one **Materialized file** (today: `AGENTS.md` per directory).
- A **View** aggregates across multiple **Scopes**.
- An **Agentic engineer** operates the **Context Kernel** via the **ck** CLI.
- A **Pinned block** lives inside a **Materialized file** and survives the next **Materialization pass**.
- The **Freshness gate** runs before any read of a **Materialized file**.
- An **Ingestion pass** updates the **Graph**; a **Materialization pass** projects the **Graph** into **Materialized files**.
- An **Agentic engineer** typically delegates tasks to a **Coding agent**; the **Coding agent** invokes **ck** and reads the materialized tree.
- The **OrientationServer** searches the **Hybrid corpus** via embedding similarity; `overview` reads a **Materialized file** directly.
- The **Hybrid corpus** is populated during the **Ingestion pass** — entity descriptions and scope summaries are embedded and stored in the **Graph**'s vector index.
- **Asymmetric prompting** governs how the **Embedder** encodes text differently at ingest time (passage) vs. query time (query).

## Example dialogue

<!-- To be filled in during the first /grill-with-docs session on an MVP slice. The dialogue should demonstrate the terms above interacting naturally in prose — e.g. an agentic engineer talking through what happens when they edit a source file and then ask the agent a question. -->

## Flagged ambiguities

<!-- To be filled in as ambiguities surface during /grill-with-docs sessions. -->
