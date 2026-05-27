# Chunking Strategies and Node Construction in Knowledge Systems

## 1. Chunking Strategies for Documentation

**Fixed-size and recursive splitting** remain the pragmatic default. A Vectara February 2026 benchmark across 50 academic papers placed recursive 512-token splitting at 69% end-to-end accuracy, outperforming more sophisticated methods. The recommended starting point is 256-512 tokens with 10-20% overlap. LangChain's `RecursiveCharacterTextSplitter` works by attempting splits at decreasing granularity (double newline, single newline, sentence boundary, word boundary), falling back only when a chunk exceeds the target size. This preserves document structure cheaply.

**Document-structure-aware chunking** exploits headings, sections, and paragraphs as natural boundaries. Microsoft Azure Architecture Center's 2025 guidance found that prepending section headers to chunks boosts QA accuracy by 15-25 percentage points (from ~55% to ~73%) with no retrieval architecture changes. Markdown-aware splitters that keep heading context attached to child chunks are now standard in both LangChain and LlamaIndex.

**Semantic chunking** uses embedding similarity between adjacent sentences to detect topic boundaries -- when cosine similarity drops below a threshold, a split is inserted. However, a NAACL 2025 Findings paper found that fixed 200-word chunks matched or beat semantic chunking across retrieval and generation tasks. The Vectara 2026 benchmark found semantic chunks averaged only 43 tokens, retrieving cleanly but giving the LLM too little context for correct answers. The overhead is often not justified.

**Agentic chunking** uses an LLM to analyze document content and decide where to split based on semantic completeness. The LLM reads propositions, computes coherence signals, and marks splits when coherence drops. IBM's 2025 tutorial with WatsonX and LangChain sends the first ~8,000 characters to GPT-4 with a system prompt requesting section boundaries with character positions. The approach is expensive (every document requires an LLM call) and a January 2026 Medium analysis flagged it as a hidden cause of RAG hallucinations when the LLM invents boundaries that fragment causal chains.

**Late chunking** (Jina AI, EMNLP 2024 paper, arXiv 2409.04701) inverts the standard pipeline: instead of chunk-then-embed, the entire document is passed through a long-context embedding model to produce token-level embeddings, then chunk boundaries are applied and token embeddings are pooled per chunk. This preserves long-distance contextual dependencies that naive chunking destroys. It requires a long-context embedding model (jina-embeddings-v3 supports it natively). The July 2025 revision of the paper confirmed gains on retrieval benchmarks where cross-chunk references are common.

**Chunk size impact on retrieval quality** is significant. Vectara's NAACL 2025 study found chunking configuration influences retrieval quality as much as embedding model choice across 25 configurations and 48 models. Factoid queries perform best at 256-512 tokens; multi-hop analytical queries at 512-1,024. A January 2026 analysis identified a "context cliff" around 2,500 tokens where response quality drops sharply. Overlap of 10-20% is the standard recommendation, though a January 2026 SPLADE/Mistral-8B study found overlap provided no measurable benefit while increasing indexing cost.

## 2. Node Construction in Knowledge Graphs

**What constitutes a node** depends on the system's granularity. In LlamaIndex, a `TextNode` is the atomic unit -- typically a chunk of a document -- with metadata (source, position, timestamps) and explicit relationships to other nodes (`PREVIOUS`, `NEXT`, `SOURCE`/parent). LlamaIndex's `PropertyGraphIndex` goes further: it extracts **entities** as labeled nodes (Person, Organization, Concept) with typed properties, connected by labeled relationship edges.

LlamaIndex offers three extraction modes for `PropertyGraphIndex`: **schema-guided extraction** (define allowed entity and relationship types; the LLM conforms to the schema), **free-form extraction** (the LLM infers entities, relations, and schema from data), and **implicit extraction** (using the document's own structural relationships -- parent/child, previous/next). The schema-guided approach produces cleaner, more consistent graphs; free-form is useful for exploration but generates more hallucinated edges.

**Microsoft GraphRAG** constructs nodes through a pipeline: source documents are split into `TextUnits` (the atomic analyzable unit), then an LLM extracts all entities, relationships, and key claims from each TextUnit. Entities become graph nodes; relationships become edges. The graph then undergoes hierarchical community detection using the Leiden algorithm, producing clusters at multiple resolutions. Each community gets an LLM-generated summary. At query time, **Global Search** reasons over community summaries for corpus-wide questions; **Local Search** fans out from specific entities through their neighbors; **DRIFT Search** (added 2025) blends entity-specific and community-level context.

**Diffbot** takes a different approach entirely: automated web crawling across 60+ billion pages, with ML-based extraction producing 10+ billion entities and 1 trillion facts. As of January 2026, 50 billion new facts were added in a single month. Entities are typed (People, Organizations, Products, Articles, Events) and queryable via DQL, Diffbot's query language. This is not document-chunking-based but rather web-scale NER and relation extraction.

## 3. Relationship and Edge Modeling

Edge types in documentation graphs fall into several categories: **hierarchical** (document contains section contains paragraph; parent-child in LlamaIndex), **sequential** (previous/next chunk, providing narrative flow), **referential** (cross-references, hyperlinks, citations), **semantic** (embedding similarity above a threshold), **typed relational** (works_at, located_in, created_by -- the knowledge graph tradition), and **causal/temporal** (event A caused event B, or preceded it).

Relationship discovery methods include: **explicit markup** (parsing hyperlinks, heading hierarchy, YAML frontmatter references), **LLM extraction** (prompting the model to extract subject-predicate-object triples, with or without a constraining schema), **embedding similarity** (connecting chunks whose embeddings are within a cosine distance threshold), **co-occurrence** (entities mentioned in the same TextUnit are likely related), and **dependency parsing** combined with graph neural networks for relation extraction (a 2025 Nature Scientific Reports paper described this approach).

**Multi-hop reasoning** is the primary motivation for graph-based retrieval over flat vector search. Neo4j's `VectorCypherRetriever` performs vector similarity search to find entry-point nodes, then executes Cypher traversals to pull in connected subgraphs. LangChain's `GraphRetriever` package supports breadth-first (Eager) and MMR-based traversal strategies. Microsoft GraphRAG's community hierarchy inherently supports multi-hop by surfacing relationships that span multiple entities.

## 4. Metadata and Enrichment

Node metadata typically includes: source document URI, creation/modification timestamps, author, section title, chunk position within the document, extracted entities, topic labels, and the embedding vector itself. A December 2025 paper (arXiv 2512.05411) described an LLM-based metadata generation pipeline that dynamically creates semantic tags, topic classifications, and relevance scores for chunks, improving vector space organization while maintaining sub-30ms P95 retrieval latency.

**Hybrid vector + graph** is the dominant architecture pattern for 2025-2026. Text chunks and entity descriptions are embedded and stored in a vector index (Qdrant, Chroma, or Neo4j's native vector index). Entities and relationships are stored as a property graph. At query time, vector search finds semantically relevant entry points; graph traversal enriches the context with structurally connected facts. TigerGraph v4.2 (December 2024) integrated vector type expressions directly into its GSQL query language, enabling compositions between vector search results and graph traversals in a single query.

**Versioning and staleness** remain under-addressed. Neo4j's documentation recommends modeling temporal validity as properties on relationship edges (valid_from, valid_to) or maintaining parallel version chains. GraphER (arXiv 2603.24925, March 2026) introduced graph-based enrichment and reranking that captures multiple proximity forms during offline indexing and applies graph-based reranking at query time, which indirectly helps with freshness by re-scoring based on recency metadata.

## 5. Notable Implementations (2024-2026)

- **LlamaIndex PropertyGraphIndex**: Schema-guided or free-form entity/relation extraction, stores in Neo4j or Nebula, supports vector + keyword + Cypher retrieval modes. Deprecated the older `KnowledgeGraphIndex`.
- **LangChain GraphRetriever** (`langchain-graph-retriever` on PyPI): Combines vector similarity search with structured metadata traversal. Supports AstraDB, Cassandra, Chroma, OpenSearch backends.
- **Microsoft GraphRAG** (open-source, github.com/microsoft/graphrag): TextUnit extraction, LLM entity/relation extraction, Leiden community detection, hierarchical community summaries, Global/Local/DRIFT search modes. Improved in 2025 with dynamic community selection for more efficient global search.
- **Diffbot Knowledge Graph**: Web-scale automated extraction, 10B+ entities, 1T+ facts, DQL query language. Released a GraphRAG LLM endpoint for combining their KG with retrieval.
- **Neo4j GraphRAG Python package** (`neo4j-graphrag-python`): First-party library providing `VectorCypherRetriever` for hybrid vector + graph traversal, with pipeline components for entity extraction and graph construction.
- **Jina AI late chunking**: Available in jina-embeddings-v3 API, preserves cross-chunk context through token-level embedding before chunking.

## Sources

- [Document Chunking for RAG: 9 Strategies Tested (2025)](https://langcopilot.com/posts/2025-10-11-document-chunking-for-rag-practical-guide)
- [Best Chunking Strategies for RAG in 2026 (Firecrawl)](https://www.firecrawl.dev/blog/best-chunking-strategies-rag)
- [Chunking Strategies: The Hidden Lever in RAG Performance](https://dasroot.net/posts/2026/02/chunking-strategies-rag-performance/)
- [Rethinking Chunk Size for Long-Document Retrieval (arXiv 2505.21700)](https://arxiv.org/html/2505.21700v2)
- [LlamaIndex Property Graph Index Guide](https://www.llamaindex.ai/blog/introducing-the-property-graph-index-a-powerful-new-way-to-build-knowledge-graphs-with-llms)
- [LlamaIndex PropertyGraphIndex Documentation](https://docs.llamaindex.ai/en/stable/module_guides/indexing/lpg_index_guide/)
- [Microsoft GraphRAG Official Site](https://microsoft.github.io/graphrag/)
- [GraphRAG: From Local to Global (arXiv 2404.16130)](https://arxiv.org/abs/2404.16130)
- [GraphRAG Dynamic Community Selection (Microsoft Research)](https://www.microsoft.com/en-us/research/blog/graphrag-improving-global-search-via-dynamic-community-selection/)
- [Late Chunking in Long-Context Embedding Models (Jina AI)](https://jina.ai/news/late-chunking-in-long-context-embedding-models/)
- [Late Chunking arXiv Paper (2409.04701)](https://arxiv.org/pdf/2409.04701)
- [Neo4j VectorCypherRetriever Documentation](https://neo4j.com/docs/neo4j-graphrag-python/current/user_guide_rag.html)
- [LangChain GraphRetriever (PyPI)](https://pypi.org/project/langchain-graph-retriever/)
- [Diffbot Knowledge Graph](https://www.diffbot.com/products/knowledge-graph/)
- [Agentic Chunking with LangChain and WatsonX (IBM)](https://www.ibm.com/think/tutorials/use-agentic-chunking-to-optimize-llm-inputs-with-langchain-watsonx-ai)
- [LLM-Generated Metadata for RAG (arXiv 2512.05411)](https://arxiv.org/pdf/2512.05411)
- [GraphER: Graph-Based Enrichment and Reranking (arXiv 2603.24925)](https://arxiv.org/pdf/2603.24925)
- [TigerVector: Vector Search in Graph Databases (arXiv 2501.11216)](https://arxiv.org/pdf/2501.11216)
- [Knowledge Graph Construction: Extraction, Learning, and Evaluation (MDPI 2025)](https://www.mdpi.com/2076-3417/15/7/3727)
- [NVIDIA Chunking Strategy Guide](https://developer.nvidia.com/blog/finding-the-best-chunking-strategy-for-accurate-ai-responses/)
