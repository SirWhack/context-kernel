"""Tests for the FreshnessGate module. See ARCHITECTURE.md §2.4."""

import logging
from datetime import datetime, timezone
from pathlib import Path

from context_kernel.config_store import IngesterConfig, MaterializerConfig, Config, OrientationConfig
from context_kernel.freshness_gate import StaleReadError, check
from context_kernel.graph.protocol import Entity, Relationship, Summary, EmbeddedChunk, SearchResult
from context_kernel.materializer import materialize
from context_kernel.materializer.headers import FreshnessHeader, render
from context_kernel.types import GraphCommit, Sha256, ScopePath


class _FakeStore:
    def __init__(self, commit="aabb1122"):
        self._commit = commit
        self._summary_md = "Test scope summary."

    def graph_commit(self) -> GraphCommit:
        return GraphCommit(self._commit)

    def get_summary(self, scope: ScopePath) -> Summary | None:
        return Summary(scope=scope, digest=Sha256("d" * 64), markdown=self._summary_md)

    def get_entity(self, entity_id: str):
        return None

    def get_neighbors(self, entity_id: str):
        return []

    def get_embedding(self, digest):
        return None

    def search_similar(self, query_embedding, k, scope=None):
        return []

    def list_summaries(self):
        return []

    def list_entities_by_scope(self):
        return {}

    def upsert(self, graph_commit, entities, relationships, summaries, chunks=None, scope_entities=None):
        self._commit = str(graph_commit)


class TestFreshnessLogging:
    def _setup_scope(self, tmp_path):
        scope_dir = tmp_path / "src"
        scope_dir.mkdir()
        (scope_dir / "app.py").write_text("class App:\n    pass\n")
        store = _FakeStore()
        materialize(ScopePath(Path("src")), store, tmp_path, MaterializerConfig())
        return scope_dir, store

    def test_logs_hit(self, tmp_path, caplog):
        scope_dir, store = self._setup_scope(tmp_path)
        agents_path = scope_dir / "AGENTS.md"
        with caplog.at_level(logging.INFO, logger="context_kernel.freshness_gate"):
            check(agents_path, store, tmp_path)
        hit_records = [r for r in caplog.records if "freshness hit" in r.getMessage()]
        assert len(hit_records) == 1
        assert hit_records[0].scope == "src"
        assert hit_records[0].graph_commit == "aabb1122"

    def test_logs_miss_graph_stale(self, tmp_path, caplog):
        scope_dir, store = self._setup_scope(tmp_path)
        agents_path = scope_dir / "AGENTS.md"
        store._commit = "newcommit"
        with caplog.at_level(logging.INFO, logger="context_kernel.freshness_gate"):
            check(agents_path, store, tmp_path)
        miss_records = [r for r in caplog.records if "freshness miss" in r.getMessage()]
        assert len(miss_records) == 1
        rec = miss_records[0]
        assert rec.stale_graph_commit == "aabb1122"
        assert rec.current_graph_commit == "newcommit"

    def test_logs_miss_source_tree_stale(self, tmp_path, caplog):
        scope_dir, store = self._setup_scope(tmp_path)
        agents_path = scope_dir / "AGENTS.md"
        (scope_dir / "new_file.py").write_text("class New:\n    pass\n")
        with caplog.at_level(logging.INFO, logger="context_kernel.freshness_gate"):
            check(agents_path, store, tmp_path)
        miss_records = [r for r in caplog.records if "freshness miss" in r.getMessage()]
        assert len(miss_records) == 1
        assert miss_records[0].source_tree_stale is True

    def test_logs_miss_no_existing_file(self, tmp_path, caplog):
        scope_dir = tmp_path / "empty"
        scope_dir.mkdir()
        (scope_dir / "app.py").write_text("x = 1\n")
        agents_path = scope_dir / "AGENTS.md"
        store = _FakeStore()
        with caplog.at_level(logging.INFO, logger="context_kernel.freshness_gate"):
            check(agents_path, store, tmp_path)
        miss_records = [r for r in caplog.records if "freshness miss" in r.getMessage()]
        assert len(miss_records) == 1
        assert miss_records[0].stale_graph_commit is None
