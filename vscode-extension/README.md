# Context Kernel Graph (VSCode extension)

Visualizes the Context Kernel knowledge graph as a navigable **file → entity** code map.

- **Files** are compound boxes; the **entities** they define live inside them.
- **Edges** are the graph's entity→entity relationships (width ∝ weight).
- **Concept hubs** (global ontology concepts) render as purple diamonds and their edges
  are dashed — these are the only links that bridge across repos.

Each repo renders separately (entity IDs are project-namespaced, so nodes are never shared
across repos). Use the **Repo** dropdown to switch; concept bridges stay visible so you can
see cross-repo connections.

## How it works

The extension shells out to the `ck graph` CLI (added in `context_kernel/graph_export.py`),
which emits a stable JSON document (`schema_version`, `projects`, `files`, `nodes`, `edges`).
Rendering uses [Cytoscape.js](https://js.cytoscape.org/) with the `fcose` layout, bundled
into the webview by esbuild (no network access at runtime).

## Develop

```bash
cd vscode-extension
npm install
npm run build        # or: npm run watch
```

Press **F5** in VSCode to launch an Extension Development Host. Open a file inside a
portfolio that has a `.context-kernel/` directory, then run **Context Kernel: Show Graph**
from the command palette.

## Settings

- `contextKernel.ckPath` — path to the `ck` CLI (default `ck`). Point this at a venv binary,
  e.g. `${workspaceFolder}/.venv/bin/ck`.
- `contextKernel.portfolioRoot` — portfolio root (the dir containing `.context-kernel`).
  Leave empty to auto-detect by walking up from the active file / workspace folder.

## Interactions

- Click an entity or file node → opens that source file in the editor.
- Search box → dims everything except matching nodes and their neighbours.
- Min-confidence slider → hides low-confidence entities.
- Concept bridges checkbox → show/hide cross-repo concept hubs.
- Re-layout → re-runs the fcose layout.
