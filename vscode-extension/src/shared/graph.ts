// Mirrors the JSON emitted by `ck graph` (see context_kernel/graph_export.py).
// schema_version is bumped on the Python side when this shape changes.

export interface GraphNode {
  id: string;
  name: string;
  kind: string;
  project: string | null; // null === global ontology concept hub (cross-repo bridge)
  scope: string | null; // owning scope (directory) in the containment spine, e.g. "src/bot"
  parent: string | null; // id of the `contains` anchor (module) for code members; null otherwise
  sources: string[]; // project-relative paths, e.g. "src/foo.py"
  is_concept: boolean;
  confidence: number;
  def_line?: number | null; // 0-based definition line (for line-anchored edges)
  // Omitted by `ck graph --slim` (the visualizer doesn't render them):
  centrality?: number;
  source_tier?: number;
  description?: string;
}

export interface GraphFile {
  path: string; // portfolio-relative, project-prefixed, e.g. "model-time/src/foo.py"
  project: string | null;
  scope: string | null; // directory scope this file belongs to (its spine parent)
  anchor_id: string | null; // the `module` entity that represents this file when collapsed
  entity_ids: string[];
}

export interface GraphEdge {
  source: string;
  target: string;
  kind: string;
  cross_repo: boolean;
  sourceLine?: number | null; // 0-based call/import site line in the source file
  targetLine?: number | null; // 0-based definition line in the target file
  // Omitted by `ck graph --slim`:
  weight?: number;
  drift?: number;
}

export interface GraphExport {
  schema_version: number;
  graph_commit: string;
  projects: string[];
  files: GraphFile[];
  nodes: GraphNode[];
  edges: GraphEdge[];
}

// Messages exchanged between the extension host and the webview.
export type HostToWebview =
  | { type: "graph"; graph: GraphExport; activeProject: string | null; activeFile: string | null }
  | { type: "code"; path: string; text: string; lang: string } // file contents for a code panel
  | { type: "codeError"; path: string };

export type WebviewToHost =
  | { type: "ready" }
  | { type: "open"; path: string } // open a file in the editor (portfolio-relative)
  | { type: "fetchCode"; path: string } // request a file's contents for a code panel
  | { type: "error"; message: string };
