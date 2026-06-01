// Builds two bundles: the extension host (Node/CJS) and the webview (a React + React Flow
// app, browser/IIFE so it loads as a single CSP-friendly nonce'd script). Imported CSS
// (React Flow base styles + the Highlight.js theme) is emitted alongside as media/main.css.
const esbuild = require("esbuild");

const watch = process.argv.includes("--watch");
const common = { bundle: true, sourcemap: true, logLevel: "info" };

async function main() {
  const host = await esbuild.context({
    ...common,
    entryPoints: ["src/extension.ts"],
    outfile: "out/extension.js",
    platform: "node",
    format: "cjs",
    external: ["vscode"],
  });
  const webview = await esbuild.context({
    ...common,
    entryPoints: ["src/webview/index.tsx"],
    outfile: "media/main.js",
    platform: "browser",
    format: "iife",
    jsx: "automatic",
    // React reads process.env.NODE_ENV; there is no process in the webview, so inline it.
    define: { "process.env.NODE_ENV": '"production"' },
    loader: { ".ttf": "dataurl" },
  });

  if (watch) {
    await host.watch();
    await webview.watch();
  } else {
    await host.rebuild();
    await webview.rebuild();
    await host.dispose();
    await webview.dispose();
  }
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
