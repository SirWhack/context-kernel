<!-- context-kernel-freshness
graph: ce4c30de6021574f8be593ca3ef2c62ccfde5e39118e774477c1d6d76f0f9abe
source-tree: e49b0af25f2cab8eb80de8fc1c629efa9666af766ef201c87aa8eab75fa33497
materialized: 2026-06-01T01:08:19Z
-->

This scope handles the Cloudflare-deployed infrastructure for the Context Kernel MCP server, providing the synchronization and storage layer that bridges local development state with cloud services. It is responsible for two core operations: archiving and transferring the entire `.context-kernel` directory to Cloudflare R2 as a compressed tar.gz object, and selectively syncing graph data (chunk embeddings and scope summaries) to Cloudflare KV and a Neon Postgres database with pgvector. The scope is designed to minimize API round-trips by treating the pipeline state as a single R2 object, while keeping derived artifacts like embeddings and summaries as regenerable.

The public API surface consists of two main modules. `r2_sync.py` exposes `upload()` and `download()` functions that take a local directory path, Cloudflare account ID, bucket name, and API token. The `upload()` function creates a tar.gz archive from the `cache/`, `graph/`, and `config.toml` directories, then PUTs it to R2 at a fixed key (`R2_OBJECT_KEY`). The `download()` function performs the inverse, optionally rewriting portfolio root paths via the `portfolio_root` parameter. `sync.py` provides `upload_kv()` and `upload_vectors()`: the former writes scope summaries (keyed as `scope:<path>`) to a Cloudflare KV namespace, and the latter reads 1024-dim float32 embeddings from `.bin` files and inserts them into a Neon pgvector table alongside chunk metadata. Both modules expose a `main()` CLI entry point.

Internally, the scope relies on a set of TypeScript interface definitions in `worker-configuration.d.ts` that describe the Cloudflare Workers runtime bindings. The `__BaseEnv_Env` interface declares the actual bindings used at runtime: `SUMMARIES` as a `KVNamespace`, `VECTORS` as a `VectorizeIndex`, `AI` as the Workers AI binding, and `MCP_OBJECT` as a `DurableObjectNamespace` pointing to the `ContextKernelMCP` handler. Supporting interfaces like `ArtifactsRepoInfo` and `JsonWebKey` provide type definitions for the broader Cloudflare ecosystem but are not directly consumed by the sync logic.

The scope depends on the `requests` library for HTTP calls to the Cloudflare API and Neon Postgres, and on standard library modules (`argparse`, `tarfile`, `json`, `struct`, `pathlib`) for CLI parsing, archive creation, and binary data handling. It reads environment variables (`CF_API_TOKEN`, `CF_ACCOUNT_ID`, `KV_NAMESPACE_ID`, `DATABASE_URL`) for authentication and configuration. The sync module also reads from the local filesystem, specifically `.context-kernel/graph/state.json` for chunk metadata and `<portfolio>/<scope>/AGENTS.md` for materialized overviews, following a convention where each scope directory contains its own AGENTS.md file.

## Recommended documentation

This scope has 397 code entities across 1 files but no reference documentation. To create one: `/init-reference mcp-server`

