"""Tests for the Materializer module. See ARCHITECTURE.md §2.3."""

from datetime import datetime, timezone
from pathlib import Path

from context_kernel.graph.protocol import Entity, Neighbor, Relationship, SearchResult, Summary
from context_kernel.materializer import materialize_view
from context_kernel.materializer.views import render_view
from context_kernel.materializer import materialize
from context_kernel.materializer.headers import FreshnessHeader, parse, render
from context_kernel.materializer.pinned import extract, merge
from context_kernel.materializer.templates import render_agents_md, render_claude_md_bridge
from context_kernel.config_store import MaterializerConfig
from context_kernel.types import GraphCommit, Sha256, ScopePath, ViewSpec


class _FakeStore:
    """Minimal KnowledgeStore for testing materialize()."""

    def __init__(self, commit: str = "aabb", summary_md: str = "Test summary."):
        self._commit = commit
        self._summary_md = summary_md
        self._summaries: list[Summary] = []
        self._scope_entities: dict[ScopePath, list[Entity]] = {}

    def graph_commit(self) -> GraphCommit:
        return GraphCommit(self._commit)

    def get_entity(self, entity_id: str) -> Entity | None:
        return None

    def get_neighbors(self, entity_id: str) -> list[Neighbor]:
        return []

    def get_summary(self, scope: ScopePath) -> Summary | None:
        for s in self._summaries:
            if s.scope == scope:
                return s
        return Summary(scope=scope, digest=Sha256("ffee"), markdown=self._summary_md)

    def get_embedding(self, digest: Sha256) -> bytes | None:
        return None

    def search_similar(self, query_embedding, k, scope=None):
        return []

    def list_summaries(self) -> list[Summary]:
        return list(self._summaries)

    def list_entities_by_scope(self) -> dict[ScopePath, list[Entity]]:
        return dict(self._scope_entities)

    def upsert(self, graph_commit, entities, relationships, summaries, chunks=None, scope_entities=None) -> None:
        if summaries:
            self._summaries = list(summaries)
        if scope_entities:
            self._scope_entities = dict(scope_entities)


class TestFreshnessHeaderRoundTrip:
    def test_render_parse_roundtrip(self):
        header = FreshnessHeader(
            graph_commit=GraphCommit("7f3a4b2c" * 8),
            source_tree_hash=Sha256("2c4e8a1f" * 8),
            materialized_at=datetime(2026, 5, 24, 15, 30, 0, tzinfo=timezone.utc),
        )
        rendered = render(header)
        parsed = parse(rendered)
        assert parsed is not None
        assert parsed.graph_commit == header.graph_commit
        assert parsed.source_tree_hash == header.source_tree_hash

    def test_parse_returns_none_on_garbage(self):
        assert parse("no header here") is None

    def test_parse_returns_none_on_empty(self):
        assert parse("") is None

    def test_render_contains_sentinel(self):
        header = FreshnessHeader(
            graph_commit=GraphCommit("aabb"),
            source_tree_hash=Sha256("ccdd"),
            materialized_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        text = render(header)
        assert "context-kernel-freshness" in text

    def test_parse_with_body_after_header(self):
        header = FreshnessHeader(
            graph_commit=GraphCommit("aabb"),
            source_tree_hash=Sha256("ccdd"),
            materialized_at=datetime(2026, 5, 24, 12, 0, 0, tzinfo=timezone.utc),
        )
        text = render(header) + "\n\nSome body text here."
        parsed = parse(text)
        assert parsed is not None
        assert parsed.graph_commit == GraphCommit("aabb")


class TestPinnedBlocks:
    def test_extract_no_blocks(self):
        assert extract("no pinned blocks here") == []

    def test_extract_one_block(self):
        text = "before\n<!-- pinned -->\nmy content\n<!-- /pinned -->\nafter"
        blocks = extract(text)
        assert len(blocks) == 1
        assert "my content" in blocks[0]

    def test_extract_multiple_blocks(self):
        text = "<!-- pinned -->\nblock1\n<!-- /pinned -->\nmid\n<!-- pinned -->\nblock2\n<!-- /pinned -->"
        blocks = extract(text)
        assert len(blocks) == 2

    def test_merge_no_blocks_is_identity(self):
        rendered = "some rendered content"
        assert merge(rendered, []) == rendered

    def test_extract_then_merge_is_noop_on_unpinned(self):
        text = "just plain text with no pinned blocks"
        blocks = extract(text)
        result = merge(text, blocks)
        assert result == text


class TestTemplates:
    def test_render_claude_md_bridge(self):
        assert render_claude_md_bridge() == "@AGENTS.md\n"

    def test_render_agents_md_with_summary(self):
        header = FreshnessHeader(
            graph_commit=GraphCommit("aabb"),
            source_tree_hash=Sha256("ccdd"),
            materialized_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        summary = Summary(
            scope=ScopePath(Path("src/auth")),
            digest=Sha256("eeff"),
            markdown="The auth module handles sessions.",
        )
        result = render_agents_md(header, summary)
        assert "context-kernel-freshness" in result
        assert "The auth module handles sessions." in result

    def test_render_agents_md_without_summary(self):
        header = FreshnessHeader(
            graph_commit=GraphCommit("aabb"),
            source_tree_hash=Sha256("ccdd"),
            materialized_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        result = render_agents_md(header, None)
        assert "context-kernel-freshness" in result


class TestMaterializeIntegration:
    def test_returns_written_paths(self, tmp_path):
        scope = ScopePath(Path("src"))
        scope_dir = tmp_path / "src"
        scope_dir.mkdir()
        (scope_dir / "main.py").write_text("code")
        store = _FakeStore()
        written = materialize(scope, store, tmp_path, MaterializerConfig())
        assert len(written) == 2
        assert any(p.name == "AGENTS.md" for p in written)
        assert any(p.name == "CLAUDE.md" for p in written)

    def test_agents_md_has_header_and_body(self, tmp_path):
        scope = ScopePath(Path("src"))
        scope_dir = tmp_path / "src"
        scope_dir.mkdir()
        (scope_dir / "main.py").write_text("code")
        store = _FakeStore(summary_md="The src module does things.")
        materialize(scope, store, tmp_path, MaterializerConfig())
        text = (scope_dir / "AGENTS.md").read_text()
        assert "context-kernel-freshness" in text
        assert "The src module does things." in text

    def test_claude_md_is_bridge(self, tmp_path):
        scope = ScopePath(Path("src"))
        scope_dir = tmp_path / "src"
        scope_dir.mkdir()
        (scope_dir / "main.py").write_text("code")
        store = _FakeStore()
        materialize(scope, store, tmp_path, MaterializerConfig())
        assert (scope_dir / "CLAUDE.md").read_text() == "@AGENTS.md\n"

    def test_idempotent_returns_empty(self, tmp_path):
        scope = ScopePath(Path("src"))
        scope_dir = tmp_path / "src"
        scope_dir.mkdir()
        (scope_dir / "main.py").write_text("code")
        store = _FakeStore()
        config = MaterializerConfig()
        materialize(scope, store, tmp_path, config)
        second = materialize(scope, store, tmp_path, config)
        assert second == []


# ── View rendering (S6) ──────────────────────────────────────────────────


def _store_with_data() -> _FakeStore:
    store = _FakeStore()
    summaries = [
        Summary(scope=ScopePath(Path("src/auth")), digest=Sha256("aa"), markdown="Auth module handles sessions and tokens."),
        Summary(scope=ScopePath(Path("src/math")), digest=Sha256("bb"), markdown="Math utilities for numeric computation."),
        Summary(scope=ScopePath(Path("src/api")), digest=Sha256("cc"), markdown="REST API layer with auth middleware."),
    ]
    scope_entities = {
        ScopePath(Path("src/auth")): [
            Entity(id="e1", name="AuthService", kind="class", description="Handles session verification and token refresh."),
            Entity(id="e2", name="verify_token", kind="function", description="Validates JWT tokens against the store."),
        ],
        ScopePath(Path("src/math")): [
            Entity(id="e3", name="add", kind="function", description="Add two numbers."),
            Entity(id="e4", name="multiply", kind="function", description="Multiply two numbers."),
        ],
        ScopePath(Path("src/api")): [
            Entity(id="e5", name="Router", kind="class", description="Express-style route dispatcher."),
        ],
    }
    store.upsert(GraphCommit("aabb"), [], [], summaries, scope_entities=scope_entities)
    return store


class TestRenderViewIndex:
    def test_lists_all_scopes(self):
        store = _store_with_data()
        spec = ViewSpec(name="index", kind="index", params={})
        result = render_view(spec, store)
        assert "# Index" in result
        assert "src/auth" in result
        assert "src/math" in result
        assert "src/api" in result

    def test_includes_summaries(self):
        store = _store_with_data()
        spec = ViewSpec(name="index", kind="index", params={})
        result = render_view(spec, store)
        assert "Auth module handles sessions" in result
        assert "Math utilities" in result

    def test_includes_agents_md_paths(self):
        store = _store_with_data()
        spec = ViewSpec(name="index", kind="index", params={})
        result = render_view(spec, store)
        assert "src/auth/AGENTS.md" in result
        assert "src/math/AGENTS.md" in result

    def test_empty_store(self):
        store = _FakeStore()
        spec = ViewSpec(name="index", kind="index", params={})
        result = render_view(spec, store)
        assert "No scopes" in result


class TestRenderViewByTopic:
    def test_matches_entity_name(self):
        store = _store_with_data()
        spec = ViewSpec(name="by-topic", kind="by-topic", params={"tag": "auth"})
        result = render_view(spec, store)
        assert "AuthService" in result

    def test_matches_entity_description(self):
        store = _store_with_data()
        spec = ViewSpec(name="by-topic", kind="by-topic", params={"tag": "token"})
        result = render_view(spec, store)
        assert "verify_token" in result
        assert "AuthService" in result  # description mentions "token refresh"

    def test_case_insensitive(self):
        store = _store_with_data()
        spec = ViewSpec(name="by-topic", kind="by-topic", params={"tag": "AUTH"})
        result = render_view(spec, store)
        assert "AuthService" in result

    def test_excludes_non_matching_scopes(self):
        store = _store_with_data()
        spec = ViewSpec(name="by-topic", kind="by-topic", params={"tag": "auth"})
        result = render_view(spec, store)
        assert "src/math" not in result

    def test_includes_scope_with_matching_summary_only(self):
        store = _store_with_data()
        spec = ViewSpec(name="by-topic", kind="by-topic", params={"tag": "auth"})
        result = render_view(spec, store)
        assert "src/api" in result  # summary mentions "auth middleware"
        assert "REST API layer" in result  # fallback to summary text

    def test_groups_by_scope(self):
        store = _store_with_data()
        spec = ViewSpec(name="by-topic", kind="by-topic", params={"tag": "auth"})
        result = render_view(spec, store)
        assert "## src/auth" in result

    def test_includes_agents_md_links(self):
        store = _store_with_data()
        spec = ViewSpec(name="by-topic", kind="by-topic", params={"tag": "auth"})
        result = render_view(spec, store)
        assert "src/auth/AGENTS.md" in result

    def test_no_matches(self):
        store = _store_with_data()
        spec = ViewSpec(name="by-topic", kind="by-topic", params={"tag": "database"})
        result = render_view(spec, store)
        assert "No matches" in result

    def test_no_tag_configured(self):
        store = _store_with_data()
        spec = ViewSpec(name="by-topic", kind="by-topic", params={})
        result = render_view(spec, store)
        assert "No tag configured" in result

    def test_entity_kind_shown(self):
        store = _store_with_data()
        spec = ViewSpec(name="by-topic", kind="by-topic", params={"tag": "auth"})
        result = render_view(spec, store)
        assert "(class)" in result

    def test_multiple_kinds_when_matched(self):
        store = _store_with_data()
        spec = ViewSpec(name="by-topic", kind="by-topic", params={"tag": "token"})
        result = render_view(spec, store)
        assert "(class)" in result  # AuthService description mentions "token"
        assert "(function)" in result  # verify_token name matches


class TestMaterializeView:
    def test_writes_index_to_views_dir(self, tmp_path):
        store = _store_with_data()
        spec = ViewSpec(name="index", kind="index", params={})
        written = materialize_view(spec, store, tmp_path, MaterializerConfig())
        assert len(written) == 1
        assert written[0] == tmp_path / ".context-kernel" / "views" / "index.md"
        assert written[0].exists()

    def test_writes_by_topic_nested(self, tmp_path):
        store = _store_with_data()
        spec = ViewSpec(name="by-topic", kind="by-topic", params={"tag": "auth"})
        written = materialize_view(spec, store, tmp_path, MaterializerConfig())
        assert len(written) == 1
        assert written[0] == tmp_path / ".context-kernel" / "views" / "by-topic" / "auth.md"

    def test_view_has_freshness_header(self, tmp_path):
        store = _store_with_data()
        spec = ViewSpec(name="index", kind="index", params={})
        materialize_view(spec, store, tmp_path, MaterializerConfig())
        text = (tmp_path / ".context-kernel" / "views" / "index.md").read_text()
        assert "context-kernel-freshness" in text

    def test_view_has_sentinel_source_tree_hash(self, tmp_path):
        store = _store_with_data()
        spec = ViewSpec(name="index", kind="index", params={})
        materialize_view(spec, store, tmp_path, MaterializerConfig())
        text = (tmp_path / ".context-kernel" / "views" / "index.md").read_text()
        assert "0" * 64 in text

    def test_idempotent_skips_on_same_commit(self, tmp_path):
        store = _store_with_data()
        spec = ViewSpec(name="index", kind="index", params={})
        materialize_view(spec, store, tmp_path, MaterializerConfig())
        second = materialize_view(spec, store, tmp_path, MaterializerConfig())
        assert second == []

    def test_regenerates_on_new_commit(self, tmp_path):
        store = _store_with_data()
        spec = ViewSpec(name="index", kind="index", params={})
        materialize_view(spec, store, tmp_path, MaterializerConfig())
        store._commit = "ccdd"
        second = materialize_view(spec, store, tmp_path, MaterializerConfig())
        assert len(second) == 1


class TestIngestPersistsScopeEntities:
    def test_scope_entities_passed_to_store(self, tmp_path):
        from context_kernel.ingester import ingest
        from context_kernel.config_store import IngesterConfig
        (tmp_path / "svc.py").write_text("class Svc:\n    pass\n")
        store = _FakeStore()
        ingest(store, tmp_path, tmp_path, IngesterConfig())
        assert len(store._scope_entities) > 0
        for scope, entities in store._scope_entities.items():
            assert isinstance(scope, Path)
            assert len(entities) > 0
