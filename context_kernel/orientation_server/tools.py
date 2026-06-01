"""MCP tools: overview(scope_path, max_tokens), find(query, scope_path). See ARCHITECTURE.md §2.5."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

from context_kernel import scoring
from context_kernel.graph.protocol import KnowledgeStore, SearchResult
from context_kernel.materializer.headers import parse
from context_kernel.scoring import ScoringConfig
from context_kernel.source_kinds import CODE_EXT
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


def rank_by_relevance(
    results: list[SearchResult],
    store: KnowledgeStore,
    cfg: ScoringConfig,
) -> list[SearchResult]:
    """Rerank similarity hits by relevance, then expand along graph edges (ADR-0015/0023).

    The top-3 similarity hits seed proximity (a free-text query has no seed entities). Each
    candidate is boosted by its 1-hop adjacency to a seed; proximity is a boost (≥ 1), never
    a gate, so an unconnected strong hit is never zeroed. Centrality stays out of the score
    by default — a query wants *relevant*, not merely *central*, results.

    Then (ADR-0023) the candidate set is *expanded*: a strong seed's graph neighbors are pulled
    in even if the vector search missed them, scored by relevance flowing along the edge. A
    direct (similarity-grounded) hit always wins a tie against an expanded (inferred) one.
    """
    seeds = [r.entity_id for r in results[:3] if r.entity_id]
    adjacency = {
        sid: [(n.entity.id, n.relationship.kind) for n in store.get_neighbors(sid)]
        for sid in seeds
    }

    def _score(r: SearchResult) -> float:
        prox = scoring.proximity(r.entity_id, seeds, adjacency, cfg) if r.entity_id else 1.0
        s = scoring.find_score(r.score, r.confidence, prox)
        if cfg.centrality_in_find and r.entity_id:
            ent = store.get_entity(r.entity_id)
            if ent is not None:
                s *= 1.0 + ent.centrality
        return s

    # (score, is_direct, result) — is_direct breaks ties in favor of similarity-grounded hits.
    scored = [(_score(r), True, r) for r in results]
    if cfg.expansion_enabled and scored:
        scored += _expand_neighbors(scored, store, cfg)
    scored.sort(key=lambda t: (t[0], t[1]), reverse=True)
    return [r for _, _, r in scored]


def _expand_neighbors(
    direct_scored: list[tuple[float, bool, SearchResult]],
    store: KnowledgeStore,
    cfg: ScoringConfig,
) -> list[tuple[float, bool, SearchResult]]:
    """Pull 1-hop neighbors of the top seeds into the candidate set (ADR-0023).

    A neighbor's score is `expansion_score(seed_score, edge_kind, neighbor_confidence)` — no
    kind allowlist; `edge_weight` is the gate. Admitted only if it clears
    `min_ratio × weakest_direct_hit`, capped at `expansion_max`. Returns new (score, False,
    result) tuples to merge into the direct set.
    """
    seeds = [(s, r) for s, _, r in sorted(direct_scored, reverse=True, key=lambda t: t[0])
             if r.entity_id][:3]
    if not seeds:
        return []
    present = {r.entity_id for _, _, r in direct_scored if r.entity_id}
    weakest = min(s for s, _, _ in direct_scored)
    threshold = cfg.expansion_min_ratio * weakest

    best: dict[str, tuple[float, object]] = {}  # neighbor_id -> (score, Neighbor)
    for seed_score, seed_r in seeds:
        for nb in store.get_neighbors(seed_r.entity_id):
            nid = nb.entity.id
            if nid in present:
                continue
            sc = scoring.expansion_score(seed_score, nb.relationship.kind, nb.entity.confidence, cfg)
            if sc < threshold:
                continue
            if nid not in best or sc > best[nid][0]:
                best[nid] = (sc, nb)

    admitted = sorted(best.values(), key=lambda t: t[0], reverse=True)[: cfg.expansion_max]
    out: list[tuple[float, bool, SearchResult]] = []
    for sc, nb in admitted:
        ent = nb.entity
        src = next((s for s in ent.sources if s.endswith(CODE_EXT)),
                   ent.sources[0] if ent.sources else "")
        out.append((sc, False, SearchResult(
            chunk_text=ent.description,
            source_path=src,
            score=sc,
            kind="entity",
            scope=ScopePath(Path(src).parent) if src else ScopePath(Path(".")),
            entity_id=ent.id,
            confidence=ent.confidence,
        )))
    return out


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

    # A scope that indexes nothing must not read as "nothing relevant" — fall back to the
    # whole corpus and say so, rather than silently returning empty (eval finding 2026-05-30).
    note = ""
    if not results and scope is not None:
        try:
            results = nearest_chunks(query, store, embedder, k=10, scope=None)
        except Exception:
            results = []
        if results:
            note = (f"_No indexed content under scope `{scope}`; searched the whole "
                    f"portfolio instead._\n\n")

    if not results:
        scope_msg = f" in scope `{scope}`" if scope else ""
        return f"No results found for query: \"{query}\"{scope_msg}."

    # Compose relevance from the pre-materialized confidence + graph adjacency (ADR-0019:
    # store is the similarity mechanism, find is the policy composer). Query-time knobs
    # come from CK_SCORING_* env (the highest-precedence layer).
    cfg = ScoringConfig.resolve(env=os.environ)
    results = rank_by_relevance(results, store, cfg)

    chunks = [r.chunk_text for r in results]
    paths = [r.source_path for r in results]
    return note + assemble(chunks, paths, max_tokens)
