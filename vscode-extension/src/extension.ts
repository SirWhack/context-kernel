import { execFile } from "node:child_process";
import { promises as fs } from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { promisify } from "node:util";
import * as vscode from "vscode";

import type { GraphExport, HostToWebview, WebviewToHost } from "./shared/graph";

const execFileP = promisify(execFile);

// A single reused panel + the root it was opened against, so "Refresh" can re-post into it.
let currentPanel: vscode.WebviewPanel | undefined;
let currentRoot: string | undefined;

export function activate(context: vscode.ExtensionContext): void {
  context.subscriptions.push(
    vscode.commands.registerCommand("contextKernel.showGraph", () => showGraph(context, false)),
    vscode.commands.registerCommand("contextKernel.refreshGraph", () => showGraph(context, true)),
  );
}

export function deactivate(): void {
  // no-op
}

async function showGraph(context: vscode.ExtensionContext, forceRefresh: boolean): Promise<void> {
  const activeUri = vscode.window.activeTextEditor?.document.uri;
  const portfolioRoot = currentRoot && (forceRefresh || currentPanel)
    ? currentRoot
    : await resolvePortfolioRoot(activeUri);
  if (!portfolioRoot) {
    vscode.window.showErrorMessage(
      "Context Kernel: could not find a .context-kernel directory. Set contextKernel.portfolioRoot.",
    );
    return;
  }

  // Read the cached view first (instant); only shell out to `ck graph` on a miss or refresh —
  // recomputing pays a ~2s backend load every time, which is what made "Show Graph" feel slow.
  let graph: GraphExport;
  try {
    graph = await loadGraph(portfolioRoot, forceRefresh);
  } catch (err) {
    vscode.window.showErrorMessage(`Context Kernel: ck graph failed — ${describe(err)}`);
    return;
  }

  const activeProject = projectForFile(graph, portfolioRoot, activeUri);
  const activeFile = activeFilePath(graph, portfolioRoot, activeUri);
  const message: HostToWebview = { type: "graph", graph, activeProject, activeFile };

  // Reuse the open panel if there is one (e.g. on Refresh) instead of stacking duplicates.
  if (currentPanel) {
    currentPanel.reveal(vscode.ViewColumn.Active);
    void currentPanel.webview.postMessage(message);
    return;
  }

  const panel = vscode.window.createWebviewPanel(
    "contextKernelGraph",
    "Context Kernel Graph",
    vscode.ViewColumn.Active,
    {
      enableScripts: true,
      retainContextWhenHidden: true,
      localResourceRoots: [vscode.Uri.joinPath(context.extensionUri, "media")],
    },
  );
  currentPanel = panel;
  currentRoot = portfolioRoot;
  panel.onDidDispose(() => {
    currentPanel = undefined;
    currentRoot = undefined;
  }, undefined, context.subscriptions);

  panel.webview.html = renderHtml(panel.webview, context.extensionUri);

  panel.webview.onDidReceiveMessage(
    (msg: WebviewToHost) => handleWebviewMessage(msg, portfolioRoot, panel.webview),
    undefined,
    context.subscriptions,
  );

  // The webview posts {type:"ready"} once its listener is attached; send then to avoid a race.
  const ready = panel.webview.onDidReceiveMessage((m: WebviewToHost) => {
    if (m.type === "ready") {
      void panel.webview.postMessage(message);
    }
  });
  context.subscriptions.push(ready);
}

async function handleWebviewMessage(
  msg: WebviewToHost,
  portfolioRoot: string,
  webview: vscode.Webview,
): Promise<void> {
  if (msg.type === "open") {
    // msg.path is portfolio-relative and project-prefixed (e.g. "model-time/src/foo.py").
    const abs = path.join(portfolioRoot, msg.path);
    try {
      const doc = await vscode.workspace.openTextDocument(vscode.Uri.file(abs));
      await vscode.window.showTextDocument(doc, { preview: true, viewColumn: vscode.ViewColumn.One });
    } catch {
      vscode.window.showWarningMessage(`Context Kernel: could not open ${msg.path}`);
    }
  } else if (msg.type === "fetchCode") {
    // Lazy-load a file's contents for a code panel on the canvas.
    const abs = path.join(portfolioRoot, msg.path);
    try {
      const text = await fs.readFile(abs, "utf-8");
      const reply: HostToWebview = { type: "code", path: msg.path, text, lang: langOf(msg.path) };
      void webview.postMessage(reply);
    } catch {
      void webview.postMessage({ type: "codeError", path: msg.path } satisfies HostToWebview);
    }
  } else if (msg.type === "error") {
    vscode.window.showErrorMessage(`Context Kernel graph: ${msg.message}`);
  }
}

// Highlight.js language hint from the file extension; "" lets Highlight.js auto-detect.
function langOf(p: string): string {
  const ext = p.slice(p.lastIndexOf(".") + 1).toLowerCase();
  const map: Record<string, string> = {
    ts: "typescript", tsx: "typescript", js: "javascript", jsx: "javascript",
    py: "python", rs: "rust", go: "go", java: "java", rb: "ruby", md: "markdown",
    json: "json", yaml: "yaml", yml: "yaml", toml: "ini", sh: "bash", html: "xml",
    css: "css", sql: "sql", tf: "hcl",
  };
  return map[ext] ?? "";
}

/** Walk up from a starting dir looking for a `.context-kernel` directory. */
async function findContextKernelRoot(start: string): Promise<string | undefined> {
  let dir = start;
  // Stop at filesystem root.
  while (true) {
    try {
      const stat = await fs.stat(path.join(dir, ".context-kernel"));
      if (stat.isDirectory()) {
        return dir;
      }
    } catch {
      // not here; keep climbing
    }
    const parent = path.dirname(dir);
    if (parent === dir) {
      return undefined;
    }
    dir = parent;
  }
}

async function resolvePortfolioRoot(activeUri?: vscode.Uri): Promise<string | undefined> {
  const configured = vscode.workspace.getConfiguration("contextKernel").get<string>("portfolioRoot");
  if (configured && configured.trim()) {
    return path.resolve(configured.trim());
  }
  const starts: string[] = [];
  if (activeUri && activeUri.scheme === "file") {
    starts.push(path.dirname(activeUri.fsPath));
  }
  for (const folder of vscode.workspace.workspaceFolders ?? []) {
    starts.push(folder.uri.fsPath);
  }
  for (const start of starts) {
    const found = await findContextKernelRoot(start);
    if (found) {
      return found;
    }
  }
  return undefined;
}

const cachePathFor = (portfolioRoot: string): string =>
  path.join(portfolioRoot, ".context-kernel", "views", "graph.json");

/** Cache-first graph load. The cached view is regenerated by `ck` (manually or in the
 *  pre-commit hook) and served as-is — matching the kernel's "no runtime synthesis" model.
 *  Use "Context Kernel: Refresh Graph" to force a re-run after re-ingesting. */
async function loadGraph(portfolioRoot: string, forceRefresh: boolean): Promise<GraphExport> {
  const cachePath = cachePathFor(portfolioRoot);
  if (!forceRefresh) {
    try {
      const cached = await fs.readFile(cachePath, "utf-8");
      return JSON.parse(cached) as GraphExport;
    } catch {
      // no cache / unreadable → fall through to a live export
    }
  }
  const graph = await runGraphExport(portfolioRoot);
  // Best-effort: persist the live export as the cache so the next open is instant.
  try {
    await fs.mkdir(path.dirname(cachePath), { recursive: true });
    await fs.writeFile(cachePath, JSON.stringify(graph), "utf-8");
  } catch {
    // a read-only or missing views dir is non-fatal — we still have the graph in memory
  }
  return graph;
}

async function runGraphExport(portfolioRoot: string): Promise<GraphExport> {
  const ckPath = (vscode.workspace.getConfiguration("contextKernel").get<string>("ckPath") || "ck").trim();
  const resolvedCk = ckPath.replace("${workspaceFolder}", portfolioRoot);
  const outFile = path.join(os.tmpdir(), `ck-graph-${process.pid}-${Date.now()}.json`);
  await execFileP(resolvedCk, ["graph", "--portfolio", portfolioRoot, "--slim", "--out", outFile], {
    maxBuffer: 256 * 1024 * 1024,
  });
  const raw = await fs.readFile(outFile, "utf-8");
  await fs.rm(outFile, { force: true });
  return JSON.parse(raw) as GraphExport;
}

/** Best-effort: which project does the active file belong to? Matches a project-prefixed
 *  file path in the export against the active file's portfolio-relative path. */
function projectForFile(graph: GraphExport, portfolioRoot: string, activeUri?: vscode.Uri): string | null {
  if (!activeUri || activeUri.scheme !== "file") {
    return graph.projects[0] ?? null;
  }
  const rel = path.relative(portfolioRoot, activeUri.fsPath).split(path.sep).join("/");
  const hit = graph.files.find((f) => f.path === rel);
  if (hit) {
    return hit.project;
  }
  // Fall back to first path segment matching a known project.
  const seg = rel.split("/")[0];
  if (graph.projects.includes(seg)) {
    return seg;
  }
  return graph.projects[0] ?? null;
}

/** The active editor's portfolio-relative path, if that file is in the exported graph. */
function activeFilePath(graph: GraphExport, portfolioRoot: string, activeUri?: vscode.Uri): string | null {
  if (!activeUri || activeUri.scheme !== "file") {
    return null;
  }
  const rel = path.relative(portfolioRoot, activeUri.fsPath).split(path.sep).join("/");
  return graph.files.some((f) => f.path === rel) ? rel : null;
}

function renderHtml(webview: vscode.Webview, extensionUri: vscode.Uri): string {
  const scriptUri = webview.asWebviewUri(vscode.Uri.joinPath(extensionUri, "media", "main.js"));
  const styleUri = webview.asWebviewUri(vscode.Uri.joinPath(extensionUri, "media", "style.css"));
  // esbuild emits the bundled CSS (React Flow base styles + Highlight.js theme) next to main.js.
  const bundleCssUri = webview.asWebviewUri(vscode.Uri.joinPath(extensionUri, "media", "main.css"));
  const nonce = makeNonce();
  const csp = [
    `default-src 'none'`,
    `style-src ${webview.cspSource} 'unsafe-inline'`,
    `script-src 'nonce-${nonce}'`,
    `font-src ${webview.cspSource} data:`,
    `img-src ${webview.cspSource} data:`,
  ].join("; ");

  return /* html */ `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta http-equiv="Content-Security-Policy" content="${csp}" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <link rel="stylesheet" href="${bundleCssUri}" />
  <link rel="stylesheet" href="${styleUri}" />
  <title>Context Kernel Graph</title>
</head>
<body>
  <div id="root"></div>
  <script nonce="${nonce}" src="${scriptUri}"></script>
</body>
</html>`;
}

function makeNonce(): string {
  const chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789";
  let out = "";
  for (let i = 0; i < 32; i++) {
    out += chars.charAt(Math.floor(Math.random() * chars.length));
  }
  return out;
}

function describe(err: unknown): string {
  if (err && typeof err === "object" && "message" in err) {
    return String((err as { message: unknown }).message);
  }
  return String(err);
}
