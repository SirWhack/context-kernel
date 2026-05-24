# Regenerate materialized files JIT on read, not on source change

**Status:** superseded by [ADR-0010](./0010-pre-commit-hook-regeneration.md)
**Date:** 2026-05-23

Context Kernel runs no daemon, file watcher, or background regenerator. Instead, a **freshness gate** runs before every read of a materialized file:

- **Direct file reads** (agent uses `Read`/`Grep`/`Glob`): the Claude Code `PreToolUse` hook invokes `ck check <path>`; on hash mismatch, `ck materialize <scope>` runs before the read returns.
- **MCP calls** (`overview`, `find`): the MCP server invokes the same `ck check` on every materialized file it's about to source chunks from; mismatch triggers regeneration before the response is built.

The first read after a source change pays the regeneration cost. Subsequent reads return immediately from cached materialized files. The agent literally cannot receive a stale chunk — staleness is an error class designed out of existence at the read boundary, not a class of bug detected and patched after the fact.

This enforces [THEORY.md](../../THEORY.md) invariant 2 ("no materialized file is ever served stale") and is the implementation of [THEORY.md](../../THEORY.md) Non-goal 4 ("no push-based / file-watcher regeneration").

## Considered options

- **Push-based regeneration via file watcher** (inotify, fswatch, chokidar). Rejected: requires a daemon, a lifecycle, and a story for what happens when the watcher is stopped, misconfigured, restarting, or behind. The failure mode of a stopped watcher is silent staleness — the same failure the freshness gate exists to eliminate. Adding watcher-health checks just moves the failure mode one level up.
- **Manual `ck materialize` after every source edit.** Rejected: the discipline burden lands on the user; the failure mode (forgetting) silently serves stale chunks to the agent. Violates invariant 2.
- **Regeneration via git hooks** (`post-commit`, `pre-push`). Rejected: only fires on commit, not on every edit. The agent's most common working pattern is *read while the user is mid-edit* — exactly the case git hooks miss. Also creates a coupling to git that not every project wants.
- **Eager full-tree regeneration on `ck` startup.** Rejected: makes startup time grow with portfolio size; defeats the "the kernel adds zero ambient cost when nothing is being read" property.

## Consequences

- No background process to manage, observe, restart, or migrate. Removing Context Kernel from a portfolio is `rm -rf .context-kernel/` plus uninstalling the hook; nothing else stops.
- First-read latency on a stale scope is the worst-case user-visible cost. If regenerating a large unseen scope takes 60+ seconds on the agent's first read, the agent UX collapses. This is logged as open question 3 in `THEORY.md` — measurement required in the first 3 days of v1 work. If intolerable, revisit this ADR; resolution may flip Non-goal 4.
- The MCP server reuses the same `ck check` mechanism — there is no parallel staleness logic that could drift between read paths. One enforcement point, two callers.
- The Ousterhout principle "define errors out of existence" is preserved: there is no class of bug where the agent reads a stale chunk and downstream code has to detect/correct it. The class of bug is structurally impossible.
- The hook-based mechanism is Claude-Code-specific. For non-Claude-Code agents, the fallback is a `pre-commit` git hook running `ck materialize` — slower, weaker (only covers committed state), but works without a harness integration. This is logged in `docs/design.md` Open question on harness portability.

## When this should be revisited

- First-read latency measurement (open question 3) returns numbers that make the agent UX painful — typically a sign that summarization is too slow, the source tree is huge, or scope decomposition is too coarse. May require flipping to push-based, sharper scope decomposition, or precomputed-on-write summaries.
- A future MCP write tool (allowed under invariant 1) creates write traffic the gate has to interleave with reads safely — may need a different concurrency story.
- The portfolio grows to a size where eager-on-startup becomes preferable to JIT-on-read (unlikely, but worth flagging).
