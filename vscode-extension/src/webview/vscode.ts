// Thin wrapper over the VS Code webview API plus an on-demand code-fetch cache. The host
// reads file contents lazily (one round-trip per file panel) so we never ship every file's
// source up front.
import type { HostToWebview, WebviewToHost } from "../shared/graph";

declare function acquireVsCodeApi(): {
  postMessage(msg: WebviewToHost): void;
  getState(): unknown;
  setState(state: unknown): void;
};

export const vscode = acquireVsCodeApi();

export function post(msg: WebviewToHost): void {
  vscode.postMessage(msg);
}

export interface CodeBlob {
  text: string;
  lang: string;
}

const cache = new Map<string, CodeBlob | null>();
const pending = new Map<string, ((blob: CodeBlob | null) => void)[]>();

/** Resolve a file's contents (cached). Returns null if the host could not read it. */
export function fetchCode(path: string): Promise<CodeBlob | null> {
  if (cache.has(path)) {
    return Promise.resolve(cache.get(path) ?? null);
  }
  return new Promise((resolve) => {
    const waiters = pending.get(path) ?? [];
    waiters.push(resolve);
    pending.set(path, waiters);
    if (waiters.length === 1) {
      post({ type: "fetchCode", path }); // only the first waiter triggers the round-trip
    }
  });
}

/** Feed host→webview code replies into the fetch cache. Returns true if it handled the msg. */
export function handleCodeMessage(msg: HostToWebview): boolean {
  if (msg.type !== "code" && msg.type !== "codeError") {
    return false;
  }
  const blob = msg.type === "code" ? { text: msg.text, lang: msg.lang } : null;
  cache.set(msg.path, blob);
  for (const resolve of pending.get(msg.path) ?? []) {
    resolve(blob);
  }
  pending.delete(msg.path);
  return true;
}
