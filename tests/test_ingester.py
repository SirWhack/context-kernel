"""Tests for the Ingester module. See ARCHITECTURE.md §2.2."""

from pathlib import Path

from context_kernel.graph.addressing import hash_bytes
from context_kernel.ingester.blobs import write_embedding, write_summary
from context_kernel.ingester.change_detection import (
    changed_since,
    discover_scopes,
    source_tree_hash,
    walk_source_files,
)
from context_kernel.ingester.handlers import MarkdownHandler
from context_kernel.types import GraphCommit


class TestMarkdownHandler:
    def test_supports_md(self, tmp_path):
        h = MarkdownHandler()
        assert h.supports(tmp_path / "README.md")
        assert h.supports(tmp_path / "notes.markdown")

    def test_rejects_non_md(self, tmp_path):
        h = MarkdownHandler()
        assert not h.supports(tmp_path / "main.py")
        assert not h.supports(tmp_path / "style.css")

    def test_chunks_small_file(self, tmp_path):
        f = tmp_path / "small.md"
        f.write_text("# Hello\n\nShort content.")
        h = MarkdownHandler()
        chunks = h.chunks(f)
        assert len(chunks) == 1
        assert "Hello" in chunks[0]

    def test_chunks_empty_file(self, tmp_path):
        f = tmp_path / "empty.md"
        f.write_text("")
        h = MarkdownHandler()
        assert h.chunks(f) == []

    def test_chunks_large_file(self, tmp_path):
        f = tmp_path / "big.md"
        f.write_text("word " * 1000)
        h = MarkdownHandler()
        chunks = h.chunks(f)
        assert len(chunks) > 1


class TestChangeDetection:
    def test_changed_since_none_returns_all(self, tmp_path):
        (tmp_path / "a.md").write_text("hello")
        (tmp_path / "b.md").write_text("world")
        result = changed_since(tmp_path, None)
        assert len(result) == 2

    def test_changed_since_unchanged_tree(self, tmp_path):
        (tmp_path / "a.md").write_text("hello")
        current_hash = source_tree_hash(tmp_path, tmp_path)
        result = changed_since(tmp_path, GraphCommit(current_hash))
        assert result == []

    def test_walk_excludes_git(self, tmp_path):
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        (git_dir / "config").write_text("gitconfig")
        (tmp_path / "README.md").write_text("hello")
        files = walk_source_files(tmp_path)
        assert len(files) == 1
        assert files[0].name == "README.md"

    def test_walk_excludes_context_kernel(self, tmp_path):
        ck = tmp_path / ".context-kernel"
        ck.mkdir()
        (ck / "log.md").write_text("log")
        (tmp_path / "src.md").write_text("source")
        files = walk_source_files(tmp_path)
        assert all(".context-kernel" not in str(f) for f in files)

    def test_walk_excludes_node_modules(self, tmp_path):
        nm = tmp_path / "node_modules" / "pkg"
        nm.mkdir(parents=True)
        (nm / "index.js").write_text("module")
        (tmp_path / "app.md").write_text("app")
        files = walk_source_files(tmp_path)
        assert len(files) == 1

    def test_discover_scopes(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        (src / "main.py").write_text("code")
        (tmp_path / "README.md").write_text("readme")
        scopes = discover_scopes(tmp_path)
        scope_strs = [str(s) for s in scopes]
        assert "." in scope_strs
        assert "src" in scope_strs

    def test_source_tree_hash_deterministic(self, tmp_path):
        (tmp_path / "a.md").write_text("hello")
        h1 = source_tree_hash(tmp_path, tmp_path)
        h2 = source_tree_hash(tmp_path, tmp_path)
        assert h1 == h2

    def test_source_tree_hash_changes_on_edit(self, tmp_path):
        f = tmp_path / "a.md"
        f.write_text("version1")
        h1 = source_tree_hash(tmp_path, tmp_path)
        f.write_text("version2")
        h2 = source_tree_hash(tmp_path, tmp_path)
        assert h1 != h2


class TestBlobs:
    def test_write_embedding_roundtrip(self, tmp_path):
        content = b"\x00\x01\x02\x03" * 256
        digest = write_embedding(tmp_path, content)
        assert len(digest) == 64
        blob = tmp_path / ".context-kernel" / "embeddings" / f"{digest}.bin"
        assert blob.exists()
        assert blob.read_bytes() == content

    def test_write_summary_roundtrip(self, tmp_path):
        md = "# Summary\n\nThis scope handles auth."
        digest = write_summary(tmp_path, md)
        blob = tmp_path / ".context-kernel" / "summaries" / f"{digest}.md"
        assert blob.exists()
        assert blob.read_text() == md

    def test_content_addressing(self, tmp_path):
        d1 = write_summary(tmp_path, "same content")
        d2 = write_summary(tmp_path, "same content")
        assert d1 == d2
        d3 = write_summary(tmp_path, "different content")
        assert d1 != d3
