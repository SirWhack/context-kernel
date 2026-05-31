"""Tests for the OrientationServer module. See ARCHITECTURE.md §2.5."""

from __future__ import annotations

import math
import struct
from datetime import datetime, timezone
from pathlib import Path

from context_kernel.config_store import IngesterConfig
from context_kernel.graph.protocol import (
    EmbeddedChunk, Entity, Neighbor, Relationship, SearchResult, Summary,
)
from context_kernel.ingester import ingest
from context_kernel.materializer.headers import FreshnessHeader, render
from context_kernel.orientation_server.tools import assemble, rank_by_relevance
from context_kernel.orientation_server.tools import find, overview
from context_kernel.scoring import ScoringConfig
from context_kernel.types import GraphCommit, Sha256, ScopePath


# ── Helpers ────────────────────────────────────────────────────────────


def _cosine_sim(a: bytes, b: bytes) -> float:
    n = len(a) // 4
    if n == 0 or len(b) // 4 != n:
        return 0.0
    af = struct.unpack(f"{n}f", a)
    bf = struct.unpack(f"{n}f", b)
    dot = sum(x * y for x, y in zip(af, bf))
    ma = math.sqrt(sum(x * x for x in af))
    mb = math.sqrt(sum(x * x for x in bf))
    if ma == 0 or mb == 0:
        return 0.0
    return dot / (ma * mb)


class _FakeStore:
    """KnowledgeStore with brute-force vector search for testing find()."""

    def __init__(self, commit="aabb", summary_md="Test summary."):
        self._commit = commit
        self._summary_md = summary_md
        self.chunks: list[EmbeddedChunk] = []

    def graph_commit(self):
        return GraphCommit(self._commit)

    def get_entity(self, entity_id):
        return None

    def get_neighbors(self, entity_id):
        return []

    def get_summary(self, scope):
        return Summary(scope=scope, digest=Sha256("ffee"), markdown=self._summary_md)

    def get_embedding(self, digest):
        return None

    def search_similar(self, query_embedding, k, scope=None):
        scored = []
        for c in self.chunks:
            if scope is not None and c.scope != scope:
                continue
            score = _cosine_sim(query_embedding, c.embedding)
            scored.append(SearchResult(
                chunk_text=c.chunk_text,
                source_path=c.source_path,
                score=score,
                kind=c.kind,
                scope=c.scope,
            ))
        scored.sort(key=lambda r: r.score, reverse=True)
        return scored[:k]

    def list_summaries(self):
        return []

    def list_entities_by_scope(self):
        return {}

    def upsert(self, graph_commit, entities, relationships, summaries, chunks=None, scope_entities=None):
        if chunks:
            self.chunks = list(chunks)


# ── Response assembly ──────────────────────────────────────────────────


class TestAssemble:
    def test_within_budget(self):
        result = assemble(["chunk one", "chunk two"], ["a.py", "b.py"], 4096)
        assert "chunk one" in result
        assert "chunk two" in result
        assert "a.py" in result

    def test_truncates_at_paragraph_boundary(self):
        long_chunk = "paragraph one\n\nparagraph two\n\nparagraph three"
        result = assemble([long_chunk], ["file.py"], 5)
        assert len(result) < len(long_chunk) + 50

    def test_empty_input(self):
        assert assemble([], [], 4096) == ""


# ── Overview ───────────────────────────────────────────────────────────


class TestOverview:
    def test_reads_agents_md(self, tmp_path):
        scope = ScopePath(Path("src"))
        scope_dir = tmp_path / "src"
        scope_dir.mkdir()
        header = FreshnessHeader(
            graph_commit=GraphCommit("aabb"),
            source_tree_hash=Sha256("ccdd"),
            materialized_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        agents = scope_dir / "AGENTS.md"
        agents.write_text(render(header) + "\n\nThe auth module handles sessions.\n")
        result = overview(scope, 4096, tmp_path)
        assert "The auth module handles sessions." in result
        assert "context-kernel-freshness" not in result

    def test_missing_agents_md(self, tmp_path):
        scope = ScopePath(Path("missing"))
        result = overview(scope, 4096, tmp_path)
        assert "No materialized overview" in result


# ── Relevance reranking (Slice 5) ──────────────────────────────────────


def _result(eid, score, confidence):
    return SearchResult(
        chunk_text=eid, source_path=f"{eid}.py", score=score, kind="entity",
        scope=ScopePath(Path(".")), entity_id=eid, confidence=confidence,
    )


class _RerankStore:
    """Minimal store exposing adjacency + entities for rank_by_relevance."""

    def __init__(self, neighbors=None, entities=None):
        self._neighbors = neighbors or {}
        self._entities = entities or {}

    def get_neighbors(self, eid):
        return self._neighbors.get(eid, [])

    def get_entity(self, eid):
        return self._entities.get(eid)


def _neighbor(target_id, kind):
    return Neighbor(
        entity=Entity(id=target_id, name=target_id, kind="class", description=""),
        relationship=Relationship(source_id="?", target_id=target_id, kind=kind, description=""),
    )


class TestRankByRelevance:
    def test_confidence_reweights_similarity(self):
        # A wins on similarity but is untrustworthy; B's confidence carries it past A.
        a = _result("A", score=0.9, confidence=0.2)   # 0.18
        b = _result("B", score=0.6, confidence=0.9)   # 0.54
        ranked = rank_by_relevance([a, b], _RerankStore(), ScoringConfig())
        assert [r.entity_id for r in ranked] == ["B", "A"]

    def test_proximity_lifts_seed_adjacent_hit(self):
        seed = _result("S", score=0.8, confidence=0.5)
        near = _result("N", score=0.5, confidence=0.5)
        far = _result("F", score=0.5, confidence=0.5)
        store = _RerankStore(neighbors={"S": [_neighbor("N", "realizes")]})
        ranked = rank_by_relevance([seed, near, far], store, ScoringConfig())
        assert ranked.index(near) < ranked.index(far)  # adjacency boost breaks the tie

    def test_unconnected_strong_hit_not_zeroed(self):
        strong = _result("X", score=0.95, confidence=0.85)  # unconnected
        weak = _result("Y", score=0.3, confidence=0.9)
        store = _RerankStore(neighbors={"Y": [_neighbor("Z", "governed-by")]})
        ranked = rank_by_relevance([strong, weak], store, ScoringConfig())
        assert ranked[0] is strong  # proximity is a boost, never a gate

    def test_centrality_off_by_default(self):
        plain = _result("P", score=0.5, confidence=0.5)     # 0.25
        central = _result("C", score=0.4, confidence=0.5)   # 0.20 unless centrality counts
        store = _RerankStore(entities={"C": Entity(
            id="C", name="C", kind="class", description="", centrality=1.0)})
        ranked = rank_by_relevance([plain, central], store, ScoringConfig())
        assert [r.entity_id for r in ranked] == ["P", "C"]

    def test_centrality_in_find_when_enabled(self):
        plain = _result("P", score=0.5, confidence=0.5)     # 0.25
        central = _result("C", score=0.4, confidence=0.5)   # 0.20 × (1+1.0) = 0.40
        store = _RerankStore(entities={"C": Entity(
            id="C", name="C", kind="class", description="", centrality=1.0)})
        cfg = ScoringConfig(centrality_in_find=True)
        ranked = rank_by_relevance([plain, central], store, cfg)
        assert [r.entity_id for r in ranked] == ["C", "P"]


class TestNeighborExpansion:
    """ADR-0023: find expands along edges, gated by edge_weight, capped, direct-hits win ties."""

    def test_pulls_in_missed_neighbor(self):
        # 'ADR' is connected to the strong seed via governed-by but was never retrieved.
        seed = _result("S", score=0.8, confidence=1.0)
        store = _RerankStore(neighbors={"S": [_neighbor("ADR", "governed-by")]})
        ranked = rank_by_relevance([seed], store, ScoringConfig())
        assert [r.entity_id for r in ranked] == ["S", "ADR"]  # neighbor now visible

    def test_edge_weight_gates_expansion(self):
        # Same seed, two neighbors: governed-by (0.95) clears the bar, imports (0.3) starves.
        seed = _result("S", score=0.8, confidence=1.0)        # find_score 0.8, threshold 0.4
        store = _RerankStore(neighbors={"S": [
            _neighbor("ADR", "governed-by"),   # 0.8×0.95×0.6 = 0.456 ≥ 0.4  → admitted
            _neighbor("DEP", "imports"),       # 0.8×0.30×0.6 = 0.144 < 0.4  → starved
        ]})
        ids = [r.entity_id for r in rank_by_relevance([seed], store, ScoringConfig())]
        assert "ADR" in ids and "DEP" not in ids

    def test_disabled_flag_is_noop(self):
        seed = _result("S", score=0.8, confidence=1.0)
        store = _RerankStore(neighbors={"S": [_neighbor("ADR", "governed-by")]})
        cfg = ScoringConfig(expansion_enabled=False)
        assert [r.entity_id for r in rank_by_relevance([seed], store, cfg)] == ["S"]

    def test_cap_limits_admitted_neighbors(self):
        seed = _result("S", score=0.9, confidence=1.0)
        store = _RerankStore(neighbors={"S": [
            _neighbor(f"N{i}", "governed-by") for i in range(10)
        ]})
        cfg = ScoringConfig(expansion_max=3)
        ranked = rank_by_relevance([seed], store, cfg)
        assert sum(1 for r in ranked if r.entity_id != "S") == 3

    def test_direct_hit_wins_tie(self):
        # T (direct) and the expanded neighbor land on the same score; direct must rank first.
        seed = _result("S", score=0.5, confidence=1.0)   # 0.50
        tee = _result("T", score=0.15, confidence=1.0)   # 0.15 (weakest direct → threshold 0.075)
        store = _RerankStore(neighbors={"S": [_neighbor("E", "motivates")]})  # 0.5×0.5×0.6 = 0.15
        ranked = rank_by_relevance([seed, tee], store, ScoringConfig())
        ids = [r.entity_id for r in ranked]
        assert ids.index("T") < ids.index("E")  # similarity-grounded beats inferred at a tie

    def test_already_present_neighbor_not_duplicated(self):
        seed = _result("S", score=0.8, confidence=1.0)
        near = _result("N", score=0.4, confidence=1.0)
        store = _RerankStore(neighbors={"S": [_neighbor("N", "realizes")]})
        ranked = rank_by_relevance([seed, near], store, ScoringConfig())
        assert [r.entity_id for r in ranked].count("N") == 1  # N is a direct hit, not re-added


# ── Find (unit — no embedder) ─────────────────────────────────────────


class TestFindNoEmbedder:
    def test_returns_error_without_embedder(self, tmp_path):
        scope = ScopePath(Path("src"))
        result = find("auth flow", scope, 4096, tmp_path, _FakeStore(), embedder=None)
        assert "not configured" in result.lower() or "unavailable" in result.lower()


# ── Find (integration — real embedder) ─────────────────────────────────


class TestFindIntegration:
    def test_returns_relevant_results(self, tmp_path, embedder):
        (tmp_path / "auth.py").write_text(
            "class AuthService:\n"
            "    def verify_token(self, token: str) -> bool:\n"
            "        pass\n"
            "    def refresh_session(self, session_id: str) -> None:\n"
            "        pass\n"
        )
        (tmp_path / "math_utils.py").write_text(
            "def add(a: int, b: int) -> int:\n"
            "    return a + b\n"
            "def multiply(a: int, b: int) -> int:\n"
            "    return a * b\n"
        )
        store = _FakeStore()
        ingest(store, tmp_path, tmp_path, IngesterConfig(), embedder=embedder)
        result = find(
            "authentication and session tokens",
            None, 4096, tmp_path, store, embedder,
        )
        assert "AuthService" in result or "auth" in result.lower()

    def test_respects_token_budget(self, tmp_path, embedder):
        (tmp_path / "big.py").write_text(
            "class Big:\n" + "".join(
                f"    def method_{i}(self) -> None:\n        pass\n"
                for i in range(20)
            )
        )
        store = _FakeStore()
        ingest(store, tmp_path, tmp_path, IngesterConfig(), embedder=embedder)
        result = find("methods", None, 50, tmp_path, store, embedder)
        assert len(result) <= 50 * 4 + 200  # budget + citation overhead

    def test_scope_filter(self, tmp_path, embedder):
        sub = tmp_path / "pkg"
        sub.mkdir()
        (tmp_path / "root.py").write_text("class Root:\n    pass\n")
        (sub / "child.py").write_text("class Child:\n    pass\n")
        store = _FakeStore()
        ingest(store, tmp_path, tmp_path, IngesterConfig(), embedder=embedder)
        result = find("class", ScopePath(Path("pkg")), 4096, tmp_path, store, embedder)
        assert "Child" in result
        assert "Root" not in result

    def test_no_scope_searches_all(self, tmp_path, embedder):
        sub = tmp_path / "pkg"
        sub.mkdir()
        (tmp_path / "root.py").write_text("class Root:\n    pass\n")
        (sub / "child.py").write_text("class Child:\n    pass\n")
        store = _FakeStore()
        ingest(store, tmp_path, tmp_path, IngesterConfig(), embedder=embedder)
        result = find("class", None, 4096, tmp_path, store, embedder)
        assert len(result) > 0

    def test_no_results_message(self, tmp_path, embedder):
        store = _FakeStore()
        result = find("nonexistent xyz", None, 4096, tmp_path, store, embedder)
        assert "no results" in result.lower()

    def test_hybrid_returns_both_kinds(self, tmp_path, embedder):
        (tmp_path / "svc.py").write_text(
            "class Svc:\n"
            "    def run(self) -> None:\n"
            "        pass\n"
        )
        store = _FakeStore()
        ingest(store, tmp_path, tmp_path, IngesterConfig(), embedder=embedder)
        kinds = {c.kind for c in store.chunks}
        assert "entity" in kinds
        assert "summary" in kinds


class _ConstEmbedder:
    """Deterministic embedder for unit tests — fixed vector, no llama-server needed."""

    def embed(self, text, *, mode="passage"):
        return struct.pack("3f", 1.0, 0.0, 0.0)

    def embed_batch(self, texts, *, mode="passage"):
        return [self.embed(t, mode=mode) for t in texts]


class TestFindScopeFallback:
    """find() must not silently return empty when a scope matches no chunk — it falls back
    to the whole corpus and says so (eval finding 2026-05-30)."""

    def _store(self):
        store = _FakeStore()
        emb = struct.pack("3f", 1.0, 0.0, 0.0)
        store.upsert(GraphCommit("c1"), [], [], [], [
            EmbeddedChunk(id="x", embedding=emb, chunk_text="JWT auth lives here",
                          scope=ScopePath(Path("backend/auth")),
                          source_path="backend/auth/security.py", kind="entity"),
        ])
        return store

    def test_unmatched_scope_falls_back_to_whole_corpus(self, tmp_path):
        out = find("jwt auth", ScopePath(Path("frontend/nope")), 4096, tmp_path,
                   self._store(), _ConstEmbedder())
        assert "security.py" in out
        assert "whole portfolio" in out.lower()

    def test_matched_scope_has_no_fallback_note(self, tmp_path):
        out = find("jwt auth", ScopePath(Path("backend/auth")), 4096, tmp_path,
                   self._store(), _ConstEmbedder())
        assert "security.py" in out
        assert "whole portfolio" not in out.lower()

    def test_truly_empty_corpus_still_reports_no_results(self, tmp_path):
        out = find("jwt auth", ScopePath(Path("backend/auth")), 4096, tmp_path,
                   _FakeStore(), _ConstEmbedder())
        assert "no results" in out.lower()
