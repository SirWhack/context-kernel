# ADR-0016: Contextual Entity Extraction

## Status

Accepted

## Context

ADR-0015 addresses confidence scoring AFTER entities are extracted. This ADR addresses the upstream problem: the entity extractor operates in a vacuum. Each markdown chunk is sent to the LLM independently, with no visibility into:

1. **Code state** — Phase 1 (structured handlers) completes before Phase 2 (chunk handlers). Code entities are already known when doc chunks are processed, but the extraction prompt doesn't include them. HANDOFF.md's "Summarizer not yet wired" claim was extracted as a valid entity because the extractor didn't know `LLMSummarizer` was already instantiated.

2. **Canonical vocabulary** — CONTEXT.md defines terms like "Materialized file," "Scope," "Freshness gate." But the extractor processing a doc chunk that says "generated docs" doesn't know the canonical term is "Materialized file" — it extracts a duplicate entity with a different name. The graph audit found 13% entity duplication, likely from this.

3. **Document identity** — The extractor doesn't know whether a chunk comes from THEORY.md (trunk, invariant-level claims) or a stale handoff note (ephemeral, likely outdated). The heading path and source file metadata are not in the prompt.

Confidence scoring mitigates bad entities after extraction. Contextual extraction prevents them from being created.

## Decision

The Phase 2 entity extraction prompt gains a context prefix containing three sections, prepended to every chunk extraction call:

### 1. Known code entities (from Phase 1)

A condensed summary of entities extracted by structured handlers in Phase 1:
```
## Known code entities
- LLMSummarizer (class, ingester/summarizer.py): Concrete Summarizer implementation...
- HttpEmbedder (class, ingester/embedder.py): Embedder backed by OpenAI-compatible endpoint...
- KnowledgeStore (protocol, graph/protocol.py): 9 methods — graph_commit, get_entity, ...
```

Truncated to fit a token budget (configurable, default ~2000 tokens). Entities sorted by centrality so the most structurally important ones survive truncation.

### 2. Canonical vocabulary (from CONTEXT.md)

The glossary terms and their definitions:
```
## Canonical vocabulary
- Materialized file: A markdown file projected from the graph by ck materialize
- Scope: The unit a single materialized file covers; coterminous with a directory in v1
- Freshness gate: The mechanism that keeps materialized files in sync with their source
```

### 3. Source metadata

The chunk's source file path and heading path:
```
## Source
File: HANDOFF.md (authority: ephemeral, shelf-life: days)
Section: What's not done
```

The extraction prompt rules are extended:
- "Use canonical terms from the vocabulary when they match concepts in the chunk."
- "If the chunk's claim contradicts a known code entity, extract the entity with kind `stale-claim` instead of its apparent kind."
- "Prefer referencing known code entity names over creating new entity names for the same concept."

### Cost impact

The context prefix is identical across all Phase 2 calls within one ingest run. With DeepSeek's prompt caching (84.6% hit rate observed), the prefix is cached after the first call. At $0.0028/M for cache hits vs $0.14/M for misses, a 2000-token prefix across 652 calls costs ~$0.004 in cache hits. Negligible.

For local models (no server-side caching), the prefix adds ~2000 tokens per call. At 1.5s/chunk on the 7900 XTX, the additional encoding overhead is measurable but bounded — the system prompt is already ~500 tokens, so this roughly quadruples the input size but does not change the output size.

## Consequences

- Entity duplication from inconsistent naming is reduced (canonical vocabulary provides consistent terms)
- Stale doc claims are flagged at extraction time, not just de-weighted after the fact
- Code entities from Phase 1 serve as ground truth that doc entity extraction is checked against
- The `stale-claim` entity kind provides a signal for both confidence scoring (ADR-0015) and contradiction detection (issue #4)
- CONTEXT.md becomes operationally load-bearing in the ingestion pipeline, not just a human reference
- The extraction prompt grows by ~2000 tokens but is cache-friendly across all calls in a run

## Related

- [ADR-0015](./0015-entity-confidence-scoring.md) — downstream confidence scoring on extracted entities
- [ADR-0013](./0013-markdown-entity-taxonomy.md) — entity kind taxonomy (gains `stale-claim` kind)
- GitHub issue #4 — doc-vs-code contradiction detection
