# Kernel-vs-grep eval harness

Measures whether the Context Kernel MCP helps a coding agent **ground itself in an
unfamiliar repo** faster/cheaper than a plain grep baseline. Two headless `claude` (sonnet)
sessions answer the same numbered battery of curated questions about one repo; their
transcripts are scored by [`scripts/h2_eval.py`](../../scripts/h2_eval.py).

```
python evals/harness/run_eval.py --repo <repo-under-test-repos>      # both arms + score
python evals/harness/run_eval.py --repo <repo> --arm kernel --no-score
python evals/harness/run_eval.py --repo <repo> --score-only          # re-score existing transcripts
```

## Arms

| | tools | how it retrieves |
|---|---|---|
| **kernel** (Arm A) | `mcp__ck__find`, `mcp__ck__overview`, `Read`, `ToolSearch` | per-repo stdio `ck mcp --config <repo>/.context-kernel/config.toml`, semantic search over the graph |
| **grep** (Arm B) | `Grep`, `Glob`, `Read`, `Bash` | raw filesystem, ripgrep/find |

Each session runs in a neutral temp cwd (no `CLAUDE.md` auto-load) with `--add-dir <repo>`.

## Two traps this harness is built to avoid

1. **Tool isolation is not enforced by `--allowedTools`.** Under `bypassPermissions`,
   allowedTools is only pre-approval — non-listed tools are still callable.
   `--disallowedTools` *does* bind, so a comprehensive `ESCAPE` list (Workflow, Agent,
   Task\*, Web\*, Edit/Write, + ToolSearch for the grep arm) blocks every escape hatch.
   Without it the grep arm reached for `Workflow` and orchestrated hidden sub-agents — not a
   grep baseline at all. **Always confirm post-run that each arm used only its own tools.**

2. **Public test repos are memorized by Sonnet.** A model can "answer" a famous repo from
   training instead of retrieving. Defenses: the prompt rule *"cite a file only if you
   opened it this session"*, and `h2_eval`'s **grounded** axis (gold files actually `Read`,
   not merely named). When `grounded == recalled`, no file was cited from memory.

## Scorecard axes (`h2_eval.py`)

- **COST** — tool calls, failed calls, duplicate reads, fresh tokens.
- **HALLUCINATION** — claimed paths that resolve to nothing under the repo.
- **RECALL** — gold files the answer named, per question.
- **GROUNDED** — gold files the arm actually opened (the memory-proof signal).
- **ASPECT-PRECISION** — only if the repo has `.context-kernel/ontology.toml` (foreign repos
  don't; that axis is skipped).

## Tasks & gold

`tasks/<repo>.json` — curated questions, each with a hand-verified `gold` file list. Gold
should cover diverse file types (code + infra/config); `h2_eval`'s path matcher is
infra-aware (`.sh`, `.ya?ml`, `.toml`, `.json`, `Dockerfile`, …). The runner renders a
`gold.toml` next to the transcripts for the recall/grounding axes.

Session transcripts (`evals/runs/sessions/`) are gitignored — they contain corpus content.
The runner, task files, and this README are committed.
