# Materialize per-scope context as `AGENTS.md`, bridge to Claude Code via `@AGENTS.md` import

**Status:** accepted
**Date:** 2026-05-23

Context Kernel's materialization pass writes per-scope context to `AGENTS.md` rather than `CLAUDE.md`. To preserve Claude Code's directory-walking auto-load behavior — which only loads `CLAUDE.md` files at session start — each scope also gets a thin materialized `CLAUDE.md` containing a single `@AGENTS.md` import. The agent's altitude-appropriate context loads automatically up the directory tree as it would for any Claude Code project, but the canonical content lives in `AGENTS.md` and remains readable by other coding agents (Cursor, etc.) without requiring a per-tool bridge in the kernel itself.

This preserves the multi-agent framing in [THEORY.md](../../THEORY.md)'s Shape ("coding agents working over it") while still buying the Claude-Code-specific UX win where spawning the agent at any scope produces the right context for free.

## Considered options

- **Materialize `CLAUDE.md` directly.** Rejected: locks Context Kernel into a Claude-Code-only future. The thesis names "coding agents" plural. While today's portfolio is all Claude Code, future-proofing the materialization filename is cheap and the irreversibility is real (the name lives at every scope across the whole portfolio).
- **Materialize `AGENTS.md` only, no bridge.** Rejected: Claude Code does not auto-load `AGENTS.md` (confirmed in [Claude Code memory docs](https://code.claude.com/docs/en/memory)). Without a `CLAUDE.md` bridge per scope, the agent only sees materialized context when it explicitly reads the file — losing the directory-walking auto-load that makes altitude-appropriate context delivery free.
- **Symlink `CLAUDE.md → AGENTS.md` per scope.** Considered: works on POSIX, fails on Windows without Administrator privileges or Developer Mode. The `@AGENTS.md` import works everywhere Claude Code runs and is what the Claude Code docs themselves recommend for `AGENTS.md`-using repos.

## Consequences

- The materialization pass produces two files per scope: `AGENTS.md` (canonical content) and `CLAUDE.md` (single `@AGENTS.md` import line). Both are pure functions of the graph state — both are derivable and overwritable.
- Hand-written `CLAUDE.md` files (like the one at this project root, written during `/init-theory-project`) coexist with materialized ones. The hand-written `CLAUDE.md` at the model-time root is **not** managed by Context Kernel — it's the project's own agent operating rules. Once Context Kernel materializes here, the hand-written `CLAUDE.md` will need to add `@AGENTS.md` as an additional import so the agent composes hand-written rules with the materialized scope context.
- The "coding agent" framing in `THEORY.md` Shape stays multi-agent without per-agent bridges in the kernel implementation.
- If another mainstream agent (Cursor, Aider, Codex) ships with a different default-loaded filename, the same bridge pattern applies — Context Kernel materializes one `<agent>.md` import file per supported agent at each scope. The canonical content stays single-sourced in `AGENTS.md`.

## When this should be revisited

- If `AGENTS.md` as a tool-agnostic convention loses traction and Claude-Code-only becomes the project's settled audience.
- If Claude Code changes its memory-load behavior such that `AGENTS.md` is also auto-loaded (the bridge would become redundant).
- If the cost of materializing two files per scope (storage, regeneration time) ever becomes load-bearing — likely not.
