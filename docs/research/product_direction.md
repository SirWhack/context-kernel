# Product Direction Research — Context Kernel as a Hosted Product

**Date:** 2026-05-26
**Status:** Research and analysis complete. No decisions made — captured for future reference.
**Companion doc:** [cloud_architecture.md](./cloud_architecture.md) (cloud provider pricing, GitHub App mechanics, MCP auth)

## The Idea

A GitHub App that watches every commit, updates a durable repo graph, and exposes that graph through an MCP server so coding agents (Claude Code, Cursor, etc.) can ask theory-aware questions about the codebase:

- "What architectural theory did this commit violate?"
- "What ADRs constrain this module?"
- "Which invariants are affected by this change?"
- "What context should an agent read before touching this area?"

## Why Generic "Code Graph + MCP" Is Not Enough

The generic version of this product — index code into a graph, expose via MCP — is already crowded:

| Competitor | What they do | Status |
|---|---|---|
| **Potpie AI** | Neo4j knowledge graph from AST, served via REST API | $1.1M revenue, $2.2M pre-seed, Fortune 500 customers |
| **CodeGraphContext** | MCP server + CLI that indexes local code into a graph DB | Open source, 2K+ stars |
| **Sourcegraph Cody** | Cross-repo code intelligence via MCP (search, nav, history) | Enterprise, well-funded |
| **GitNexus** | Knowledge graph + MCP, zero-server (local + WASM) | Open source, 14K stars |
| **Greptile** | Full-codebase analysis, dependency graph, AI code review | YC-backed SaaS |
| **GitHub Copilot** | Code review, bug detection, PR suggestions | GA April 2025, platform incumbent |
| **CodeRabbit** | AI PR review, planning, Jira integration | Growing SaaS |

A product that says "we index your code and let you search it" is fighting Sourcegraph with 1/1000th the resources. The graph alone commoditizes fast.

## The Differentiator: Theory Preservation, Not Code Search

Most tools answer: **"Where is the code?"**
This product should answer: **"What does this codebase believe, and did this change preserve that theory?"**

This maps directly to the Naur/Ousterhout/Parnas/ADR direction already embedded in Context Kernel. The business-grade version maintains a living model of:

- System purpose (thesis)
- Module responsibilities and contracts
- Interface boundaries (Ousterhout depth, Parnas secrets)
- Design decisions (ADRs) and their constraints
- Invariants and non-goals
- Terminology / ubiquitous language
- "Why this exists" context
- Drift between implementation and documented theory

This is more interesting than code search because it targets a real failure mode: **agents can write plausible code while violating project intent.** No existing tool detects this.

## The Sharper Positioning

Avoid: "Knowledge graph for your repo."
Say: **"Architecture memory for AI-coded repositories."**

Or: "A GitHub App that keeps your project theory synchronized with every commit and exposes it to coding agents over MCP."

## Product Shape

### Core Loop

1. GitHub App installed on a repo
2. On merge or push, incrementally update the repo's theory graph
3. Extract: symbols, modules, imports, call edges, docs, ADR references, semantic entities from THEORY.md, ARCHITECTURE.md, ADRs, READMEs, and code
4. On PR, comment **only** when theory drift is detected — undocumented architectural changes, affected ADRs, invariant violations
5. MCP server exposes theory-aware tools

### MCP Tool Surface (Beyond current overview/find)

| Tool | What it does |
|---|---|
| `get_relevant_theory(path_or_symbol)` | Return the theory context (invariants, ADRs, contracts) relevant to a file or symbol |
| `explain_module_contract(module)` | Describe a module's interface, Parnas secret, depth, and upstream requirements |
| `find_affected_adrs(diff)` | Given a code diff, identify which ADRs constrain the changed areas |
| `check_architecture_drift(diff)` | Detect whether a diff violates documented invariants, non-goals, or module boundaries |
| `get_agent_context(task)` | Given a task description, return what an agent should read before starting |
| `trace_concept(concept_name)` | Follow a glossary term through the codebase — where it's defined, used, and constrained |
| `summarize_repo_theory()` | Return the thesis, key invariants, and current architectural shape |

The proactive MCP tools (called *before* the agent writes code) are higher-value than the reactive PR check (called *after* the damage is done). The highest-value intervention is upstream: agent reads the theory, respects it, never writes the drifting code in the first place.

### PR Check Value

When the PR check does fire, it should say things like:

> This commit modifies `BillingPolicy`, but the graph shows `BillingPolicy` is constrained by ADR-004 and owned by the Pricing bounded context. The change introduces a dependency on `CustomerSupport`, which violates the documented direction of dependency flow.

This is much more defensible than "here are possible bugs." It's the kind of feedback that only comes from someone who deeply understands the project.

### Sparse, High-Signal Comments

The PR check must be sparse. If it behaves like another lint bot, developers will disable it. It has to be capable of saying "no architectural issues found" and staying silent. Only comment when there's genuine theory drift.

## Build Sequence

1. **Open-source local CLI + MCP server** — Prove the graph is useful with Claude Code on your own repos. This is v1 (current build).
2. **GitHub Action** — Run on PRs, output "architecture/theory drift" comments. Low barrier to adoption (no app install, just a workflow file).
3. **GitHub App** — Hosted incremental graph, repo history, branch-aware graph snapshots. Webhook-triggered ingestion.
4. **Team SaaS** — Permissions, org-wide graph, multi-repo architecture memory, agent access tokens, audit trail.

This sequence earns credibility before asking for payment.

## Who Pays First

Not giant enterprises (they move slowly, already look at Sourcegraph). The early wedge:

- Small AI-heavy dev shops (5-20 engineers using Claude Code/Cursor daily)
- Solo consultants managing multiple client codebases
- Agencies using agentic coding workflows heavily
- Open-source maintainers overwhelmed by AI-generated PRs
- Teams with strong ADR/documentation culture
- Compliance-adjacent engineering teams where "why did this change happen?" matters

## Pricing Intuition

Not a mass-market $10/month developer tool at first:

| Tier | Price | What |
|---|---|---|
| Free (open-source) | $0 | Local CLI + MCP server, unlimited repos |
| Free hosted | $0 | 1 private repo, public repos unlimited |
| Pro | $10/month/repo | Hosted graph, PR checks, MCP endpoint, incremental updates |
| Team | $10-25/user/month | Org-wide graph, multi-repo memory, access controls, audit trail |
| Consulting | Custom | Onboarding, theory formation workshops, architecture review |

GitHub Marketplace distribution (5% commission). Metered billing not natively supported for third-party apps on Marketplace — would need flat-rate or per-unit (seats) pricing model.

## Biggest Risks

### 1. Platform Capture
GitHub Copilot, Sourcegraph, Cursor, and Claude Code can all improve repo context. GitHub is expanding AI agent orchestration inside GitHub itself. However, none of them are building theory-aware architecture review — they're focused on generic code intelligence. The theory layer is defensible because it requires opinionated product design, not just better search.

### 2. Cold-Start Quality
Most repos don't have THEORY.md or well-structured ADRs. The product either needs to:
- Generate a draft theory (but this violates the hand-write rule for good reason — the struggle to compress IS the theory formation)
- Work degraded without one (index what exists: READMEs, comments, module structure, implicit patterns)
- Make theory formation part of the product (the `/grill-theory` skill IS onboarding)

This is the hardest product problem. The `/grill-theory` workflow — relentlessly questioning until the thesis is sharp and falsifiable — might be the onboarding experience itself.

### 3. MCP Security
Git/MCP integrations have had serious security scrutiny. Reported vulnerabilities in Anthropic's Git MCP server involved path validation bypass and argument injection. A hosted product needs a serious sandboxing story: the MCP server is read-only, the GitHub App has read-only permissions, the graph is derived (never authoritative), tenant isolation is enforced at every layer.

### 4. Noisy PR Comments
If it behaves like another lint bot, devs disable it. Must be sparse and high-signal. Default to silence; comment only on genuine theory drift. The bar is: "would a senior engineer who knows this project deeply flag this?"

## Graph Schema Implications

Theory preservation requires first-class graph entities beyond code symbols:

| Entity kind | Source | Example |
|---|---|---|
| `thesis` | THEORY.md | "Context at one altitude doesn't compose into context at another" |
| `invariant` | THEORY.md | "The graph is the source of truth" |
| `non_goal` | THEORY.md | "No cross-project entity merging in v1" |
| `adr` | docs/adr/*.md | ADR-0010: pre-commit hook regeneration |
| `open_question` | THEORY.md | "Does cross-project insight require entity merging?" |
| `module_contract` | ARCHITECTURE.md | Materializer: owns rendering policy, does not own edit survival |
| `glossary_term` | CONTEXT.md | "Scope: unit a single materialized file covers" |
| `module` | Code (AST) | `context_kernel.ingester` |
| `class` | Code (AST) | `LightRAGStore` |
| `function` | Code (AST) | `ingest()` |
| `relationship` | Extracted | `Ingester --writes--> Graph` |

The current v1 graph captures the bottom four. The product version needs the top seven too. This is where the graph becomes more valuable than "AI code search."

## Cloud Architecture Summary

See [cloud_architecture.md](./cloud_architecture.md) for full pricing details. The headline:

| Stack | Monthly cost (100 tenants) | Key advantage |
|---|---|---|
| Cloudflare Workers + external DB | ~$25-40 | Best MCP hosting (McpAgent + OAuth), cheapest serving |
| GCP Cloud Run + Cloud SQL | ~$20-35 | GPU scale-to-zero, official MCP support, Gemini Flash is dirt cheap |
| Azure Container Apps + Cosmos DB | ~$8-34 | Best compliance story, Cosmos DiskANN eliminates separate vector DB |
| Supabase + Modal + CF Workers | ~$30-37 | Most flexible, least lock-in, run exact models |

The cloud choice is less critical than the graph quality and tool design. Start wherever is cheapest and iterate. The value is in the theory graph, not the infrastructure.

## The Eval Question

The MVP test for this product direction: take a repo with THEORY.md, wire the theory graph + MCP, then measure whether agents make fewer architectural mistakes when the graph is available vs. not.

If agents measurably avoid invariant violations, respect ADR constraints, and stay within documented module boundaries when they have theory context, the product story writes itself. If they don't, the graph isn't valuable enough regardless of how it's hosted.

This is testable with the current v1 demo (S10). An eval methodology would:
1. Define a set of tasks that *could* violate documented invariants (e.g., "add a feature that writes to a materialized file directly")
2. Run the agent with and without the theory graph available
3. Measure: did the agent check THEORY.md? Did it respect invariant 1? Did it flag the conflict?
4. The delta between with-graph and without-graph is the product's value proposition, quantified.

## What This Means for v1

Nothing changes in the current build. v1 (S10 demo) proves the graph works end-to-end on a real portfolio. The product direction described here is post-v1 — it's what happens after the local version is proven and dogfooded.

The key decisions deferred:
- Whether to build the GitHub Action (step 2) or jump straight to GitHub App (step 3)
- Whether the hosted version runs on Cloudflare, GCP, or a hybrid
- Whether to pursue the theory-drift PR check or focus purely on MCP context delivery
- Pricing model and go-to-market

All of these depend on dogfooding results from v1.
