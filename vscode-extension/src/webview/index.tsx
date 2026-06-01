// Webview entry: mount the React Flow canvas and route host messages. The bundled CSS
// (React Flow base + Highlight.js theme, imported here) is emitted as media/main.css.
import "@xyflow/react/dist/style.css";
import "highlight.js/styles/github-dark.css";

import { createRoot } from "react-dom/client";

import type { GraphExport, HostToWebview } from "../shared/graph";
import { Root } from "./App";
import { handleCodeMessage, post } from "./vscode";

const root = createRoot(document.getElementById("root")!);

let state: { graph: GraphExport; activeProject: string | null; activeFile: string | null } | null = null;

function render(): void {
  if (state) {
    root.render(<Root graph={state.graph} activeProject={state.activeProject} activeFile={state.activeFile} />);
  }
}

window.addEventListener("message", (event: MessageEvent<HostToWebview>) => {
  const msg = event.data;
  if (handleCodeMessage(msg)) {
    return; // code reply resolved a fetch promise; no app re-render needed
  }
  if (msg.type === "graph") {
    state = { graph: msg.graph, activeProject: msg.activeProject, activeFile: msg.activeFile };
    render();
  }
});

post({ type: "ready" });
