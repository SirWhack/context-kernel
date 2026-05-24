"""Tests for the OrientationServer module. See ARCHITECTURE.md §2.5."""

from datetime import datetime, timezone
from pathlib import Path

from context_kernel.materializer.headers import FreshnessHeader, render
from context_kernel.orientation_server.response import assemble
from context_kernel.orientation_server.tools import find, overview
from context_kernel.types import GraphCommit, Sha256, ScopePath


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


class TestFind:
    def test_returns_stub(self, tmp_path):
        scope = ScopePath(Path("src"))
        result = find("auth flow", scope, tmp_path)
        assert "stub" in result.lower() or "S1" in result
