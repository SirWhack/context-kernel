# Cloud Architecture Research — Context Kernel as a Hosted Product

**Date:** 2026-05-26
**Status:** Research complete. Decision pending.
**Context:** Evaluating whether Context Kernel can be productized as a hosted SaaS, and which cloud stack fits best.

## Product Concept

A GitHub App that, on every push, ingests the client's repository into a knowledge graph, then serves that graph to coding agents via a hosted MCP server (Streamable HTTP + OAuth 2.1). Tenants install the GitHub App, connect their repos, and get an MCP endpoint their agents can use immediately.

```
GitHub App (push webhook)
  → Queue (async processing)
    → LLM entity extraction (Summarizer)
    → Embedding generation (Embedder)
    → Graph store (entities, relationships, summaries, vectors)

Client's coding agent (Claude Code, Cursor, etc.)
  → MCP server (Streamable HTTP, per-tenant auth)
    → overview: read scope summaries
    → find: embedding-similarity search
```

## Expensive Services in the Current Local Pipeline

| Service | Local cost driver | Cloud translation |
|---|---|---|
| LLM entity extraction (Qwen3-30B-A3B) | ~50s/file on 7900 XTX GPU | Cloud LLM API or managed GPU inference |
| Embedding (Qwen3-Embedding-0.6B, 1024-dim) | ~22ms/embed, hundreds per ingest | Cloud embedding API |
| Graph storage (JSON + binary blobs) | Disk I/O, ~tens of MB per project | Managed DB + object storage |
| MCP serving (stdio, stateless) | Negligible | HTTP endpoint, always-on or scale-to-zero |

Entity extraction is 95%+ of compute cost. Everything else is cheap.

## Competitive Landscape

**Potpie AI** is the closest existing product:
- $2.2M pre-seed (Feb 2026), $1.1M revenue by mid-2025, 12 employees (India-based)
- Neo4j knowledge graph from AST parsing, served via FastAPI REST API
- Fortune 500 customers in healthcare/insurtech (40M+ line codebases)
- Open-source, self-hostable (Docker Compose + Neo4j + Postgres + Redis + Celery)
- **No MCP support**, no cross-project composition, purely structural (AST) not semantic

**Context Kernel differentiators:**
1. MCP-native serving (any agent that speaks MCP gets it automatically)
2. Cross-project semantic composition (the thesis)
3. LLM-extracted semantic relationships (not just AST structure) — 38% cross-scope density
4. Radically simpler infrastructure (no Neo4j/Postgres/Redis required)

**Broader category** (from Ry Walker's research): GitNexus (14K stars, knowledge graph + MCP), Greptile (YC-backed, code review SaaS), Sourcegraph Cody (enterprise RAG), Repomix (22K stars, context packing). Critical gap noted: "no tool has nailed incremental, real-time graph updates."

## Cloud Provider Comparison

### Cloudflare

**Architecture:** Workers + D1 + Vectorize + Queues + Workers AI + Durable Objects (McpAgent)

| Service | Role | Pricing | Notes |
|---|---|---|---|
| Workers ($5/mo base) | MCP server, webhook handler | $0.30/M requests after 10M included | 128MB memory, 15-min CPU (Queue consumer) |
| Workers AI | LLM + embeddings | Qwen3-30B: $0.051/$0.335/M tok in/out; Qwen3-Embed: $0.012/M | Exact local models available (FP8 quantization) |
| D1 | Graph state (entities, rels, summaries) | $0.001/M reads, $1.00/M writes, $0.75/GB | 10GB/db max, single-writer bottleneck |
| Vectorize | Embedding similarity search | $0.01/M queried dims, $0.05/100M stored dims | **CRITICAL: 5M stored dims per account = ~4,800 vectors at 1024-dim** |
| Queues | Webhook → processing pipeline | $0.40/M messages, 1M free | Natural backpressure for rate limiting |
| Durable Objects | Per-tenant MCP sessions | $0.15/M requests, WebSocket hibernation | 128MB memory, 10GB SQLite, hibernation = free when idle |
| R2 | Blob storage (materialized files) | $0.015/GB, zero egress | 10GB free tier |

**Estimated cost (100 tenants):** ~$13-15/month

**Strengths:**
- Has both Qwen3-30B-A3B (FP8) and Qwen3-Embedding-0.6B — the exact spike-validated models
- McpAgent with OAuth + WebSocket hibernation is purpose-built for multi-tenant MCP
- Cloudflare for SaaS: custom hostnames, SSL per tenant, Workers for Platforms
- Zero egress fees on R2
- Scale-to-zero on everything

**Critical concerns:**
- **Vectorize dimension cap is a dealbreaker.** 5M stored dimensions per account = ~4,800 vectors. A single 500-file repo would exceed this. This eliminates Vectorize for production use unless the cap is raised or you get an Enterprise agreement.
- **D1 single-writer architecture.** Only one write transaction globally per database. Slow writes bottleneck everything. >5K writes/sec is not possible.
- **128MB memory limit** on Workers/DOs — large graph states can't be loaded into memory.
- **Workers AI has no latency SLA.** Shared GPU infrastructure, 30-80 tok/s community reports vs 94 tok/s local. Rate limits require Enterprise negotiation for production scale.
- **D1 reliability concerns** — intermittent 500s under load reported through 2025, improving.
- **No committed-use discounts** — retail pricing at all scales.

**Verdict:** Cheapest and most integrated, but Vectorize's dimension cap is a hard blocker. Would need either an Enterprise deal or an external vector DB (negating the "all-Cloudflare" simplicity).

---

### GCP

**Architecture:** Cloud Run + Cloud SQL (pgvector) + Cloud Tasks + Gemini Flash + Firebase Auth

| Service | Role | Pricing | Notes |
|---|---|---|---|
| Cloud Run | MCP server, processing worker | $0.000024/vCPU-sec, scale-to-zero | 60-min timeout (services), 24-hr (jobs) |
| Cloud Run GPU (L4) | Optional: self-hosted inference | ~$0.67/GPU-hr, **scale-to-zero** | Unique: GPU scale-to-zero |
| Gemini 2.5 Flash-Lite | Entity extraction | $0.10/$0.40/M tok in/out | Cheapest major-provider LLM |
| text-embedding-004 | Embeddings | $0.10/M tokens (768 dim) | Or text-embedding-005 |
| Cloud SQL (pgvector) | Graph + vector storage | ~$10-25/mo (micro to small) | Familiar Postgres, **does not scale to zero** |
| Firestore | Alternative: serverless storage | $0.18/100K reads, native vector search | Scale-to-zero, but less mature vector support |
| Cloud Tasks | Webhook queue | 1M ops/mo free | Guaranteed delivery, rate limiting |
| Firebase Auth | OAuth per tenant | Free up to 50K MAU | Integrated with GCP IAM |

**Estimated cost (100 tenants):** ~$20-35/month (Gemini Flash), ~$30-90/month (Cloud Run GPU)

**Strengths:**
- **Cloud Run GPU scale-to-zero is unique.** Run Qwen3-30B on L4, pay only during ingestion. No other major cloud offers this.
- Official MCP-on-Cloud-Run support (GA, templates, docs)
- Gemini 2.5 Flash-Lite at $0.10/M input is extremely cheap
- pgvector on Cloud SQL — no vector dimension caps, familiar Postgres, no vendor lock-in on data
- Qwen3 available via Vertex AI Model Garden (self-hosted on GPU)

**Concerns:**
- Cloud SQL doesn't scale to zero (~$10/mo floor even with zero traffic)
- More services to wire together than Cloudflare
- Egress charges ($0.085-0.12/GB)
- Heavier IAM/networking configuration
- No Durable Objects equivalent for per-tenant stateful MCP sessions

**Verdict:** Strongest alternative to Cloudflare. GPU scale-to-zero is a genuine differentiator. Best choice if you want to self-host inference or if Cloudflare's limits prove binding. Slightly more expensive floor but more headroom.

---

### Azure

**Architecture:** Container Apps + Cosmos DB (DiskANN vectors) + Azure AI Foundry + Service Bus

| Service | Role | Pricing | Notes |
|---|---|---|---|
| Container Apps | MCP server, processing | $0.000024/vCPU-sec, scale-to-zero | GPU requires Dedicated plan (~$300+/mo, no scale-to-zero) |
| Azure AI Foundry | LLM inference | GPT-4o-mini: $0.15/$0.60/M; Qwen3 via Marketplace | Broad model catalog |
| Cosmos DB (Serverless) | Graph + vector (DiskANN) | $0.25/M RU, $0.25/GB | Integrated vector search eliminates separate vector DB |
| Service Bus | Webhook queue | $0.05/M operations | Guaranteed delivery, FIFO |
| Entra ID | Auth | Free tier covers basics | Enterprise SSO built-in |

**Estimated cost (100 tenants):** ~$8-34/month (without AI Search), ~$83-109/month (with AI Search)

**Strengths:**
- Cosmos DB with DiskANN vector search — one DB for graph + vectors + documents
- GitHub ownership — deep Actions/Apps integration, OIDC deployment
- Azure AI Foundry model breadth — Qwen3, Llama, Mistral, GPT, all as serverless endpoints
- Best compliance story (SOC2, HIPAA, FedRAMP) if targeting enterprise like Potpie does
- Container Apps supports scale-to-zero for CPU workloads

**Concerns:**
- GPU Container Apps requires Dedicated plan (~$300+/mo minimum, no scale-to-zero)
- More complex to wire together (5+ services)
- Egress charges ($0.087/GB)
- AI Search is expensive ($73/mo floor) — Cosmos DB DiskANN is the workaround
- Higher operational complexity than Cloudflare or GCP

**Verdict:** Best for enterprise/regulated customers. Cosmos DB + DiskANN is architecturally interesting (one service for everything). But GPU compute is expensive without scale-to-zero, and overall complexity is highest.

---

### Neo-Cloud Hybrids

**Best hybrid: Supabase ($25) + Modal (scale-to-zero GPU) + Cloudflare Workers ($5 MCP)**

| Layer | Service | Cost | Why |
|---|---|---|---|
| Database + auth + vectors | Supabase Pro | $25/mo | Postgres + pgvector + OAuth + RLS tenant isolation in one service |
| GPU inference | Modal (A10G) | ~$0 idle, $1.10/hr active | True scale-to-zero GPU, sub-second cold start, run any model |
| Job queue | Upstash QStash | ~$0 (free tier) | HTTP-based serverless queue, dispatches to Modal |
| MCP server | Cloudflare Workers + DOs | $5/mo | McpAgent with OAuth, WebSocket hibernation |
| **Total** | | **~$30-37/mo idle** | Plus ~$1.10/hr during ingestion |

**Notable neo-cloud findings:**
- **Modal** is the standout for GPU inference. True scale-to-zero, sub-second cold starts, run Qwen3-30B on A100-80GB ($2.50/hr) or 4-bit quantized on A10G ($1.10/hr).
- **Supabase** is the best all-in-one data layer. Postgres + pgvector + auth + RLS + edge functions for $25/mo.
- **Turso** is better than D1 for edge SQLite (multi-region, embedded replicas, no dimension cap issues), but no vector search.
- **Neon** ($5/mo) is the best pure serverless Postgres with pgvector and scale-to-zero. Database branching for testing.
- **Fly.io** is deprecating GPU machines after Aug 2026 — eliminated for inference.
- **Replicate** was acquired by Cloudflare (Nov 2025) — future uncertain, being absorbed into Workers AI.
- **Railway** has no GPU support and no scale-to-zero on paid plans.

**Verdict:** More assembly required, but the best option for model quality (your exact model), portability (minimal vendor lock-in), and flexibility. More expensive idle floor than all-Cloudflare, but no hard caps on vectors/writes.

---

## Summary Table

| | Cloudflare | GCP | Azure | Hybrid (Supabase+Modal+CF) |
|---|---|---|---|---|
| **Monthly (100 tenants)** | ~$13-15 | ~$20-35 | ~$8-34 | ~$30-37 + GPU time |
| **Your exact models** | Yes (FP8) | No (Gemini) | Qwen3 via Marketplace | Yes (any model on Modal) |
| **MCP hosting** | First-class | Official (Cloud Run) | DIY (Container Apps) | First-class (CF Workers) |
| **Vector search** | ~~Vectorize~~ **capped** | pgvector (no cap) | Cosmos DiskANN | pgvector (Supabase) |
| **GPU scale-to-zero** | N/A (managed) | Yes (Cloud Run L4) | No ($300+ floor) | Yes (Modal) |
| **Scale-to-zero (all)** | Yes | Mostly | Mostly | Yes |
| **Vendor lock-in** | High | Medium | Medium | Low |
| **Complexity** | Low | Medium | High | Medium |
| **Enterprise readiness** | Low-Medium | Medium | High | Low |

## Recommendation

**Start with Cloudflare for serving + external vector/inference, not all-Cloudflare.**

The Vectorize dimension cap kills the "pure Cloudflare" dream. The practical architecture is:

1. **Cloudflare Workers + Durable Objects** for MCP serving (McpAgent, OAuth, WebSocket hibernation) — this part is genuinely best-in-class
2. **Supabase or Neon** for Postgres + pgvector (graph state + vector search, no caps)
3. **Workers AI** for embedding at query time (cheap, fast, no caps for inference)
4. **Workers AI or Modal** for entity extraction (Workers AI if Qwen3-30B FP8 quality is acceptable; Modal if you need exact model match)
5. **Cloudflare Queues** for webhook processing pipeline

This gives you the best of Cloudflare's MCP/edge story without hitting the D1/Vectorize walls. Total cost ~$25-40/month for 100 tenants with healthy margins at $10/tenant.

**GCP is the strongest pure-cloud alternative** if you want one vendor for everything, especially with Cloud Run GPU scale-to-zero.

## Open Questions Before Building

1. **Does Qwen3-30B FP8 on Workers AI produce graphs comparable to your local Q4_K_M results?** Run the S0 spike methodology against Workers AI and measure cross-scope density.
2. **What's the Vectorize stored dimension limit under an Enterprise agreement?** If Cloudflare lifts it to 100M+, all-Cloudflare becomes viable again.
3. **Is Gemini Flash-Lite good enough for entity extraction?** If yes, GCP becomes the cheapest option ($0.10/M input tokens vs $0.051/M on Workers AI).
4. **What's the MCP client support landscape?** Streamable HTTP is the spec standard, but which agents actually support remote MCP servers with OAuth today?

## GitHub App + MCP Auth Integration

### The Pairing Model

The GitHub App and MCP server share a single identity chain. The user installs the GitHub App (granting read access to repos), then adds the MCP server to their coding agent. The MCP OAuth login delegates to GitHub OAuth ("Login with GitHub"), which maps the user to their installation(s) and scopes all MCP queries to those repos.

**One shared MCP endpoint** (`mcp.contextkernel.dev`) with auth-based routing — not per-tenant URLs.

### Identity Chain

```
GitHub App Install
  → installation_id = tenant_id
  → installation token (server-to-server, 1hr expiry, 5K req/hr)
  → used to read repo contents via GitHub API

MCP Connection (user-facing)
  → MCP client discovers OAuth at /.well-known/oauth-authorization-server
  → redirects to your /authorize → "Login with GitHub" (GitHub OAuth)
  → your server maps GitHub user → installation(s) → repos
  → issues MCP access token with claims: { installation_id, repos[], scope }
  → MCP client stores token, includes on all requests
  → token refreshes transparently via refresh_token
```

The MCP server is the OAuth authorization server. GitHub OAuth is the upstream identity provider. The MCP client never talks to GitHub directly.

### GitHub App Permissions (Read-Only)

| Permission | Level | Why |
|---|---|---|
| `contents` | `read` | Read repo files via Contents API |
| `metadata` | `read` | Required for all GitHub Apps (implicit) |

**Webhook subscriptions:** `push`, `installation`, `installation_repositories`

The app is entirely read-only. No write permissions required.

### Webhook → Ingestion Pipeline

**`push` event**: Payload includes `commits[].added`, `commits[].removed`, `commits[].modified` — the exact file diff. Enables incremental ingestion (only re-process changed files). GitHub retries failed deliveries 3 times over ~6 hours. Webhook endpoint must respond within 10 seconds (ack immediately, process async via queue).

**Reading files**: Use Contents API with installation token (`GET /repos/{owner}/{repo}/contents/{path}`). Max 1MB per file via Contents API; use Git Blobs API for files up to 100MB. Full tree listing in one call via `GET /repos/{owner}/{repo}/git/trees/{branch}?recursive=1`.

**Rate limits**: 5,000 API requests/hour per installation (15K for GitHub Enterprise Cloud). A 500-file repo needs ~501 calls (1 tree + 500 file reads) — well within limits.

**Webhook security**: Verify `X-Hub-Signature-256` header (HMAC-SHA256 of raw body with webhook secret).

### Lifecycle Events

| Event | Trigger | Action |
|---|---|---|
| `installation` (created) | User installs app | Create tenant, queue initial full ingest of selected repos |
| `push` | Code pushed to any branch | Queue incremental ingest (changed files only) |
| `installation_repositories` (added) | User adds repos to installation | Queue full ingest of new repos |
| `installation_repositories` (removed) | User removes repos | Delete repo data from tenant's graph |
| `installation` (deleted) | User uninstalls app | Delete all tenant data (graph, vectors, config) |

### User Experience

**Setup (one-time):**
1. User visits `github.com/apps/context-kernel/installations/new`
2. Selects org/account, chooses repos (all or selected)
3. App starts ingesting in the background
4. User adds MCP server to their coding agent:
   ```json
   {
     "mcpServers": {
       "context-kernel": {
         "type": "url",
         "url": "https://mcp.contextkernel.dev/sse"
       }
     }
   }
   ```
5. First MCP call triggers OAuth → browser opens → "Login with GitHub" → done
6. All subsequent calls authenticated automatically (token refresh is transparent)

**Ongoing:**
- Every `git push` triggers a webhook → incremental re-ingest → graph updated
- Agent queries (`overview`, `find`) return fresh results scoped to that user's repos
- User can add/remove repos from the GitHub App settings page — graph updates accordingly

### GitHub Marketplace Distribution

- **Fees**: 0% commission (GitHub eliminated the 25% cut in 2024)
- **Pricing models**: Per-unit (seats), flat-rate, or metered billing
- **Metered billing**: Charge based on repos processed, queries served, or storage used
- **Provides**: Billing, invoicing, license management, discovery
- **Free tier**: Can offer a free plan with limits (e.g., 1 repo, 100 queries/day)

### Cloudflare Implementation

On Cloudflare, the pairing uses:
- **`workers-oauth-provider`** package for the OAuth authorization server
- **`McpAgent`** Durable Object for per-tenant MCP sessions with WebSocket hibernation
- GitHub OAuth as the upstream identity provider (plug into the `authorize` handler)
- Token claims carry `installation_id` → route to tenant's D1 database / Vectorize namespace

### Cost of the GitHub App Layer

The GitHub App itself is free to create and operate. Costs are:
- Webhook receiving: handled by the same Workers/Queue infrastructure already priced above
- API calls (reading repo contents): free (GitHub doesn't charge for API use within rate limits)
- Marketplace listing: free (0% commission)

**The GitHub App adds zero marginal cost to the stack.**

## Sources

- [Cloudflare Workers AI Models](https://developers.cloudflare.com/workers-ai/models/)
- [Cloudflare Workers AI Pricing](https://developers.cloudflare.com/workers-ai/platform/pricing/)
- [Cloudflare Vectorize Limits](https://developers.cloudflare.com/vectorize/platform/limits/)
- [Cloudflare D1 Limits](https://developers.cloudflare.com/d1/platform/limits/)
- [Cloudflare Durable Objects](https://developers.cloudflare.com/durable-objects/platform/pricing/)
- [Cloudflare Containers (GA)](https://developers.cloudflare.com/containers/pricing/)
- [Cloudflare McpAgent](https://developers.cloudflare.com/agents/guides/remote-mcp-server/)
- [GCP Cloud Run Pricing](https://cloud.google.com/run/pricing)
- [GCP Cloud Run GPU](https://docs.google.com/run/docs/configuring/services/gpu)
- [Vertex AI / Gemini Pricing](https://cloud.google.com/vertex-ai/generative-ai/pricing)
- [Host MCP on Cloud Run](https://docs.cloud.google.com/run/docs/host-mcp-servers)
- [Azure Container Apps Pricing](https://azure.microsoft.com/en-us/pricing/details/container-apps/)
- [Azure Cosmos DB DiskANN Vector Search](https://learn.microsoft.com/en-us/azure/cosmos-db/vector-database)
- [Azure AI Foundry](https://azure.microsoft.com/en-us/pricing/details/azure-openai/)
- [Modal Pricing](https://modal.com/pricing)
- [Supabase Pricing](https://supabase.com/pricing)
- [Neon Pricing](https://neon.com/pricing)
- [Turso Pricing](https://turso.tech/pricing)
- [Upstash Pricing](https://upstash.com/pricing)
- [Potpie AI](https://potpie.ai/)
- [Potpie raises $2.2M](https://techfundingnews.com/the-startup-building-a-knowledge-graph-for-code-raises-2-2m-to-make-ai-agents-actually-useful/)
- [Code Intelligence Tools Compared](https://rywalker.com/research/code-intelligence-tools)
