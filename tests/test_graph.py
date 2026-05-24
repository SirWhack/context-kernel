"""Tests for the Graph module. See ARCHITECTURE.md §2.1."""

from pathlib import Path

from context_kernel.graph.addressing import blob_path, hash_bytes
from context_kernel.types import Sha256


class TestHashBytes:
    def test_deterministic(self):
        assert hash_bytes(b"hello") == hash_bytes(b"hello")

    def test_different_inputs_differ(self):
        assert hash_bytes(b"hello") != hash_bytes(b"world")

    def test_returns_64_char_hex(self):
        result = hash_bytes(b"test")
        assert len(result) == 64
        assert all(c in "0123456789abcdef" for c in result)

    def test_empty_bytes(self):
        result = hash_bytes(b"")
        assert len(result) == 64


class TestBlobPath:
    def test_embeddings(self):
        root = Path("/repo")
        digest = Sha256("abc123")
        result = blob_path(root, digest, "embeddings")
        assert result == Path("/repo/.context-kernel/embeddings/abc123.bin")

    def test_summaries(self):
        root = Path("/repo")
        digest = Sha256("abc123")
        result = blob_path(root, digest, "summaries")
        assert result == Path("/repo/.context-kernel/summaries/abc123.md")
