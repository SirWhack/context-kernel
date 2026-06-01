<!-- context-kernel-freshness
graph: ce4c30de6021574f8be593ca3ef2c62ccfde5e39118e774477c1d6d76f0f9abe
source-tree: 5fa7aeb1b50492a09844e171f2344bc8ee92a86c490be64411ce1242a1e6ca54
materialized: 2026-06-01T01:08:20Z
-->

This scope contains the evaluation and analysis scripts that validate, measure, and improve the context kernel's behavior against ground truth. These are standalone diagnostic tools, not part of the runtime kernel — they run on demand to audit session transcripts, verify graph integrity, and materialize concept views. The scripts are organized around three responsibilities: auditing Claude Code sessions (`h2_eval.py`), grounding concepts in source code (`concept_classify.py`, `concept_materialize.py`, `concept_gotchas.py`, `concept_spans.py`), and verifying the knowledge graph (`verify_graph.py`, `scoring_distribution.py`, `expansion_ab.py`).

The central evaluation tool is `h2_eval.py`, which formalizes the manual audit process for orientation sessions. It scores transcripts on three deterministic axes: cost (tool calls, tokens, failures), hallucination (file paths in the answer that don't resolve), and aspect precision (whether files claimed for coordination concepts actually contain coordination primitives). It reads transcripts as `.jsonl` files and the ontology from `$CK_PORTFOLIO/.context-kernel/ontology.toml`, using `concept_spans.precision_patterns` and `concept_spans.find_spans` as the ground-truth oracle for what counts as a coordination primitive. The `expansion_ab.py` script isolates the retrieval effect of ADR-0023's query-time neighbor expansion by calling `nearest_chunks` and `rank_by_relevance` directly, bypassing the token-budget truncation in `find()`.

The concept grounding scripts implement a two-stage "coarse recall → attention precision" pattern. `concept_classify.py` first runs a cheap keyword prefilter over code entities, then uses an LLM to judge each candidate against the aspect's definition — producing confidence scores without mutating the graph. `concept_materialize.py` writes each concept as a markdown hub under `.context-kernel/views/concepts/`, giving agents a `resolve-concept` surface with exact source paths and governing ADRs. `concept_gotchas.py` extracts code-level landmines for entity-concepts that skip the LLM judge. All grounding scripts read from `$CK_PORTFOLIO/.context-kernel/graph/state.json` and the ontology, and write results to `spike-results/` — they are generic, driven by `CK_PORTFOLIO` with no corpus-specific names.

Graph verification scripts (`verify_graph.py`, `scoring_distribution.py`) inspect the re-ingested graph's density, traversal, and scoring distributions. They import from `context_kernel.graph.lightrag_adapter` and `context_kernel.types` to load the store and entities, then report confidence/centrality/drift distributions split by entity class. These scripts depend on the kernel's internal modules (`config_store`, `ingester._http`, `orientation_server.tools`) and the `concept_spans` module for pattern matching — they are tightly coupled to the kernel's data structures but run as standalone diagnostics, not as part of the serving path.

## Recommended documentation

This scope has 79 code entities across 1 files but no reference documentation. To create one: `/init-reference scripts`

