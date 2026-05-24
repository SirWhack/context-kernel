# Derive `graph_commit` from source content, not from graph state

**Status:** accepted
**Date:** 2026-05-24

`graph_commit` is the opaque hash downstream modules embed in materialized freshness headers (per [ARCHITECTURE.md](../../ARCHITECTURE.md) §2.1). It answers the question: "is this materialized file derived from a Graph state that is still current?"

We compute it as **SHA-256 over `(portfolio_root_relative_path, SHA-256(file_contents))` pairs, sorted by path, newline-joined**, taken over every source file ingested in the pass. The same primitive scoped to one directory's files is the per-scope **source-tree hash** stored in the same freshness header. Ingester computes `graph_commit` *before* invoking LightRAG and passes it through to `KnowledgeStore.upsert(graph_commit, ...)`. The Graph stores it and returns it on `graph_commit()`; it does not derive its own.

## Considered options

- **Graph derives `graph_commit` from its own state** (hash over entities + relationships + summaries it now holds). Rejected because LightRAG's entity extraction is LLM-driven and **nondeterministic** — re-running ingest over identical sources produces slightly different entity descriptions, IDs, and relationship phrasings, which would mint a different `graph_commit` every time. Every materialized file would mark stale on every re-ingest. Breaks idempotency and makes the freshness header useless as a "did anything change?" signal.
- **`graph_commit` is a UUID minted per ingest pass.** Cheap, monotonic. Rejected for the same reason — re-ingest on unchanged sources produces a new UUID, marking every file stale even when nothing has changed. Violates the spirit of [THEORY.md](../../THEORY.md) invariant 4 (content-addressing).
- **`graph_commit` is the hash of LightRAG's storage trio serialized canonically.** Rejected because it ties the commit identity to LightRAG's internal serialization format. Storage backends are pluggable per [ARCHITECTURE.md](../../ARCHITECTURE.md) §2.1; canonical serialization differs across them; the commit identity would change under the operator's feet if the backend swapped. Also has the LLM-nondeterminism problem.

## Consequences

- **Re-ingest on unchanged sources is genuinely a no-op.** Same source content → same `graph_commit` → existing materialized files match by header → no regeneration. The "incremental update story" Ingester owns ([ARCHITECTURE.md](../../ARCHITECTURE.md) §2.2) becomes real, not aspirational.
- **`graph_commit` and per-scope `source-tree hash` share one primitive** — the same hash function over different file sets. One implementation, one set of tests, one canonical edge-case story (empty scope, single-file scope, binary files).
- **`KnowledgeStore.upsert` takes `graph_commit` as input, not output.** Slightly inverted from a typical "transactional store" interface but reads cleanly: "here is the commit identity, here are the artifacts to associate with it."
- **Swapping the indexing LLM does NOT change `graph_commit`.** The Graph contents differ (different entity descriptions), but the commit identity does not, since it's derived purely from source content. This is fine for the freshness invariant — the question `graph_commit` answers is "are sources unchanged?", not "is the graph identical?" The user-facing implication: changing LLMs requires `rm -rf .context-kernel/` to fully rebuild, consistent with [ARCHITECTURE.md](../../ARCHITECTURE.md) §8 (no schema migration tooling).
- **Computing `graph_commit` requires walking and hashing every source file once per ingest.** For a portfolio of thousands of files this becomes the floor of ingest latency; mitigation is a `(path, mtime, size)`-keyed cache of per-file SHAs. Out of scope for v1.

## When this should be revisited

- LightRAG (or a successor) gains deterministic extraction (e.g., via a non-LLM extractor for some entity kinds) — Graph-derived commit could become viable for that subset.
- A use case emerges where two distinct Graph states over the same sources need to be distinguished (e.g., A/B-ing extraction prompts on the same corpus) — would need a richer commit identity that incorporates the extraction config hash.
- The per-ingest cost of hashing every source file becomes a real bottleneck — would push toward the mtime/size cache or an explicit content-tracking layer.
