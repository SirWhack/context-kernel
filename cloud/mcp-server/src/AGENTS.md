<!-- context-kernel-freshness
graph: ce4c30de6021574f8be593ca3ef2c62ccfde5e39118e774477c1d6d76f0f9abe
source-tree: 8d2e63fba4a4af486adc37f89a0fff7925dcfeb7ea86e78eccdbea9196a361ce
materialized: 2026-06-01T01:08:19Z
-->

This scope implements the Cloudflare Workers MCP server that exposes the Context Kernel’s summarization and retrieval capabilities as a Model Context Protocol service. The server acts as the bridge between AI agents (like Claude) and the project’s persistent storage, allowing agents to read, write, and search summaries stored in Cloudflare KV and Neon PostgreSQL. It handles authentication, webhook processing from GitHub, and token-aware text truncation to stay within model context limits.

The primary public interface is the `ContextKernelMCP` class, which extends `McpAgent` from the `agents/mcp` library. It exposes a single public method `init()` that configures the underlying `McpServer` instance with tools and resources. The class reads its configuration from the `Env` interface, which defines bindings for `MCP_OBJECT` (DurableObjectNamespace), `SUMMARIES` (KVNamespace), `AI` (Workers AI binding), `AUTH_TOKEN`, `NEON_DATABASE_URL`, `GITHUB_WEBHOOK_SECRET`, `MODAL_ENDPOINT`, and `MODAL_TRIGGER_TOKEN`. This interface pattern keeps environment configuration explicit and type-safe.

Internally, the module provides three private helper functions. `truncateAtParagraph(text, budget)` performs intelligent text truncation at paragraph boundaries to respect token budgets. `verifyGitHubSignature(request, secret)` validates incoming webhook payloads using HMAC-SHA256. `handleWebhook(request, env, ctx)` processes GitHub webhook events, likely triggering summary updates or re-indexing. The module also defines a private constant `CHARS_PER_TOKEN` for estimating token counts from character lengths.

The scope depends on several external packages: `@modelcontextprotocol/sdk/server/mcp.js` for the MCP server implementation, `@neondatabase/serverless` for PostgreSQL connectivity, `zod` for schema validation, and Cloudflare’s runtime APIs (Durable Objects, KV, Workers AI). The design follows the MCP agent pattern, where `ContextKernelMCP` hides the complexity of managing multiple storage backends and webhook processing behind a clean server interface that AI agents can interact with through standard MCP tool/resource calls.
