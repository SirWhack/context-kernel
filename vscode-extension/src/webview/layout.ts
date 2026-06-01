// Canvas layouts (ELK). The default "streams" mode is a two-lane waterfall: documentation
// files cascade down the left lane, code files down the right, and concept hubs sit in the
// center gutter bridging them — so expanding a concept reads as two clean columns instead of
// a hairball. "flow" is a single left→right call graph; "network" is a force/stress layout.
import ELK from "elkjs/lib/elk.bundled.js";
import type { Edge, Node } from "@xyflow/react";

const elk = new ELK();

export type LayoutMode = "streams" | "flow" | "network";
export type Stream = "doc" | "code" | "concept";

interface Box {
  x: number;
  y: number;
  w: number;
  h: number;
}

function dims(n: Node): { w: number; h: number } {
  const isConcept = n.type === "concept";
  return {
    w: n.measured?.width ?? (isConcept ? 180 : 300),
    h: n.measured?.height ?? (isConcept ? 44 : 200),
  };
}

const streamOf = (n: Node): Stream => ((n.data as { stream?: Stream }).stream ?? "code");

// One ELK pass. `dir` DOWN = waterfall (layers stack vertically), RIGHT = call flow.
async function elkPass(
  nodes: Node[],
  edges: Edge[],
  options: Record<string, string>,
): Promise<Map<string, Box>> {
  const out = new Map<string, Box>();
  if (nodes.length === 0) {
    return out;
  }
  const children = nodes.map((n) => {
    const { w, h } = dims(n);
    return { id: n.id, width: w, height: h };
  });
  try {
    const res = await elk.layout({
      id: "root",
      layoutOptions: options,
      children,
      edges: edges.map((e) => ({ id: e.id, sources: [e.source], targets: [e.target] })),
    });
    for (const c of res.children ?? []) {
      out.set(c.id, { x: c.x ?? 0, y: c.y ?? 0, w: c.width ?? 300, h: c.height ?? 200 });
    }
  } catch {
    nodes.forEach((n, i) => {
      const { w, h } = dims(n);
      out.set(n.id, { x: 0, y: i * (h + 48), w, h });
    });
  }
  return out;
}

function maxRight(pos: Map<string, Box>): number {
  let m = 0;
  for (const p of pos.values()) {
    m = Math.max(m, p.x + p.w);
  }
  return m;
}

const WATERFALL = {
  "elk.algorithm": "layered",
  "elk.direction": "DOWN",
  "elk.layered.spacing.nodeNodeBetweenLayers": "80",
  "elk.spacing.nodeNode": "44",
  "elk.layered.considerModelOrder.strategy": "NODES_AND_EDGES",
};

async function streamsLayout(nodes: Node[], edges: Edge[]): Promise<Node[]> {
  const doc = nodes.filter((n) => streamOf(n) === "doc");
  const code = nodes.filter((n) => streamOf(n) === "code");
  const concepts = nodes.filter((n) => streamOf(n) === "concept");

  const idsOf = (arr: Node[]) => new Set(arr.map((n) => n.id));
  const within = (set: Set<string>) => edges.filter((e) => set.has(e.source) && set.has(e.target));

  // Lay out each stream as its own waterfall, using only the edges internal to that stream so
  // cross-stream links don't distort the columns (they're still drawn, routed diagonally).
  const [docPos, codePos] = await Promise.all([
    elkPass(doc, within(idsOf(doc)), WATERFALL),
    elkPass(code, within(idsOf(code)), WATERFALL),
  ]);

  const LANE_GAP = 340;
  const docWidth = Math.max(maxRight(docPos), doc.length ? 300 : 0);
  const codeOffsetX = docWidth + LANE_GAP;
  const conceptX = docWidth + LANE_GAP / 2 - 90;

  const final = new Map<string, { x: number; y: number }>();
  for (const [id, p] of docPos) {
    final.set(id, { x: p.x, y: p.y });
  }
  for (const [id, p] of codePos) {
    final.set(id, { x: p.x + codeOffsetX, y: p.y });
  }

  // Concepts ride the center gutter, each pulled toward the average height of the nodes it
  // links, then de-overlapped top-to-bottom.
  const avgNeighborY = (id: string): number => {
    const ys: number[] = [];
    for (const e of edges) {
      if (e.source === id && final.has(e.target)) {
        ys.push(final.get(e.target)!.y);
      }
      if (e.target === id && final.has(e.source)) {
        ys.push(final.get(e.source)!.y);
      }
    }
    return ys.length ? ys.reduce((a, b) => a + b, 0) / ys.length : 0;
  };
  const ordered = [...concepts].sort((a, b) => avgNeighborY(a.id) - avgNeighborY(b.id));
  let lastY = -Infinity;
  const STEP = 72;
  for (const c of ordered) {
    let y = avgNeighborY(c.id);
    if (y < lastY + STEP) {
      y = lastY + STEP;
    }
    lastY = y;
    final.set(c.id, { x: conceptX, y });
  }

  return nodes.map((n) => (final.has(n.id) ? { ...n, position: final.get(n.id)! } : n));
}

const SINGLE: Record<Exclude<LayoutMode, "streams">, Record<string, string>> = {
  flow: {
    "elk.algorithm": "layered",
    "elk.direction": "RIGHT",
    "elk.layered.spacing.nodeNodeBetweenLayers": "120",
    "elk.spacing.nodeNode": "60",
    "elk.layered.considerModelOrder.strategy": "NODES_AND_EDGES",
  },
  network: {
    "elk.algorithm": "stress",
    "elk.stress.desiredEdgeLength": "260",
    "elk.spacing.nodeNode": "80",
  },
};

export async function layout(nodes: Node[], edges: Edge[], mode: LayoutMode): Promise<Node[]> {
  if (nodes.length === 0) {
    return nodes;
  }
  if (mode === "streams") {
    return streamsLayout(nodes, edges);
  }
  const pos = await elkPass(nodes, edges, SINGLE[mode]);
  return nodes.map((n) => {
    const p = pos.get(n.id);
    return p ? { ...n, position: { x: p.x, y: p.y } } : n;
  });
}
