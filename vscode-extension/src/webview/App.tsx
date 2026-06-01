import {
  Background,
  Controls,
  type Edge,
  MarkerType,
  MiniMap,
  type Node,
  ReactFlow,
  ReactFlowProvider,
  useEdgesState,
  useNodesState,
} from "@xyflow/react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type { GraphExport } from "../shared/graph";
import { layout, type LayoutMode } from "./layout";
import { buildModel, defaultFocus, type Key, type Model, topNeighbors } from "./model";
import { type ConceptNodeData, type FileNodeData, nodeTypes } from "./nodes";
import { post } from "./vscode";

const EXPAND_CAP = 6; // neighbors pulled in per expand / initial focus
const basename = (p: string) => p.split("/").pop() || p;

// The two streams: prose (markdown/docs/ADRs) vs. everything else (source + config).
const DOC_EXT = new Set(["md", "mdx", "markdown", "rst", "txt", "adoc"]);
const isDocPath = (p: string): boolean => DOC_EXT.has(p.slice(p.lastIndexOf(".") + 1).toLowerCase());

interface Props {
  graph: GraphExport;
  activeProject: string | null;
  activeFile: string | null;
}

export default function App({ graph, activeProject, activeFile }: Props) {
  const [project, setProject] = useState(
    () => (activeProject && graph.projects.includes(activeProject) ? activeProject : graph.projects[0]) ?? "",
  );
  const [mode, setMode] = useState<LayoutMode>("streams");
  const [showBridges, setShowBridges] = useState(true);
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState<Set<Key>>(new Set());

  const model = useMemo(() => buildModel(graph, project), [graph, project]);

  // Seed the canvas: the active file if it's in this repo, else the highest-degree hub.
  useEffect(() => {
    const focus = activeFile && model.filesByPath.has(activeFile) ? activeFile : defaultFocus(model);
    const seed = new Set<Key>();
    if (focus) {
      seed.add(focus);
      for (const n of topNeighbors(model, focus, EXPAND_CAP)) {
        seed.add(n);
      }
    }
    setOpen(seed);
  }, [model, activeFile]);

  const expand = useCallback(
    (key: Key) => {
      setOpen((prev) => {
        const next = new Set(prev);
        for (const n of topNeighbors(model, key, EXPAND_CAP)) {
          next.add(n);
        }
        return next;
      });
    },
    [model],
  );

  const openInEditor = useCallback((path: string) => post({ type: "open", path }), []);

  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);

  // Rebuild + lay out whenever the open set, project, mode, or bridge toggle changes. A
  // signature of the visible keys keeps us from relaying out on every drag/selection.
  const signature = useMemo(
    () => [...open].sort().join("|") + `#${project}#${mode}#${showBridges}`,
    [open, project, mode, showBridges],
  );
  const lastSig = useRef<string>("");

  useEffect(() => {
    if (signature === lastSig.current) {
      return;
    }
    lastSig.current = signature;
    const { rfNodes, rfEdges } = buildElements(model, open, showBridges, { expand, openInEditor });
    let cancelled = false;
    layout(rfNodes, rfEdges, mode).then((positioned) => {
      if (!cancelled) {
        setNodes(positioned);
        setEdges(rfEdges);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [signature, model, open, showBridges, mode, expand, openInEditor, setNodes, setEdges]);

  const results = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) {
      return [];
    }
    const hits: { key: Key; label: string; kind: string }[] = [];
    for (const path of model.filesByPath.keys()) {
      if (basename(path).toLowerCase().includes(q)) {
        hits.push({ key: path, label: basename(path), kind: "file" });
      }
    }
    for (const c of model.conceptById.values()) {
      if (c.name.toLowerCase().includes(q)) {
        hits.push({ key: c.id, label: c.name, kind: "concept" });
      }
    }
    return hits.slice(0, 12);
  }, [query, model]);

  const openResult = (key: Key) => {
    setOpen((prev) => {
      const next = new Set(prev);
      next.add(key);
      for (const n of topNeighbors(model, key, EXPAND_CAP)) {
        next.add(n);
      }
      return next;
    });
    setQuery("");
  };

  const focusOnly = () => {
    const focus = activeFile && model.filesByPath.has(activeFile) ? activeFile : defaultFocus(model);
    setOpen(focus ? new Set([focus, ...topNeighbors(model, focus, EXPAND_CAP)]) : new Set());
  };

  return (
    <div className="ck-app">
      <header className="ck-toolbar">
        <label>
          Repo{" "}
          <select value={project} onChange={(e) => setProject(e.target.value)}>
            {graph.projects.map((p) => (
              <option key={p} value={p}>{p}</option>
            ))}
          </select>
        </label>
        <div className="ck-search">
          <input
            type="search"
            placeholder="Open a file or concept…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          {results.length > 0 && (
            <ul className="ck-results">
              {results.map((r) => (
                <li key={r.key} onMouseDown={() => openResult(r.key)}>
                  <span className={`ck-tag ck-tag-${r.kind}`}>{r.kind}</span> {r.label}
                </li>
              ))}
            </ul>
          )}
        </div>
        <label className="ck-seg">
          Layout
          <button className={mode === "streams" ? "on" : ""} onClick={() => setMode("streams")}>Streams</button>
          <button className={mode === "flow" ? "on" : ""} onClick={() => setMode("flow")}>Call flow</button>
          <button className={mode === "network" ? "on" : ""} onClick={() => setMode("network")}>Network</button>
        </label>
        <label className="ck-check">
          <input type="checkbox" checked={showBridges} onChange={(e) => setShowBridges(e.target.checked)} />
          Concept bridges
        </label>
        <button onClick={focusOnly}>Reset</button>
        <span className="ck-status">{nodes.length} panels · {edges.length} links</span>
      </header>
      <div className="ck-canvas">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          nodeTypes={nodeTypes}
          minZoom={0.05}
          maxZoom={2.5}
          fitView
          proOptions={{ hideAttribution: true }}
        >
          <Background gap={24} />
          <MiniMap pannable zoomable nodeStrokeWidth={2} />
          <Controls />
        </ReactFlow>
      </div>
    </div>
  );
}

interface Callbacks {
  expand: (key: Key) => void;
  openInEditor: (path: string) => void;
}

const PAIR_CAP = 8; // max distinct line-anchors drawn between any two panels

function buildElements(model: Model, open: Set<Key>, showBridges: boolean, cb: Callbacks) {
  const visible = new Set<Key>();
  for (const k of open) {
    if (model.conceptById.has(k) && !showBridges) {
      continue;
    }
    visible.add(k);
  }

  const hiddenCount = (key: Key): number => {
    let n = 0;
    for (const nb of model.neighbors.get(key) ?? []) {
      if (!visible.has(nb) && !(model.conceptById.has(nb) && !showBridges)) {
        n++;
      }
    }
    return n;
  };

  // Edges first: one per distinct (sourceLine,targetLine) pair, so multiple lines of one file
  // can connect to multiple lines of another. Collect the lines each node participates in so
  // the panel can render a handle per line.
  const rfEdges: Edge[] = [];
  const linesByNode = new Map<Key, Set<number>>();
  const addLine = (key: Key, line: number | null) => {
    if (line == null) {
      return;
    }
    (linesByNode.get(key) ?? linesByNode.set(key, new Set()).get(key)!).add(line);
  };
  let i = 0;
  for (const s of visible) {
    for (const [t, agg] of model.out.get(s) ?? []) {
      if (!visible.has(t)) {
        continue;
      }
      const isCall = agg.kinds.has("calls");
      const cls = agg.bridge ? "ck-edge-bridge" : isCall ? "ck-edge-call" : "ck-edge-rel";
      const pairs = [...agg.pairs.values()].slice(0, PAIR_CAP);
      for (const { s: sLine, t: tLine } of pairs) {
        addLine(s, sLine);
        addLine(t, tLine);
        rfEdges.push({
          id: `e${i++}`,
          source: s,
          target: t,
          sourceHandle: sLine != null ? `line-${sLine}` : "line-node",
          targetHandle: tLine != null ? `line-${tLine}` : "line-node",
          type: "smoothstep",
          animated: isCall,
          className: cls,
          markerEnd: { type: MarkerType.ArrowClosed, width: 13, height: 13 },
          data: { kinds: [...agg.kinds].join(", ") },
        });
      }
    }
  }

  const rfNodes: Node[] = [];
  for (const key of visible) {
    if (model.conceptById.has(key)) {
      const c = model.conceptById.get(key)!;
      rfNodes.push({
        id: key,
        type: "concept",
        position: { x: 0, y: 0 },
        data: { id: key, label: c.name, hidden: hiddenCount(key), onExpand: cb.expand, stream: "concept" } as ConceptNodeData,
      });
    } else {
      const f = model.filesByPath.get(key);
      rfNodes.push({
        id: key,
        type: "file",
        position: { x: 0, y: 0 },
        data: {
          path: key,
          label: basename(key),
          scope: f?.scope ?? "",
          symbolCount: model.symbolsOfFile.get(key)?.length ?? 0,
          hidden: hiddenCount(key),
          lines: [...(linesByNode.get(key) ?? [])].sort((a, b) => a - b),
          onExpand: cb.expand,
          onOpen: cb.openInEditor,
          stream: isDocPath(key) ? "doc" : "code",
        } as FileNodeData,
      });
    }
  }

  return { rfNodes, rfEdges };
}

export function Root(props: Props) {
  return (
    <ReactFlowProvider>
      <App {...props} />
    </ReactFlowProvider>
  );
}
