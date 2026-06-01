// Turns a GraphExport into the indexes the canvas needs. The canvas works at FILE granularity
// (each file is a code panel) plus concept hubs; entity→entity edges from the graph are
// aggregated up to the file panels that contain their endpoints (we have no line numbers to
// anchor finer, so panel-to-panel is the honest resolution for now).
import type { GraphEdge, GraphExport, GraphFile, GraphNode } from "../shared/graph";

// A canvas key is either a file path or a concept-hub node id.
export type Key = string;

export interface LinePair {
  s: number | null; // source-file line (call/import site), null = node-level
  t: number | null; // target-file line (definition), null = node-level
}

export interface EdgeAgg {
  kinds: Set<string>; // edge kinds collapsed onto this (source→target) pair
  bridge: boolean; // touches a concept hub (drawn as a dashed bridge)
  pairs: Map<string, LinePair>; // distinct (sourceLine,targetLine) anchors between the two panels
}

export interface Model {
  project: string;
  filesByPath: Map<string, GraphFile>;
  conceptById: Map<string, GraphNode>;
  fileOfEntity: Map<string, Key>; // entity id → its primary file path
  symbolsOfFile: Map<string, GraphNode[]>; // file path → its class/function/module entities
  out: Map<Key, Map<Key, EdgeAgg>>; // directed, deduped canvas edges
  neighbors: Map<Key, Set<Key>>; // undirected adjacency (for expansion)
  degree: Map<Key, number>; // undirected degree (for picking a focus / capping)
}

const SYMBOL_KINDS = new Set(["module", "class", "function", "interface", "method"]);

// Markdown/prose extensions — a file is "doc", everything else "code". Mirrors App's split.
const DOC_EXT = new Set(["md", "mdx", "markdown", "rst", "txt", "adoc"]);
const isDocPath = (p: string): boolean => DOC_EXT.has(p.slice(p.lastIndexOf(".") + 1).toLowerCase());

function addNeighbor(neighbors: Map<Key, Set<Key>>, a: Key, b: Key): void {
  (neighbors.get(a) ?? neighbors.set(a, new Set()).get(a)!).add(b);
  (neighbors.get(b) ?? neighbors.set(b, new Set()).get(b)!).add(a);
}

export function buildModel(graph: GraphExport, project: string): Model {
  const filesByPath = new Map<string, GraphFile>();
  for (const f of graph.files) {
    if (f.project === project) {
      filesByPath.set(f.path, f);
    }
  }

  const conceptById = new Map<string, GraphNode>();
  const nodeById = new Map<string, GraphNode>();
  for (const n of graph.nodes) {
    nodeById.set(n.id, n);
    if (n.is_concept) {
      conceptById.set(n.id, n);
    }
  }

  const fileOfEntity = new Map<string, Key>();
  const symbolsOfFile = new Map<string, GraphNode[]>();
  for (const f of filesByPath.values()) {
    const syms: GraphNode[] = [];
    for (const eid of f.entity_ids) {
      // An entity's "home" panel is its code file when it has one — a class/module merged with
      // its doc mentions must surface as the .py panel, not the first doc that names it.
      const prev = fileOfEntity.get(eid);
      if (prev === undefined || (isDocPath(prev) && !isDocPath(f.path))) {
        fileOfEntity.set(eid, f.path);
      }
      const n = nodeById.get(eid);
      if (n && !n.is_concept && SYMBOL_KINDS.has(n.kind)) {
        syms.push(n);
      }
    }
    symbolsOfFile.set(f.path, syms);
  }

  // Resolve an entity/concept endpoint to its canvas key (file path or concept id).
  const keyOf = (id: string): Key | null => {
    if (conceptById.has(id)) {
      return id;
    }
    return fileOfEntity.get(id) ?? null;
  };

  const out = new Map<Key, Map<Key, EdgeAgg>>();
  const neighbors = new Map<Key, Set<Key>>();
  const record = (s: Key, t: Key, e: GraphEdge) => {
    const bridge = e.cross_repo || conceptById.has(e.source) || conceptById.has(e.target);
    const row = out.get(s) ?? out.set(s, new Map()).get(s)!;
    const agg = row.get(t) ?? { kinds: new Set<string>(), bridge: false, pairs: new Map<string, LinePair>() };
    agg.kinds.add(e.kind);
    agg.bridge = agg.bridge || bridge;
    // A line anchor is only meaningful for a file endpoint (concepts have no lines).
    const sLine = conceptById.has(e.source) ? null : (e.sourceLine ?? null);
    const tLine = conceptById.has(e.target) ? null : (e.targetLine ?? null);
    agg.pairs.set(`${sLine}:${tLine}`, { s: sLine, t: tLine });
    row.set(t, agg);
    addNeighbor(neighbors, s, t);
  };

  for (const e of graph.edges) {
    const s = keyOf(e.source);
    const t = keyOf(e.target);
    if (!s || !t || s === t) {
      continue; // unresolved endpoint or within a single file panel
    }
    record(s, t, e);
  }

  const degree = new Map<Key, number>();
  for (const [k, set] of neighbors) {
    degree.set(k, set.size);
  }

  return { project, filesByPath, conceptById, fileOfEntity, symbolsOfFile, out, neighbors, degree };
}

/** The highest-degree file — a sensible default focus when no active file is known. */
export function defaultFocus(model: Model): Key | null {
  let best: Key | null = null;
  let bestDeg = -1;
  for (const path of model.filesByPath.keys()) {
    const d = model.degree.get(path) ?? 0;
    if (d > bestDeg) {
      best = path;
      bestDeg = d;
    }
  }
  return best ?? (model.filesByPath.keys().next().value ?? null);
}

/** Up to `cap` neighbors of `key`, highest-degree first (most informative expansion). */
export function topNeighbors(model: Model, key: Key, cap: number): Key[] {
  const ns = [...(model.neighbors.get(key) ?? [])];
  ns.sort((a, b) => (model.degree.get(b) ?? 0) - (model.degree.get(a) ?? 0));
  return ns.slice(0, cap);
}
