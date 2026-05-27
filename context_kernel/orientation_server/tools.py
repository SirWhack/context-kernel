"""MCP tools: overview(scope_path, max_tokens), find(query, scope_path). See ARCHITECTURE.md §2.5."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from context_kernel.graph.protocol import KnowledgeStore, SearchResult
from context_kernel.materializer.headers import parse
from context_kernel.types import ScopePath

if TYPE_CHECKING:
    from context_kernel.ingester.embedder import Embedder

log = logging.getLogger(__name__)

_CHARS_PER_TOKEN = 4


def nearest_chunks(
    query: str,
    store: KnowledgeStore,
    embedder: "Embedder",
    k: int,
    scope: ScopePath | None = None,
) -> list[SearchResult]:
    """Embed the query and return top-k results by similarity from the hybrid corpus."""
    query_embedding = embedder.embed(query, mode="query")
    return store.search_similar(query_embedding, k, scope)


def assemble(chunks: list[str], source_paths: list[str], max_tokens: int) -> str:
    """Concatenate chunks with file-path citations, enforcing the token budget."""
    budget = max_tokens * _CHARS_PER_TOKEN
    parts: list[str] = []
    used = 0
    for chunk, path in zip(chunks, source_paths):
        citation = f"\n\n> Source: `{path}`\n"
        entry = chunk + citation
        if used + len(entry) > budget and parts:
            break
        parts.append(entry)
        used += len(entry)
    result = "\n".join(parts)
    if used > budget:
        cut = result[:budget]
        para = cut.rfind("\n\n")
        if para > budget // 2:
            result = cut[:para]
    return result


def overview(scope: ScopePath, max_tokens: int, tree_root: Path) -> str:
    """Return a markdown overview of this scope, capped by max_tokens. Cites source file paths."""
    agents_path = tree_root / scope / "AGENTS.md"
    if not agents_path.exists():
        return f"No materialized overview for scope `{scope}`."
    text = agents_path.read_text(encoding="utf-8")
    header = parse(text)
    if header:
        end = text.find("-->")
        if end != -1:
            text = text[end + 3:].lstrip("\n")
    budget = max_tokens * _CHARS_PER_TOKEN
    if len(text) <= budget:
        return text
    cut = text[:budget]
    para = cut.rfind("\n\n")
    if para > budget // 2:
        return cut[:para]
    return cut


def find(
    query: str,
    scope: ScopePath | None,
    max_tokens: int,
    tree_root: Path,
    store: KnowledgeStore,
    embedder: "Embedder | None",
) -> str:
    """Embedding-similarity search over the hybrid corpus. Per ADR-0012."""
    if embedder is None:
        return (
            "Embedding service not configured. "
            "Use `overview` for scope-level orientation."
        )

    try:
        results = nearest_chunks(query, store, embedder, k=10, scope=scope)
    except Exception as exc:
        log.warning("find: embedding failed: %s", exc)
        return (
            f"Embedding service unavailable: {exc}. "
            "Start the embedder server and retry, or use `overview` for scope-level orientation."
        )

    if not results:
        scope_msg = f" in scope `{scope}`" if scope else ""
        return f"No results found for query: \"{query}\"{scope_msg}."

    chunks = [r.chunk_text for r in results]
    paths = [r.source_path for r in results]
    return assemble(chunks, paths, max_tokens)
