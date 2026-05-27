# RAG and Graph-Based Documentation Systems

## 1. Standard RAG for Documentation: What Breaks

The canonical RAG pipeline -- chunk documents, embed chunks, store in a vector database, retrieve by cosine similarity, generate with retrieved context -- has a fundamental structural tension. Semantic matching works best with small chunks (100-256 tokens), but context understanding requires larger chunks (1024+ tokens). This forces a trade-off between "precise but fragmented" and "complete but vague".

Three failure modes dominate in documentation settings. First, **context loss**: a chunk that says "its `retry` parameter accepts a backoff function" becomes meaningless without knowing which method or library is being discussed. Second, **cross-document reasoning failure**: when a user asks "how does authentication interact with rate limiting?", naive RAG retrieves chunks about each topic independently but cannot synthesize their relationship. Third, **retrieval quality bottlenecks**: if the retriever selects irrelevant or incomplete chunks, the generator produces hallucinated or unsupported answers, a problem Google Research has studied extensively in the context of "sufficient context."

## 2. GraphRAG (Microsoft)

Microsoft's GraphRAG paper (April 2024, Edge et al., arXiv 2404.16130) introduced a two-stage indexing pipeline. First, an LLM extracts entities and relationships from source documents to build a knowledge graph. Second, the Leiden community-detection algorithm partitions the graph into hierarchical communities, and the LLM generates **community summaries** -- natural-language descriptions of each cluster's key entities, relationships, and claims.

At query time, GraphRAG offers two retrieval modes. **Local search** operates like enhanced RAG: it finds relevant entities, pulls their neighborhoods from the graph, and generates answers grounded in those subgraphs. **Global search** is the novel contribution: it fans out across community summaries in a map-reduce pattern, generating partial answers from each community and then synthesizing them into a final response. This enables "global sensemaking" queries ("what are the main themes in this corpus?") that naive RAG cannot answer because no single chunk contains the answer.

The trade-off is cost. Full GraphRAG indexing requires LLM calls for every chunk (entity extraction) and every community (summarization). Microsoft's own cost analysis identifies two major cost centers: graph construction (indexing) and graph retrieval (query-time map-reduce). This led to **LazyGraphRAG** (2025), which defers all LLM summarization to query time, performing only lightweight NLP-based graph construction during indexing. The result: indexing costs drop to 0.1% of full GraphRAG, and global query costs fall 700x at comparable quality. KET-RAG, a separate 2025 framework, achieves comparable coverage at 18.3% of competitor indexing costs through multi-granular indexing.

## 3. Hybrid Approaches: Vector Search + Graph Traversal

The most practical production systems in 2025-2026 combine both paradigms. **Neo4j's hybrid retrieval architecture** merges two retrieval paths -- graph traversal over entities/relations and vector similarity over text embeddings -- into a merged result ranked by a lightweight scoring function. As of Neo4j 2026.01, the library uses the Cypher `SEARCH` clause for vector queries, enabling in-index filtering that unifies graph and vector operations.

**TigerGraph's TigerVector** (2025) embeds vector search directly inside a graph database engine, arguing that the graph context around a retrieved node (its neighbors, paths, community membership) is as valuable as the embedding match itself.

**Weaviate** takes a different approach with its cross-reference system, where objects in the vector store can reference other objects, creating lightweight graph-like traversal on top of vector search. Their benchmarks show hybrid search (vector + BM25 + reranking) improving Success@1 by 17% over vector-only retrieval. Real-world GraphRAG implementations report 20-35% improvement in retrieval precision over traditional RAG.

## 4. LlamaIndex's Graph Approaches

LlamaIndex's **PropertyGraphIndex** builds a labeled property graph from unstructured documents using modular "graph constructors" -- LLM-based extractors that identify entities, relationships, and properties. Unlike earlier KnowledgeGraphIndex (which produced simple triples), property graphs support typed nodes, typed edges, and key-value properties on both, enabling far richer modeling.

At retrieval time, LlamaIndex provides swappable **graph retrievers**: keyword-based entity lookup, vector-similarity search over graph elements, Cypher-query generation, and custom traversal strategies. The **KnowledgeGraphRAGRetriever** performs subgraph retrieval -- given a query, it identifies relevant entities and pulls their local subgraphs as context. The GraphRAG v2 cookbook demonstrates combining LlamaIndex's property graph with Microsoft-style community detection for hybrid local/global retrieval.

## 5. Anthropic's Contextual Retrieval

Anthropic's approach (September 2024) attacks the root cause of chunking-induced context loss without building a graph at all. Before embedding, each chunk is sent to an LLM with the full document, and the LLM generates a short contextualizing prefix (roughly 50-100 tokens) that situates the chunk within its source. For example, a chunk about retry parameters gets prepended with "This chunk is from the `HttpClient` class documentation in ACME SDK v3.2".

This reduces retrieval failure rates by up to 67%. Combined with BM25 hybrid search and reranking, Anthropic's full pipeline achieves strong results at a one-time cost of roughly $1.02 per million document tokens.

**Compared to graph approaches**, contextual retrieval is simpler, cheaper, and easier to maintain -- it requires no graph construction, community detection, or graph database infrastructure. However, it does not enable cross-document reasoning or global sensemaking. It solves the "this chunk lost its context" problem but not the "how do these concepts relate across the corpus?" problem. The two approaches are complementary rather than competitive.

## 6. The "Lost in the Middle" Problem

Liu et al. (2024) demonstrated that LLMs exhibit a U-shaped attention curve: they attend strongly to tokens at the beginning and end of the context window but lose information placed in the middle, with performance dropping over 30% on multi-document QA tasks. This is caused by positional encoding biases, particularly in Rotary Position Embedding (RoPE) used by most modern architectures.

Graph structures help mitigate this in two ways. First, **pre-retrieval filtering**: by traversing a knowledge graph to select only the most structurally relevant context, graph-based systems send fewer, more targeted chunks to the LLM, reducing the volume of context where information can get lost. Second, **structured context assembly**: rather than dumping a flat list of chunks, graph-aware systems can organize retrieved information hierarchically -- entity first, then relationships, then supporting evidence -- placing the most important information at the edges of the context window. MIT and Google Cloud researchers have also proposed calibration mechanisms that disentangle relevance from position, though newer models like Gemini 2.5 Flash show substantially improved position-agnostic retrieval.

## 7. Documentation-Specific RAG Challenges

Different documentation types stress different parts of the retrieval pipeline.

**API references** are highly structured (method signatures, parameter tables, return types) but semantically sparse -- the embedding for `client.get(url, timeout=30)` carries little semantic signal. BM25 and keyword matching often outperform vector search here. Graph approaches help by modeling inheritance hierarchies and method-class relationships.

**Tutorials and guides** are narrative and sequential. Chunking destroys the step ordering. A chunk about "step 4: configure the middleware" is useless without steps 1-3. Hierarchical chunking (KohakuRAG, 2025) and parent-child document relationships address this.

**Conceptual documentation** ("how authentication works in our system") requires cross-document reasoning -- the answer spans architecture docs, API references, and configuration guides. This is precisely where graph-based approaches excel, connecting concepts across document boundaries.

**Code examples** present a unique challenge: code and prose have fundamentally different embedding characteristics. Systems like RAG for code documentation show that domain-specific embeddings and structure-aware parsing (AST-based chunking) significantly outperform generic approaches.

The emerging consensus in 2025-2026 is that no single retrieval strategy works for all documentation types. Production systems increasingly use **routing**: classifying the query type and dispatching to the appropriate retrieval strategy (vector search for conceptual queries, keyword/BM25 for API lookups, graph traversal for cross-cutting questions).

## Sources

- [The 2025 Guide to RAG - EdenAI](https://www.edenai.co/post/the-2025-guide-to-retrieval-augmented-generation-rag)
- [Deeper Insights into RAG: The Role of Sufficient Context - Google Research](https://research.google/blog/deeper-insights-into-retrieval-augmented-generation-the-role-of-sufficient-context/)
- [GraphRAG: From Local to Global (arXiv 2404.16130)](https://arxiv.org/abs/2404.16130)
- [GraphRAG: Unlocking LLM Discovery on Narrative Private Data - Microsoft Research](https://www.microsoft.com/en-us/research/blog/graphrag-unlocking-llm-discovery-on-narrative-private-data/)
- [GraphRAG Costs Explained - Azure AI Foundry Blog](https://techcommunity.microsoft.com/blog/azure-ai-foundry-blog/graphrag-costs-explained-what-you-need-to-know/4207978)
- [LazyGraphRAG: Setting a New Standard - Microsoft Research](https://www.microsoft.com/en-us/research/blog/lazygraphrag-setting-a-new-standard-for-quality-and-cost/)
- [KET-RAG (arXiv 2502.09304)](https://arxiv.org/html/2502.09304v2)
- [Hybrid Retrieval Architecture with Neo4j](https://markaicode.com/architecture/hybrid-retrieval-architecture-with-neo4j/)
- [TigerVector: Vector Search in Graph Databases (arXiv 2501.11216)](https://arxiv.org/html/2501.11216v1)
- [Graph RAG - Weaviate](https://weaviate.io/blog/graph-rag)
- [GraphRAG vs Vector RAG 2026](https://www.buildmvpfast.com/blog/graphrag-vs-vector-rag-knowledge-graph-ai-2026)
- [LlamaIndex Property Graph Index](https://www.llamaindex.ai/blog/introducing-the-property-graph-index-a-powerful-new-way-to-build-knowledge-graphs-with-llms)
- [LlamaIndex KnowledgeGraphRAGRetriever](https://developers.llamaindex.ai/python/framework-api-reference/retrievers/knowledge_graph/)
- [LlamaIndex GraphRAG v2 Cookbook](https://developers.llamaindex.ai/python/examples/cookbooks/graphrag_v2/)
- [Contextual Embeddings Guide - Anthropic Cookbook](https://platform.claude.com/cookbook/capabilities-contextual-embeddings-guide)
- [Contextual Retrieval - DataCamp Analysis](https://www.datacamp.com/tutorial/contextual-retrieval-anthropic)
- [Lost in the Middle: How Language Models Use Long Contexts (Liu et al. 2024)](https://www.researchgate.net/publication/378284067_Lost_in_the_Middle_How_Language_Models_Use_Long_Contexts)
- [Lost in the Middle - Morph Analysis](https://www.morphllm.com/lost-in-the-middle-llm)
- [Why Language Models Are Lost in the Middle - Towards AI](https://pub.towardsai.net/why-language-models-are-lost-in-the-middle-629b20d86152)
- [Solving the Lost in the Middle Problem - Maxim](https://www.getmaxim.ai/articles/solving-the-lost-in-the-middle-problem-advanced-rag-techniques-for-long-context-llms/)
- [KohakuRAG: Hierarchical Chunking (arXiv 2603.07612)](https://arxiv.org/pdf/2603.07612)
- [RAG for Code Documentation (arXiv 2404.00657)](https://arxiv.org/pdf/2404.00657)
