// Custom React Flow node renderers. A FileNode is a code panel of real, syntax-highlighted
// source (lazily fetched from the host) with a Handle PER PARTICIPATING LINE, so edges anchor
// to exact lines. A ConceptNode is an ontology hub. Both expose an "expand" affordance.
import { Handle, Position, type NodeProps, useUpdateNodeInternals } from "@xyflow/react";
import hljs from "highlight.js/lib/common";
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";

import { fetchCode } from "./vscode";

const MAX_LINES = 1200; // cap rendered lines per panel; handles beyond clamp to the last line
const HEADER_H = 24;
const LINE_H = 15;
const PAD_TOP = 6;

const escapeHtml = (s: string): string =>
  s.replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" })[c] || c);

// Highlight.js returns one HTML blob where a span can straddle newlines, so we can't just
// split on "\n". Walk the highlighted DOM keeping the open-tag stack; on each newline close
// all open tags, flush the line, and reopen them — yielding one self-contained HTML string
// per source line (technique from code-canvas). Each becomes <span class="ck-line" data-line>.
function highlightToLines(text: string, lang: string): string[] {
  let highlighted: string;
  try {
    highlighted = lang && hljs.getLanguage(lang)
      ? hljs.highlight(text, { language: lang, ignoreIllegals: true }).value
      : hljs.highlightAuto(text).value;
  } catch {
    highlighted = escapeHtml(text);
  }

  const doc = new DOMParser().parseFromString(`<pre>${highlighted}</pre>`, "text/html");
  const root = doc.body.firstChild as HTMLElement | null;
  const lines: string[] = [];
  const stack: string[] = [];
  let current = "";
  const openAll = () => stack.join("");
  const closeAll = () => stack.map(() => "</span>").join("");
  const flush = () => {
    lines.push(current);
    current = "";
  };
  const walk = (node: ChildNode): void => {
    if (node.nodeType === Node.TEXT_NODE) {
      const parts = (node.textContent ?? "").split(/\r\n|\n/);
      for (let i = 0; i < parts.length; i++) {
        current += escapeHtml(parts[i]);
        if (i < parts.length - 1) {
          current += closeAll();
          flush();
          current += openAll();
        }
      }
      return;
    }
    if (node.nodeType === Node.ELEMENT_NODE) {
      const el = node as HTMLElement;
      const cls = el.getAttribute("class") ?? "";
      const open = `<span class="${cls}">`;
      current += open;
      stack.push(open);
      el.childNodes.forEach(walk);
      stack.pop();
      current += "</span>";
    }
  };
  if (root) {
    root.childNodes.forEach(walk);
  }
  flush();
  return lines;
}

export type Stream = "doc" | "code" | "concept";

export interface FileNodeData {
  path: string;
  label: string;
  scope: string;
  symbolCount: number;
  hidden: number; // unopened neighbor count
  stream: Stream;
  lines: number[]; // 0-based lines that have an edge → get a per-line handle
  onExpand: (key: string) => void;
  onOpen: (path: string) => void;
  [key: string]: unknown;
}

export interface ConceptNodeData {
  id: string;
  label: string;
  hidden: number;
  stream: Stream;
  onExpand: (key: string) => void;
  [key: string]: unknown;
}

export function FileNode({ id, data, selected }: NodeProps & { data: FileNodeData }) {
  const [lineHtml, setLineHtml] = useState<string[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [tops, setTops] = useState<Map<number, number>>(new Map());
  const rootRef = useRef<HTMLDivElement>(null);
  const codeRef = useRef<HTMLPreElement>(null);
  const updateNodeInternals = useUpdateNodeInternals();

  useEffect(() => {
    let live = true;
    fetchCode(data.path).then((blob) => {
      if (!live) {
        return;
      }
      if (!blob) {
        setFailed(true);
        return;
      }
      setLineHtml(highlightToLines(blob.text, blob.lang).slice(0, MAX_LINES));
    });
    return () => {
      live = false;
    };
  }, [data.path]);

  // Measure each rendered line's vertical center, CLAMPED to the visible code viewport: a line
  // scrolled above the box pins to its top edge, one scrolled below pins to its bottom — so an
  // edge to off-screen code points at the box edge instead of flying off. rAF-throttled, and we
  // tell React Flow to re-read handle geometry (required in v12).
  useLayoutEffect(() => {
    const root = rootRef.current;
    const pre = codeRef.current;
    if (!root || !pre || lineHtml === null) {
      return;
    }
    let raf = 0;
    const measure = () => {
      const rootRect = root.getBoundingClientRect();
      const preRect = pre.getBoundingClientRect();
      const preTop = preRect.top - rootRect.top; // code area's offset within the node
      const viewH = pre.clientHeight;
      const next = new Map<number, number>();
      pre.querySelectorAll<HTMLElement>("span.ck-line").forEach((sp) => {
        const ln = Number(sp.dataset.line);
        const r = sp.getBoundingClientRect();
        const centerInView = r.top + r.height / 2 - preRect.top; // relative to the viewport
        const clamped = Math.max(0, Math.min(centerInView, viewH)); // pin to top/bottom edge
        next.set(ln, preTop + clamped);
      });
      setTops(next);
      updateNodeInternals(id);
    };
    const schedule = () => {
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(measure);
    };
    measure();
    const ro = new ResizeObserver(schedule);
    ro.observe(pre);
    pre.addEventListener("scroll", schedule, { passive: true });
    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
      pre.removeEventListener("scroll", schedule);
    };
  }, [lineHtml, id, updateNodeInternals]);

  const rendered = lineHtml?.length ?? 0;
  // Lines beyond what's rendered clamp to the last line; until measured, estimate from line
  // height (also clamped into the code box so an early estimate can't fly off either).
  const handleTop = (ln: number): number => {
    const clamped = rendered ? Math.min(ln, rendered - 1) : ln;
    const measured = tops.get(clamped);
    if (measured !== undefined) {
      return measured;
    }
    const est = HEADER_H + PAD_TOP + clamped * LINE_H;
    return Math.min(est, HEADER_H + 420); // don't exceed the code box height before measuring
  };

  return (
    <div ref={rootRef} className={`ck-file ck-${data.stream}${selected ? " selected" : ""}`}>
      {/* Node-level fallback handles (edges with no line use these). */}
      <Handle type="target" position={Position.Left} id="line-node" />
      <Handle type="source" position={Position.Right} id="line-node" />
      {/* Per-line handles for lines that participate in an edge. */}
      {data.lines.map((ln) => (
        <span key={ln}>
          <Handle type="target" position={Position.Left} id={`line-${ln}`} style={{ top: handleTop(ln) }} />
          <Handle type="source" position={Position.Right} id={`line-${ln}`} style={{ top: handleTop(ln) }} />
        </span>
      ))}
      <div className="ck-file-head">
        <span className="ck-file-badge">{data.stream === "doc" ? "DOC" : "CODE"}</span>
        <span className="ck-file-name" title={data.path}>{data.label}</span>
        <span className="ck-file-scope">{data.scope}</span>
        <span className="ck-spacer" />
        <button className="ck-btn" title="Open in editor" onClick={() => data.onOpen(data.path)}>↗</button>
        {data.hidden > 0 && (
          <button className="ck-btn" title="Expand neighbors" onClick={() => data.onExpand(data.path)}>
            +{data.hidden}
          </button>
        )}
      </div>
      <pre ref={codeRef} className="ck-code hljs">
        {failed ? (
          <code className="ck-dim">(could not read file)</code>
        ) : lineHtml === null ? (
          <code className="ck-dim">loading…</code>
        ) : (
          lineHtml.map((h, i) => (
            <span key={i} className="ck-line" data-line={i} dangerouslySetInnerHTML={{ __html: h || "&nbsp;" }} />
          ))
        )}
      </pre>
    </div>
  );
}

export function ConceptNode({ data, selected }: NodeProps & { data: ConceptNodeData }) {
  const label = useMemo(() => data.label, [data.label]);
  return (
    <div className={`ck-concept${selected ? " selected" : ""}`}>
      <Handle type="target" position={Position.Left} />
      <span className="ck-concept-label">◆ {label}</span>
      {data.hidden > 0 && (
        <button className="ck-btn" title="Expand linked code" onClick={() => data.onExpand(data.id)}>
          +{data.hidden}
        </button>
      )}
      <Handle type="source" position={Position.Right} />
    </div>
  );
}

export const nodeTypes = { file: FileNode, concept: ConceptNode };
