# Graph Canvas — Context Kernel knowledge-graph visualizer

A VS Code extension that renders the Context Kernel knowledge graph as an **infinite
code canvas**: files become syntax-highlighted code panels, and the graph's real
relationships (`calls`, `imports`, `contains`, concept groundings) are drawn as edges that
anchor to the exact lines of code they connect. It is a *read* surface over the graph the
kernel already builds — not a new analyzer.

> TL;DR: `ck graph` exports the graph as JSON → the extension reads that JSON → a React
> Flow webview renders file panels + line-anchored edges, with focus-and-expand navigation,
> a documentation/code two-stream layout, and a call-flow layout.

---

## 1. Why this exists

The Context Kernel builds one shared knowledge graph across a portfolio of repos (entities,
relationships, embeddings, ontology concepts), but until now there was **no way to see it** —
only the derived `AGENTS.md` files and the `find`/`overview` MCP tools. You could query the
graph but not *look* at it.

The goal: a navigable **code map**. Start from a file or a concept, see what it connects to,
follow calls through the codebase, and understand how documentation and code relate — all
inside the editor, clicking through to the real source.

The visual model is an **infinite canvas** (the term of art), directly inspired by
[CodeCanvas](https://www.codecanvas.app/) (see §7). Where CodeCanvas re-derives a graph from
import parsing, we feed it the kernel's *already-resolved* graph, which is richer: real
`calls` edges, an ontology concept layer, and cross-repo structure.

---

## 2. What we built (chronological)

1. **`ck graph` export** — a clean, versioned JSON view of the graph, decoupled from the
   backend `state.json` so the extension never depends on internal layout.
2. **Cytoscape v1 (replaced)** — first cut rendered files/entities as abstract boxes with a
   force layout. It worked but didn't *look* like code, and the layout was a hairball.
3. **Containment spine** — added `scope`/`parent`/`anchor_id` so the graph carries the real
   `repo ⊃ directory ⊃ file ⊃ entity` hierarchy (schema v2).
4. **React Flow rewrite** — swapped the renderer to React Flow + ELK + Highlight.js so file
   nodes are **real code panels**, matching the CodeCanvas paradigm.
5. **Two-stream waterfall layout** — documentation cascades down a left lane, code down a
   right lane, concept hubs in the center gutter bridging them.
6. **Line-anchored edges** (schema v3) — captured definition/reference line numbers through
   the whole ingest pipeline so an edge can leave a *call site* line and land on the *target
   definition* line, the way CodeCanvas does.
7. **Performance + UX polish** — cache-first loading, slim/compact export, scroll-safe handle
   clamping, code-vs-doc panel resolution, edge de-emphasis.

---

## 3. Architecture

```
 ┌─────────────────────────────────────────────┐         ┌──────────────────────────────┐
 │  Python kernel                                │         │  VS Code extension            │
 │                                               │  JSON   │                               │
 │  state.json ──► ck graph (graph_export.py)  ──┼────────►│  host (extension.ts)          │
 │                  └ --slim, schema v3          │ (cached) │   ├ cache-first read          │
 │                                               │         │   ├ fetchCode (read files)    │
 └─────────────────────────────────────────────┘         │   └ webview panel             │
                                                           │                               │
                                                           │  webview (React Flow)         │
                                                           │   ├ App.tsx   focus+expand    │
                                                           │   ├ model.ts  graph indexes   │
                                                           │   ├ nodes.tsx code panels +   │
                                                           │   │            per-line handles│
                                                           │   └ layout.ts ELK streams/flow │
                                                           └──────────────────────────────┘
```

### 3.1 The export (`ck graph`)

`context_kernel/graph_export.py :: build_graph_export(store, config, project=None)` is a pure
transform from a `KnowledgeStore` snapshot to a stable JSON document. `context_kernel/
agent_cli.py` wires the `graph` subcommand (`--portfolio --config --project --out --slim`).

Shape (schema v3):

```jsonc
{
  "schema_version": 3,
  "graph_commit": "…",
  "projects": ["Ticket Agent"],
  "files": [ { "path", "project", "scope", "anchor_id", "entity_ids": [...] } ],
  "nodes": [ {
    "id", "name", "kind", "project", "scope", "parent",
    "sources": [...], "is_concept", "confidence",
    "def_line"            // 0-based definition line (v3)
  } ],
  "edges": [ {
    "source", "target", "kind", "cross_repo",
    "sourceLine",         // 0-based call/import site in the source file (v3)
    "targetLine"          // 0-based definition line in the target file (v3)
  } ]
}
```

- **`--slim`** drops fields the webview never renders (`description`, `centrality`,
  `source_tier` on nodes) and writes **compact** JSON (no `indent=2`). This roughly halved the
  payload (≈9.6 MB → ≈4.6 MB on the Ticket Agent). It keeps `sources` (for the prefer-code
  resolution) and `kind` (for call-flow + edge styling).
- **Concept hubs** (`is_concept: true`) have `project: null` — they're the ontology layer and
  the only cross-repo bridges.

### 3.2 The host (`src/extension.ts`)

- Registers **`Context Kernel: Show Graph`** and **`Context Kernel: Refresh Graph`**.
- **Cache-first load** (`loadGraph`): reads `.context-kernel/views/graph.json` directly when
  present — instant, no subprocess, no 2-second backend load. This matches the kernel's
  invariant that *views are pre-materialized and served as-is, with no runtime synthesis*
  (AGENTS.md). On a cache miss it shells out to `ck graph --slim` and writes the result as the
  cache. **Refresh Graph** forces a re-run (use it after re-ingesting).
- **Lazy code fetch**: file panels request source on demand (`fetchCode` → `{type:"fetchCode"}`
  → host reads the file → `{type:"code", text, lang}`), so we never ship every file's source
  up front.
- One reused webview panel; strict CSP with a per-load nonce.

### 3.3 The webview (React Flow)

- **`model.ts`** turns the export into indexes: `filesByPath`, `fileOfEntity` (prefers a code
  source — see §6), `conceptById`, `symbolsOfFile`, and a directed adjacency `out` that
  aggregates entity→entity edges to **file panels**, carrying the distinct
  `(sourceLine, targetLine)` line pairs for each panel-pair.
- **`App.tsx`** holds the canvas: focus-and-expand state, `buildElements` (emits one React
  Flow edge per line pair, binding `sourceHandle`/`targetHandle` to `line-{N}`), the toolbar
  (repo, search-to-open, layout toggle, Concept-bridges, Reset), MiniMap/Controls/Background.
- **`nodes.tsx`** renders the two node types:
  - `FileNode` — a code panel. Highlight.js output is split into **one DOM element per source
    line** (`<span class="ck-line" data-line>`), a Handle is rendered **per participating
    line** (`id="line-N"`), and line positions are **measured and clamped to the code
    viewport** so handles track scrolling and pin to the box edge when a line scrolls out of
    view. `useUpdateNodeInternals` is called on every re-measure (required by React Flow v12).
  - `ConceptNode` — an ontology hub pill (cross-cutting / cross-repo bridge).
- **`layout.ts`** runs ELK in three modes (§5).

---

## 4. The data model on the canvas

- **Node = file panel** (code or doc) **or concept hub.** Entities (classes/functions) are
  *symbols within* a file, not separate nodes — the panel shows them as real code.
- **Edge = aggregated relationship between two panels**, drawn per distinct line pair.
  - `calls` → animated blue, anchored call-site line → callee definition line.
  - `imports` / other structural → faint.
  - anything touching a concept hub → dashed purple **bridge**.
- **Streams**: every file is classified `doc` (markdown/prose) or `code` (everything else),
  used by the Streams layout and shown as an orange `DOC` / green `CODE` badge.

---

## 5. Layouts (ELK)

- **Streams (default)** — a two-lane waterfall: docs cascade down the left, code down the
  right, concept hubs in the center gutter at the height of the nodes they link. Each lane is
  laid out from its *internal* edges only, so cross-stream links don't distort the columns.
- **Call flow** — a single left→right layered graph over the `calls` edges (entry → callee),
  the execution-path view.
- **Network** — a force/stress layout for general relationship browsing.

---

## 6. Line-anchored edges — how it works end to end

This is the headline feature and the trickiest. We needed a *source line* and *target line* on
every edge; the graph had neither.

**Upstream (Python), schema v3:**
- `handlers.py` — the Python AST handler and TS tree-sitter handler now capture `def_line`
  (0-based start line) on every code entity (module/class/function/method) and `source_line`
  (the call/import site line) on every `calls`/`imports` edge.
- Threaded through `entity_resolver.py` (`Extracted*` → `Canonical*` → `Resolved*`; a merged
  node keeps the first code definition's `def_line`), into `protocol.py`
  (`Entity.def_line`, `Relationship.source_line`), persisted in `lightrag_adapter.py`.
- `graph_export.py` emits `edge.sourceLine = rel.source_line` and
  `edge.targetLine = target_entity.def_line`. **We can do this precisely from the AST**, where
  CodeCanvas has to guess the target via an LSP "first symbol" heuristic.

**Webview:**
- Highlight.js HTML is re-wrapped so each source line is its own element (a multi-line
  syntax span is closed at the newline and reopened — see `highlightToLines` in `nodes.tsx`).
- For each line that participates in an edge, `FileNode` renders a source+target Handle pair
  `id="line-{N}"`; edges set `sourceHandle`/`targetHandle` accordingly. Edges without line
  data fall back to a node-level `line-node` handle.
- Handle vertical positions are **measured** from the rendered lines and **clamped to the code
  viewport**, so scrolling a panel re-anchors edges and off-screen targets pin to the top/
  bottom edge instead of flying across the canvas.

---

## 7. Reference repos / prior art

### CodeCanvas — the model we emulate
- Product: <https://www.codecanvas.app/> (and the v2 preview at `v2.codecanvas.app`).
- Origin we were pointed at: a r/webdev post, mirrored on DEV.to
  ("I built a VSCode extension to see your code on an infinite canvas").
- Open-source implementation studied closely: **`waLLxAck/code-canvas`** on GitHub (cloned to
  `/tmp/code-canvas` during analysis — a scratch clone, not vendored here).

**What CodeCanvas does:** files are panels of real, syntax-highlighted code arranged on a
pan/zoom canvas, with edges anchored to exact code lines (definition → reference → call).

**Its stack (from the open-source repo):**
- **React Flow** — the canvas renderer (DOM panels, pan/zoom, built-in MiniMap).
- **ELK (`elkjs`)** — layout (layered left→right for flows).
- **Highlight.js** — code rendering, *preserving line structure so edges anchor to lines*.
- **fast-glob + import-statement regex** — discovers files and source-side import lines.
- **VS Code LSP** (`executeDocumentSymbolProvider`) — target-side definition line (a crude
  "first class/function in the file" heuristic).
- Extension (tsup) + webview (Vite/React), standard webview messaging; no separate server.

**What we borrowed:** React Flow + ELK + Highlight.js; the line-preserving HTML technique; the
per-line `Handle` + `sourceHandle/targetHandle` line-binding; the measured-handle-position
trick. The v12-specific must-do they don't show — calling `useUpdateNodeInternals` when handles
move — we do.

**What we do differently / better:**
- We render the kernel's **already-resolved knowledge graph** (real `calls`/`contains`/
  `imports` + an ontology **concept layer** + cross-repo structure) instead of re-parsing
  imports. Richer and not limited to JS/TS/Python import graphs.
- Target lines come from our **AST `def_line`**, so we skip CodeCanvas's LSP "first symbol"
  guess.
- We add a **documentation⇄code two-stream layout** and **concept hubs**, which have no
  analogue in CodeCanvas.
- We add **scroll-safe handle clamping** (off-screen lines pin to the box edge).

### Example data repo
The graph shown during development is the **Ticket Agent** repo
(`/Users/samwynn/Code/Internal/Ticket Agent`), a single-project portfolio. Its
`.context-kernel/` holds the `state.json` graph and the materialized
`views/graph.json` cache the extension reads.

---

## 8. Build / run

```bash
cd vscode-extension
npm install
npm run build           # esbuild → out/extension.js + media/main.js + media/main.css
npx tsc --noEmit        # type-check (esbuild does not)
npx @vscode/vsce package --allow-missing-repository --skip-license -o context-kernel-graph.vsix
code --install-extension context-kernel-graph.vsix --force
```

Point the extension at the `ck` CLI via the `contextKernel.ckPath` setting (e.g. the venv
binary). It auto-detects the portfolio root by walking up for a `.context-kernel/` dir, or set
`contextKernel.portfolioRoot`.

After **re-ingesting** the kernel (which is what populates `def_line`/`source_line`), run
**Context Kernel: Refresh Graph** to rebuild the cache, then reload the window.

Regenerate the cache manually:
```bash
ck graph --portfolio "<repo>" --config "<repo>/.context-kernel/config.toml" \
         --slim --out "<repo>/.context-kernel/views/graph.json"
```

---

## 9. Schema history

| Version | Added |
|---|---|
| v1 | `projects`, `files` (prefixed paths), `nodes`, `edges`; concept hubs `project: null` |
| v2 | Containment spine: `node.scope`/`node.parent`, `file.anchor_id`/`file.scope` |
| v3 | Line anchors: `node.def_line`, `edge.sourceLine`/`edge.targetLine` |

---

## 10. Known limitations & next steps

- **Concept breadth** depends on ontology aliases. A concept only links to code its
  `altLabel`s alias-match (e.g. Query Pipeline → only `pipeline`/`PipelineCircuitBreaker`).
  Breadth comes from expanding those files outward; richer hubs need more `altLabel`s.
- **Aspect concepts** (recall-then-judge) are wired in the kernel now, but the canvas treats
  all concepts uniformly as bridges.
- **No multi-repo testing yet** — single-repo (Ticket Agent) is the only exercised path;
  project-scoped concepts currently export as `project: null` (fine for one repo, needs
  bucketing for a real portfolio).
- **Edge density** — even dimmed, a heavily-connected concept can be busy. Next lever: show
  line-anchored edges only for the selected panel and collapse the rest to node-level edges.
- **Nice-to-haves**: edge-click → scroll+highlight both endpoint lines (CodeCanvas has this);
  in-panel symbol outline; persisted manual node positions; line-anchor `imports` edges to the
  imported symbol rather than the module's first line.

---

## 11. File map

**Python (`context_kernel/`)**
- `graph_export.py` — `build_graph_export`, schema v3, the export shape.
- `agent_cli.py` — `ck graph` subcommand (`--slim`, compact output).
- `ingester/handlers.py` — `def_line` / `source_line` capture (Python AST + TS tree-sitter).
- `ingester/entity_resolver.py` — threads line fields through resolution.
- `graph/protocol.py` — `Entity.def_line`, `Relationship.source_line`.
- `graph/lightrag_adapter.py` — persists/loads the line fields.

**Extension (`vscode-extension/`)**
- `src/extension.ts` — host: commands, cache-first load, code fetch, webview/CSP.
- `src/shared/graph.ts` — TS types mirroring the export + the host↔webview messages.
- `src/webview/index.tsx` — entry; mounts React, routes messages, imports CSS.
- `src/webview/App.tsx` — the canvas; focus+expand; `buildElements`; toolbar.
- `src/webview/model.ts` — graph indexes; prefer-code resolution; adjacency + line pairs.
- `src/webview/nodes.tsx` — `FileNode` (line-preserving highlight, per-line handles,
  measurement+clamp) and `ConceptNode`.
- `src/webview/layout.ts` — ELK streams / call-flow / network.
- `src/webview/vscode.ts` — VS Code API wrapper + code-fetch cache.
- `media/style.css` — toolbar, panels, code lines/gutter, edge styling.
- `esbuild.js` — builds the host (CJS) and webview (IIFE React) bundles.
