import { McpAgent } from "agents/mcp";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { neon } from "@neondatabase/serverless";
import { z } from "zod";

interface Env {
	MCP_OBJECT: DurableObjectNamespace;
	SUMMARIES: KVNamespace;
	AI: Ai;
	AUTH_TOKEN: string;
	NEON_DATABASE_URL: string;
	GITHUB_WEBHOOK_SECRET: string;
	MODAL_ENDPOINT: string;
	MODAL_TRIGGER_TOKEN: string;
}

const CHARS_PER_TOKEN = 4;

function truncateAtParagraph(text: string, budget: number): string {
	if (text.length <= budget) return text;
	const cut = text.slice(0, budget);
	const para = cut.lastIndexOf("\n\n");
	if (para > budget / 2) return cut.slice(0, para);
	return cut;
}

export class ContextKernelMCP extends McpAgent<Env, {}, {}> {
	server = new McpServer({
		name: "context-kernel",
		version: "1.0.0",
	});

	async init() {
		this.server.registerTool(
			"overview",
			{
				description:
					"Get orientation summary for a specific scope (directory). Use scopes like 'model-time' or 'model-time/context_kernel'.",
				inputSchema: {
					scope: z.string().describe("Scope path, e.g. 'model-time' or 'evergreenlabs/src'"),
					max_tokens: z.number().default(4096).describe("Token budget for the response"),
				},
			},
			async ({ scope, max_tokens }) => {
				const text = await this.env.SUMMARIES.get(`scope:${scope}`);
				if (!text) {
					const index = await this.env.SUMMARIES.get("scopes:index");
					const available = index ? JSON.parse(index).join(", ") : "none";
					return {
						content: [
							{
								type: "text" as const,
								text: `No materialized overview for scope "${scope}". Available scopes: ${available}`,
							},
						],
					};
				}
				const budget = max_tokens * CHARS_PER_TOKEN;
				return {
					content: [{ type: "text" as const, text: truncateAtParagraph(text, budget) }],
				};
			},
		);

		this.server.registerTool(
			"find",
			{
				description:
					"Search for relevant code, modules, and documentation across the portfolio by semantic similarity.",
				inputSchema: {
					query: z.string().describe("Natural language search query"),
					scope: z.string().optional().describe("Optional scope to filter results"),
					max_tokens: z.number().default(4096).describe("Token budget for the response"),
				},
			},
			async ({ query, scope, max_tokens }) => {
				const embedding = await this.env.AI.run("@cf/qwen/qwen3-embedding-0.6b", {
					text: [query],
				});
				const queryVector = embedding.data[0];
				const vectorStr = `[${queryVector.join(",")}]`;

				const sql = neon(this.env.NEON_DATABASE_URL);
				const rows = scope
					? await sql`
						SELECT chunk_text, source_path
						FROM chunks
						WHERE scope = ${scope}
						ORDER BY embedding <=> ${vectorStr}::vector
						LIMIT 10`
					: await sql`
						SELECT chunk_text, source_path
						FROM chunks
						ORDER BY embedding <=> ${vectorStr}::vector
						LIMIT 10`;

				if (!rows.length) {
					const scopeMsg = scope ? ` in scope "${scope}"` : "";
					return {
						content: [
							{
								type: "text" as const,
								text: `No results found for query: "${query}"${scopeMsg}.`,
							},
						],
					};
				}

				const budget = max_tokens * CHARS_PER_TOKEN;
				let assembled = "";
				for (const row of rows) {
					const entry = `${row.chunk_text}\n\n> Source: \`${row.source_path}\`\n`;
					if (assembled.length + entry.length > budget && assembled.length > 0) break;
					assembled += entry + "\n";
				}

				return {
					content: [{ type: "text" as const, text: truncateAtParagraph(assembled, budget) }],
				};
			},
		);
	}
}

async function verifyGitHubSignature(request: Request, secret: string): Promise<boolean> {
	const signature = request.headers.get("x-hub-signature-256");
	if (!signature) return false;
	const body = await request.clone().arrayBuffer();
	const key = await crypto.subtle.importKey(
		"raw",
		new TextEncoder().encode(secret),
		{ name: "HMAC", hash: "SHA-256" },
		false,
		["sign"],
	);
	const sig = await crypto.subtle.sign("HMAC", key, body);
	const expected = "sha256=" + [...new Uint8Array(sig)].map((b) => b.toString(16).padStart(2, "0")).join("");
	return signature === expected;
}

async function handleWebhook(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
	if (request.method !== "POST") {
		return new Response("Method not allowed", { status: 405 });
	}

	if (!(await verifyGitHubSignature(request, env.GITHUB_WEBHOOK_SECRET))) {
		return new Response("Invalid signature", { status: 401 });
	}

	const event = request.headers.get("x-github-event");
	if (event !== "push") {
		return new Response(JSON.stringify({ skipped: true, event }), {
			headers: { "Content-Type": "application/json" },
		});
	}

	const payload = (await request.json()) as Record<string, unknown>;
	const repo = (payload.repository as Record<string, unknown>)?.full_name ?? "unknown";

	ctx.waitUntil(
		fetch(env.MODAL_ENDPOINT, {
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify({ token: env.MODAL_TRIGGER_TOKEN, repo }),
		}).then((r) => {
			if (!r.ok) console.error(`Modal trigger failed: ${r.status}`);
			else console.log(`Modal pipeline triggered for ${repo}`);
		}),
	);

	return new Response(JSON.stringify({ ok: true, repo, queued: true }), {
		headers: { "Content-Type": "application/json" },
	});
}

export default {
	fetch(request: Request, env: Env, ctx: ExecutionContext) {
		const url = new URL(request.url);

		if (url.pathname === "/mcp" || url.pathname.startsWith("/mcp/")) {
			const auth = request.headers.get("Authorization");
			if (auth !== `Bearer ${env.AUTH_TOKEN}`) {
				return new Response("Unauthorized", { status: 401 });
			}
			return ContextKernelMCP.serve("/mcp").fetch(request, env, ctx);
		}

		if (url.pathname === "/webhook") {
			return handleWebhook(request, env, ctx);
		}

		if (url.pathname === "/health") {
			return new Response("ok");
		}

		return new Response("Not found", { status: 404 });
	},
};
