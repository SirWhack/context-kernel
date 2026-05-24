# Produce per-scope summaries via a second-pass LLM call at ingest

**Status:** accepted
**Date:** 2026-05-24

LightRAG's ingest produces cross-document entities and relationships. Context Kernel needs **per-scope summaries** — one orientation paragraph per directory in the portfolio, rendered into `AGENTS.md` at every scope. [CONTEXT.md](../../CONTEXT.md) commits the Graph to holding "entities, relationships, **and per-scope summaries**" as a real data class, and [ARCHITECTURE.md](../../ARCHITECTURE.md) §2.3 commits the Materializer to being a pure function of `(scope, graph_commit, view_spec) → markdown`. Pure functions cannot call LLMs.

Therefore: the Ingester runs a **second pass** at the end of every `ck ingest`. For each scope (every directory under `portfolio_root` containing ≥1 ingested file), one LLM call is made that consumes the scope's source-file list plus LightRAG's extracted entities and cross-scope relationships, and emits a ~500-token markdown orientation summary. The resulting `Summary(scope, digest, markdown)` is content-addressed under `.context-kernel/summaries/<sha256>.md` and recorded in the Graph. The Materializer reads it back during `ck materialize` and prepends only the freshness header — no LLM call at materialize time.

## Considered options

- **Materializer renders a deterministic template from raw entities; no LLM anywhere.** Cheap, pure, deterministic. Rejected because [CONTEXT.md](../../CONTEXT.md) treats "per-scope summary" as a real data class — prose, not a templated entity list — and an agent reading a dry catalog still has to synthesize, defeating the orientation goal that justifies the materialized tree at all.
- **Aggregate LightRAG's per-entity descriptions, grouped by scope.** No new LLM calls. Rejected because the output is "an entity catalog with descriptions", not "what this scope is about". Quality is bounded by LightRAG's per-entity prompt rather than by a scope-level synthesis prompt; the orientation problem persists.
- **Materializer makes the LLM call lazily on first read of a stale scope.** Closer in feel to [ADR-0003](./0003-pull-based-jit-regeneration.md)'s JIT mechanism. Rejected because it breaks the Materializer purity claim in [ARCHITECTURE.md](../../ARCHITECTURE.md) §2.3, and stacks synthesis latency on top of regeneration latency — exactly the 60s budget [THEORY.md](../../THEORY.md) open question 3 is trying to validate.

## Consequences

- **Extra LLM calls per ingest = number of scopes.** For a portfolio with ~10 directories, that's ~10 extra calls — negligible vs. the hundreds LightRAG natively makes for entity extraction. For a portfolio with hundreds of scopes, ingest gets meaningfully slower; ingest is already a batch operation allowed to be slow per [ADR-0003](./0003-pull-based-jit-regeneration.md).
- **Summaries are cacheable by scope-contents hash.** If a scope's source files are unchanged since the last ingest, reuse the stored `Summary` and skip the second-pass call. Change detection is already an Ingester-owned concern per [ARCHITECTURE.md](../../ARCHITECTURE.md) §2.2.
- **Materializer stays pure.** Given the same Graph state, materializing the same scope produces byte-identical output. This preserves the "no runtime synthesis" claim downstream — OrientationServer reading materialized `AGENTS.md` content stays consistent with [THEORY.md](../../THEORY.md) invariant 3.
- **The synthesis prompt is the lever for `AGENTS.md` quality** — bounded by one template, iterable without touching LightRAG.
- **Failure is per-scope.** If one synthesis call fails or returns malformed content, that scope's `Summary` is missing and the Materializer renders a fallback (`summary unavailable, see source files`); other scopes are unaffected.

## When this should be revisited

- Second-pass synthesis meaningfully blows the 60s first-read budget even with caching — would point to a shorter prompt, a different indexing LLM, or accepting a non-prose `Summary` for large scopes.
- LightRAG (or its successor) starts emitting per-scope summaries natively — the second pass becomes dead weight.
- Summary quality stays poor across prompt iterations — would point to scope decomposition being too coarse, the indexing LLM being undermatched, or the orientation framing being wrong.
