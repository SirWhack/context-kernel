# Kernel-vs-grep eval prompts — MANUAL / agent runs

Paste each block into a **fresh-context** agent. Two arms per repo.

**Setup (one time):** the kernel arm needs this repo's project MCP servers loaded —
`ck-sudoku` and `ck-locate` (defined in `.mcp.json`, each a local `ck mcp` over that repo's
graph). **Restart Claude Code** so `.mcp.json` loads, and approve the two servers when
prompted. Keep the embedder up on :8081 (the `find` tool needs it). The kernel prompts below
name the exact `mcp__ck-<repo>__*` tools and forbid the cloud `mcp__context-kernel__*`.


---

# Repo: `vibe-coded/sudoku`  (server `ck-sudoku`, 6 questions)

## Arm: kernel  (tools: `mcp__ck-sudoku__find`, `mcp__ck-sudoku__overview`, `Read`)

```text
Arm A. You are orienting in an unfamiliar codebase using ONLY the Context Kernel MCP tools from the **ck-sudoku** server — `mcp__ck-sudoku__find` (semantic search over the repo's knowledge graph) and `mcp__ck-sudoku__overview` (a scope/directory orientation summary) — plus `Read`. Do NOT use `mcp__context-kernel__*` (that is the cloud PORTFOLIO graph and will give the wrong repo). Do NOT grep, glob, or browse the filesystem: locate everything through `mcp__ck-sudoku__*`, then `Read` the exact files it cites to confirm.

Target repository (all file paths relative to here): /home/swynn/Code/model-time/test-repos/vibe-coded/sudoku

Answer the 6 questions below. For EACH question, write a markdown header `## Q{i}` with its number, give a concise answer, and end that question with a line `Files:` followed by every source file path that answers it — one per line, in backticks, relative to the repo root.

CRITICAL: list a file ONLY if you actually OPENED it this session (read its contents via your allowed tools). Do NOT list files from prior knowledge or memory of this or any public project — if you did not open it in this session, do not cite it.

## Q1
How does the API authenticate incoming requests? Trace where the bearer token is read off the request, where the Cognito JWT is verified, and how user identity / admin status is exposed to GraphQL resolvers. Name the exact source files and key functions.

## Q2
Where is a new sudoku puzzle generated and where is a solution/cell correctness validated? Name the exact source files and key functions (generation, backtracking solver, uniqueness check) and explain the algorithm at a high level.

## Q3
What is the API's data model and persistence layer? Which database is used, what entities/tables exist, and where are the create/get/update/delete operations and serialization defined?

## Q4
How does the React web frontend manage and render game state (current game, board, selected number, notes mode)? Where does it fetch the game and where is per-cell interaction state held?

## Q5
Where is the server/API wired up: the ASGI app entrypoint, route definitions, the Lambda handlers, and how the GraphQL schema is assembled from resolvers? Name the exact source files.

## Q6
What does Terraform provision and how is the app deployed? Identify the compute for the API, the frontend hosting/CDN, and the CI pipeline that builds and ships both api and web.
```

## Arm: grep  (tools: `Grep`, `Glob`, `Read`, `Bash`)

```text
Arm B. You are orienting in an unfamiliar codebase to establish a baseline, using ONLY grep/ripgrep, glob, and file reads over the raw repository — no Context Kernel, no MCP tools. Any `AGENTS.md` or `CLAUDE.md` files in the tree are generated artifacts, not part of the project — ignore them and work from the real source.

Target repository (all file paths relative to here): /home/swynn/Code/model-time/test-repos/vibe-coded/sudoku

Answer the 6 questions below. For EACH question, write a markdown header `## Q{i}` with its number, give a concise answer, and end that question with a line `Files:` followed by every source file path that answers it — one per line, in backticks, relative to the repo root.

CRITICAL: list a file ONLY if you actually OPENED it this session (read its contents via your allowed tools). Do NOT list files from prior knowledge or memory of this or any public project — if you did not open it in this session, do not cite it.

## Q1
How does the API authenticate incoming requests? Trace where the bearer token is read off the request, where the Cognito JWT is verified, and how user identity / admin status is exposed to GraphQL resolvers. Name the exact source files and key functions.

## Q2
Where is a new sudoku puzzle generated and where is a solution/cell correctness validated? Name the exact source files and key functions (generation, backtracking solver, uniqueness check) and explain the algorithm at a high level.

## Q3
What is the API's data model and persistence layer? Which database is used, what entities/tables exist, and where are the create/get/update/delete operations and serialization defined?

## Q4
How does the React web frontend manage and render game state (current game, board, selected number, notes mode)? Where does it fetch the game and where is per-cell interaction state held?

## Q5
Where is the server/API wired up: the ASGI app entrypoint, route definitions, the Lambda handlers, and how the GraphQL schema is assembled from resolvers? Name the exact source files.

## Q6
What does Terraform provision and how is the app deployed? Identify the compute for the API, the frontend hosting/CDN, and the CI pipeline that builds and ships both api and web.
```


---

# Repo: `vibe-coded/locate_anything_setup`  (server `ck-locate`, 6 questions)

## Arm: kernel  (tools: `mcp__ck-locate__find`, `mcp__ck-locate__overview`, `Read`)

```text
Arm A. You are orienting in an unfamiliar codebase using ONLY the Context Kernel MCP tools from the **ck-locate** server — `mcp__ck-locate__find` (semantic search over the repo's knowledge graph) and `mcp__ck-locate__overview` (a scope/directory orientation summary) — plus `Read`. Do NOT use `mcp__context-kernel__*` (that is the cloud PORTFOLIO graph and will give the wrong repo). Do NOT grep, glob, or browse the filesystem: locate everything through `mcp__ck-locate__*`, then `Read` the exact files it cites to confirm.

Target repository (all file paths relative to here): /home/swynn/Code/model-time/test-repos/vibe-coded/locate_anything_setup

Answer the 6 questions below. For EACH question, write a markdown header `## Q{i}` with its number, give a concise answer, and end that question with a line `Files:` followed by every source file path that answers it — one per line, in backticks, relative to the repo root.

CRITICAL: list a file ONLY if you actually OPENED it this session (read its contents via your allowed tools). Do NOT list files from prior knowledge or memory of this or any public project — if you did not open it in this session, do not cite it.

## Q1
This server's core domain is spatial object localization: the model emits answers like <box><x1><y1><x2><y2></box> and <ref>label</ref> tags in a normalized [0,1000] coordinate space. Where is the raw model text parsed into structured detections and points, what are the core domain data types (bounding box / point), and how are normalized [0,1000] coords converted to source-image pixels? Name the exact files and key functions.

## Q2
The model only accepts seven canonical trained prompt templates (closed-class detection, phrase grounding single/multi, text grounding, scene-text detection, GUI box, pointing). Where is the single source of truth for these templates, and where/how are client-submitted prompts strictly validated against them at the network edge? Name the exact files and how drift between the two is prevented.

## Q3
How does the app compute the pixel-to-token geometry for an input image — the ViT patch size, the 2x2 patch merger to LLM tokens, the 25,600-patch budget, the resize/pad plan, and the minimum resolvable object size? Name the source file(s) that implement this math and the function that produces the resize plan used per inference.

## Q4
Trace how an inference request flows from client to model: which HTTP/WebSocket routes exist, how the binary frame (length-prefixed JSON header + JPEG) is parsed and validated, and how the Rust frontend forwards each frame to the Python worker over the Unix domain socket. Name the exact source files and key functions/handlers.

## Q5
How is the LocateAnything-3B model actually loaded and run for inference on the Python side? Cover the asyncio Unix-socket worker entrypoint that serializes GPU access behind a lock, and the inference adapter that loads the model (attn-implementation override, SDPA mem-efficient patches, bf16) and runs .generate(). Name the exact files and key classes/functions.

## Q6
Where do the runtime configuration knobs and pinned versions live, and how are they wired into the two processes at container start? Cover the single source of truth for pinned versions and input caps (LA_MAX_IMAGE_DIM, LA_MAX_JPEG_BYTES, ports), how the entrypoint launches the worker and frontend, and how the Rust binary parses its CLI/env args. Name the exact files.
```

## Arm: grep  (tools: `Grep`, `Glob`, `Read`, `Bash`)

```text
Arm B. You are orienting in an unfamiliar codebase to establish a baseline, using ONLY grep/ripgrep, glob, and file reads over the raw repository — no Context Kernel, no MCP tools. Any `AGENTS.md` or `CLAUDE.md` files in the tree are generated artifacts, not part of the project — ignore them and work from the real source.

Target repository (all file paths relative to here): /home/swynn/Code/model-time/test-repos/vibe-coded/locate_anything_setup

Answer the 6 questions below. For EACH question, write a markdown header `## Q{i}` with its number, give a concise answer, and end that question with a line `Files:` followed by every source file path that answers it — one per line, in backticks, relative to the repo root.

CRITICAL: list a file ONLY if you actually OPENED it this session (read its contents via your allowed tools). Do NOT list files from prior knowledge or memory of this or any public project — if you did not open it in this session, do not cite it.

## Q1
This server's core domain is spatial object localization: the model emits answers like <box><x1><y1><x2><y2></box> and <ref>label</ref> tags in a normalized [0,1000] coordinate space. Where is the raw model text parsed into structured detections and points, what are the core domain data types (bounding box / point), and how are normalized [0,1000] coords converted to source-image pixels? Name the exact files and key functions.

## Q2
The model only accepts seven canonical trained prompt templates (closed-class detection, phrase grounding single/multi, text grounding, scene-text detection, GUI box, pointing). Where is the single source of truth for these templates, and where/how are client-submitted prompts strictly validated against them at the network edge? Name the exact files and how drift between the two is prevented.

## Q3
How does the app compute the pixel-to-token geometry for an input image — the ViT patch size, the 2x2 patch merger to LLM tokens, the 25,600-patch budget, the resize/pad plan, and the minimum resolvable object size? Name the source file(s) that implement this math and the function that produces the resize plan used per inference.

## Q4
Trace how an inference request flows from client to model: which HTTP/WebSocket routes exist, how the binary frame (length-prefixed JSON header + JPEG) is parsed and validated, and how the Rust frontend forwards each frame to the Python worker over the Unix domain socket. Name the exact source files and key functions/handlers.

## Q5
How is the LocateAnything-3B model actually loaded and run for inference on the Python side? Cover the asyncio Unix-socket worker entrypoint that serializes GPU access behind a lock, and the inference adapter that loads the model (attn-implementation override, SDPA mem-efficient patches, bf16) and runs .generate(). Name the exact files and key classes/functions.

## Q6
Where do the runtime configuration knobs and pinned versions live, and how are they wired into the two processes at container start? Cover the single source of truth for pinned versions and input caps (LA_MAX_IMAGE_DIM, LA_MAX_JPEG_BYTES, ports), how the entrypoint launches the worker and frontend, and how the Rust binary parses its CLI/env args. Name the exact files.
```
