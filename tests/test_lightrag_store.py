"""Tests for LightRAGStore — the production KnowledgeStore implementation."""

from pathlib import Path

import pytest

from context_kernel.graph.lightrag_adapter import LightRAGStore
from context_kernel.graph.protocol import Entity, Relationship, Summary, EmbeddedChunk
from context_kernel.types import GraphCommit, Sha256, ScopePath


def _entity(id: str, name: str, kind: str = "module", desc: str = "desc") -> Entity:
    return Entity(id=id, name=name, kind=kind, description=desc)


def _rel(src: str, tgt: str, kind: str = "depends_on", desc: str = "") -> Relationship:
    return Relationship(source_id=src, target_id=tgt, kind=kind, description=desc)


def _summary(scope: str, text: str = "summary") -> Summary:
    return Summary(scope=ScopePath(Path(scope)), digest=Sha256("abc"), markdown=text)


class TestUpsert:
    def test_entities_are_idempotent(self, tmp_path):
        store = LightRAGStore(tmp_path / "graph")
        e = _entity("e1", "Foo")
        commit = GraphCommit("c1")
        store.upsert(commit, [e], [], [])
        store.upsert(commit, [e], [], [])
        assert len(store.list_entities_by_scope()) == 0  # no scope_entities passed
        assert store.get_entity("e1") == e

    def test_relationships_are_deduplicated(self, tmp_path):
        store = LightRAGStore(tmp_path / "graph")
        e1, e2 = _entity("e1", "A"), _entity("e2", "B")
        r = _rel("e1", "e2")
        commit = GraphCommit("c1")
        store.upsert(commit, [e1, e2], [r], [])
        store.upsert(commit, [e1, e2], [r], [])
        neighbors = store.get_neighbors("e1")
        assert len(neighbors) == 1

    def test_different_kind_relationships_kept(self, tmp_path):
        store = LightRAGStore(tmp_path / "graph")
        e1, e2 = _entity("e1", "A"), _entity("e2", "B")
        r1 = _rel("e1", "e2", kind="depends_on")
        r2 = _rel("e1", "e2", kind="implements")
        commit = GraphCommit("c1")
        store.upsert(commit, [e1, e2], [r1, r2], [])
        neighbors = store.get_neighbors("e1")
        assert len(neighbors) == 2

    def test_chunks_are_deduplicated(self, tmp_path):
        import struct
        emb = struct.pack("f", 1.0)
        store = LightRAGStore(tmp_path / "graph")
        chunk = EmbeddedChunk(
            id="ch1", embedding=emb, chunk_text="text",
            source_path="a.py", kind="entity", scope=ScopePath(Path(".")),
        )
        commit = GraphCommit("c1")
        store.upsert(commit, [], [], [], [chunk])
        store.upsert(commit, [], [], [], [chunk])
        results = store.search_similar(emb, 10)
        assert len(results) == 1


class TestGetNeighbors:
    def test_returns_related_entities(self, tmp_path):
        store = LightRAGStore(tmp_path / "graph")
        e1, e2 = _entity("e1", "A"), _entity("e2", "B")
        r = _rel("e1", "e2", desc="uses")
        store.upsert(GraphCommit("c1"), [e1, e2], [r], [])
        neighbors = store.get_neighbors("e1")
        assert len(neighbors) == 1
        assert neighbors[0].entity == e2
        assert neighbors[0].relationship == r

    def test_bidirectional(self, tmp_path):
        store = LightRAGStore(tmp_path / "graph")
        e1, e2 = _entity("e1", "A"), _entity("e2", "B")
        r = _rel("e1", "e2")
        store.upsert(GraphCommit("c1"), [e1, e2], [r], [])
        assert len(store.get_neighbors("e2")) == 1


class TestPersistence:
    def test_round_trip(self, tmp_path):
        graph_dir = tmp_path / "graph"
        store = LightRAGStore(graph_dir)
        e1, e2 = _entity("e1", "A"), _entity("e2", "B")
        r = _rel("e1", "e2")
        s = _summary("proj", "A project summary")
        store.upsert(GraphCommit("c1"), [e1, e2], [r], [s])

        store2 = LightRAGStore(graph_dir)
        assert store2.graph_commit() == GraphCommit("c1")
        assert store2.get_entity("e1") == e1
        assert len(store2.get_neighbors("e1")) == 1
        assert store2.get_summary(ScopePath(Path("proj"))).markdown == "A project summary"

    def test_dedup_on_load(self, tmp_path):
        """Existing corrupt state with duplicate relationships is cleaned on load."""
        graph_dir = tmp_path / "graph"
        store = LightRAGStore(graph_dir)
        e1, e2 = _entity("e1", "A"), _entity("e2", "B")
        r = _rel("e1", "e2")
        store.upsert(GraphCommit("c1"), [e1, e2], [r], [])

        # Corrupt: manually inject a duplicate relationship into state.json
        import json
        state_path = graph_dir / "state.json"
        raw = json.loads(state_path.read_text())
        raw["relationships"].append(raw["relationships"][0])
        state_path.write_text(json.dumps(raw))

        store2 = LightRAGStore(graph_dir)
        assert len(store2.get_neighbors("e1")) == 1


class TestScoringFieldsPersistence:
    """Slice 1 (ADR-0015/0020): scoring axes round-trip; legacy state loads neutral."""

    def test_scoring_fields_round_trip(self, tmp_path):
        graph_dir = tmp_path / "graph"
        store = LightRAGStore(graph_dir)
        e = Entity(
            id="e1", name="A", kind="module", description="d",
            source_tier=0.9, centrality=0.42, confidence=0.81,
        )
        r = Relationship(
            source_id="e1", target_id="e2", kind="realizes", description="",
            weight=0.9, drift=0.7,
        )
        e2 = _entity("e2", "B")
        store.upsert(GraphCommit("c1"), [e, e2], [r], [])

        reloaded = LightRAGStore(graph_dir)
        got = reloaded.get_entity("e1")
        assert (got.source_tier, got.centrality, got.confidence) == (0.9, 0.42, 0.81)
        rel = reloaded.get_neighbors("e1")[0].relationship
        assert (rel.weight, rel.drift) == (0.9, 0.7)

    def test_legacy_state_without_scoring_fields_loads_neutral(self, tmp_path):
        """An old state.json predating the scoring fields loads with neutral defaults."""
        graph_dir = tmp_path / "graph"
        store = LightRAGStore(graph_dir)
        store.upsert(GraphCommit("c1"), [_entity("e1", "A"), _entity("e2", "B")], [_rel("e1", "e2")], [])

        import json
        state_path = graph_dir / "state.json"
        raw = json.loads(state_path.read_text())
        for e in raw["entities"]:
            e.pop("source_tier", None); e.pop("centrality", None); e.pop("confidence", None)
        for r in raw["relationships"]:
            r.pop("weight", None); r.pop("drift", None)
        state_path.write_text(json.dumps(raw))

        reloaded = LightRAGStore(graph_dir)
        got = reloaded.get_entity("e1")
        assert (got.source_tier, got.centrality, got.confidence) == (0.0, 0.0, 1.0)
        rel = reloaded.get_neighbors("e1")[0].relationship
        assert (rel.weight, rel.drift) == (0.5, 0.0)


class TestGraphCommit:
    def test_commit_tracks_latest(self, tmp_path):
        store = LightRAGStore(tmp_path / "graph")
        store.upsert(GraphCommit("c1"), [], [], [])
        assert store.graph_commit() == GraphCommit("c1")
        store.upsert(GraphCommit("c2"), [], [], [])
        assert store.graph_commit() == GraphCommit("c2")


class TestScopeFilter:
    """search_similar scope handling — normalize repo-name/absolute scopes to the stored
    portfolio-relative form, and treat a scope as a subtree (prefix). Regression for the
    eval finding where `find(scope='open-webui')` silently returned zero results."""

    def _store(self, tmp_path):
        import struct
        portfolio = tmp_path / "myrepo"
        store = LightRAGStore(portfolio / ".context-kernel" / "graph")
        emb = struct.pack("3f", 1.0, 0.0, 0.0)
        chunks = [
            EmbeddedChunk(id="a", embedding=emb, chunk_text="api", scope=ScopePath(Path("backend/app/api")), source_path="backend/app/api/routes.py", kind="entity"),
            EmbeddedChunk(id="b", embedding=emb, chunk_text="core", scope=ScopePath(Path("backend/app/core")), source_path="backend/app/core/db.py", kind="entity"),
            EmbeddedChunk(id="c", embedding=emb, chunk_text="fe", scope=ScopePath(Path("frontend/src")), source_path="frontend/src/main.ts", kind="entity"),
        ]
        store.upsert(GraphCommit("c1"), [], [], [], chunks)
        return store, portfolio, emb

    def test_none_scope_searches_whole_corpus(self, tmp_path):
        store, _, emb = self._store(tmp_path)
        assert len(store.search_similar(emb, 10)) == 3

    def test_exact_scope_excludes_subdirs_of_siblings(self, tmp_path):
        store, _, emb = self._store(tmp_path)
        r = store.search_similar(emb, 10, ScopePath(Path("backend/app/api")))
        assert {x.source_path for x in r} == {"backend/app/api/routes.py"}

    def test_scope_is_a_subtree_prefix(self, tmp_path):
        store, _, emb = self._store(tmp_path)
        r = store.search_similar(emb, 10, ScopePath(Path("backend")))
        assert {x.source_path for x in r} == {"backend/app/api/routes.py", "backend/app/core/db.py"}

    def test_repo_name_means_whole_corpus(self, tmp_path):
        store, _, emb = self._store(tmp_path)
        assert len(store.search_similar(emb, 10, ScopePath(Path("myrepo")))) == 3

    def test_dot_means_whole_corpus(self, tmp_path):
        store, _, emb = self._store(tmp_path)
        assert len(store.search_similar(emb, 10, ScopePath(Path(".")))) == 3

    def test_absolute_path_is_normalized(self, tmp_path):
        store, portfolio, emb = self._store(tmp_path)
        r = store.search_similar(emb, 10, ScopePath(portfolio / "backend" / "app" / "core"))
        assert {x.source_path for x in r} == {"backend/app/core/db.py"}

    def test_unknown_scope_returns_empty(self, tmp_path):
        store, _, emb = self._store(tmp_path)
        assert store.search_similar(emb, 10, ScopePath(Path("does/not/exist"))) == []
