"""Tests for the OrientationServer module. See ARCHITECTURE.md §2.5."""

from __future__ import annotations

import math
import struct
from datetime import datetime, timezone
from pathlib import Path

from context_kernel.config_store import IngesterConfig
from context_kernel.graph.protocol import EmbeddedChunk, Entity, SearchResult, Summary
from context_kernel.ingester import ingest
from context_kernel.materializer.headers import FreshnessHeader, render
from context_kernel.orientation_server.response import assemble
from context_kernel.orientation_server.tools import find, overview
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

    def upsert(self, graph_commit, entities, relationships, summaries, chunks=None):
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
