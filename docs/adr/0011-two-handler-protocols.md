# Separate handler protocols for structured and unstructured source formats

**Status:** accepted
**Date:** 2026-05-24

Two handler protocols instead of one: `ChunkHandler` for unstructured sources (markdown, prose, PDFs) that produce text chunks for the LLM Summarizer, and `StructuredHandler` for parseable sources (Python, TS/JS) that extract entities directly via AST analysis. The ingester dispatches to the right protocol per file.

## Why two

Python's AST gives us entities (classes, functions, modules), relationships (inheritance, imports), and Ousterhout-style depth signals (public/private split, LOC, method counts) mechanically. Sending structured text through an LLM to re-extract what the parser already knows is redundant and lossy. Markdown has no parseable structure — the LLM is the entity extractor.

These are different intents behind different interfaces. A single protocol with a union return type or sniff-based dispatch hides that distinction instead of expressing it.

## Considered options

1. **One protocol, richer return type** — `chunks()` returns either raw text or pre-extracted entities. Rejected: type union obscures intent; caller must sniff the result.
2. **One protocol, two methods with defaults** — `extract()` defaults to empty; `chunks()` defaults to empty. Rejected: every handler carries dead interface; depth without purpose.
3. **Keep one protocol, deterministic parser post-hoc** — handler returns structured text, a parser extracts entities without LLM. Rejected: two-step pipeline for what should be one call; parser couples to handler's text format.
4. **Two protocols** — `ChunkHandler` and `StructuredHandler`. Accepted: each hides one decision; ingester dispatches cleanly.

## Consequences

- Adding a new source format requires choosing which protocol it implements — a forcing function for thinking about whether the format has parseable structure.
- The ingester orchestration loop has two code paths (Summarizer-dependent and Summarizer-independent). Both must be tested.
- `StructuredHandler` returns `RawEntity`/`RawRelationship` (no graph IDs); the ingester derives IDs. Clean boundary between parsing and graph identity.
