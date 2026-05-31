"""Tests for the plain-text ChunkHandler."""

from __future__ import annotations

from pathlib import Path

import pytest

from context_kernel.ingester._chunking import _CEILING
from context_kernel.ingester.text_handler import TextHandler


@pytest.fixture
def handler() -> TextHandler:
    return TextHandler()


def test_supports_txt_and_text(handler: TextHandler) -> None:
    assert handler.supports(Path("notes.txt"))
    assert handler.supports(Path("README.text"))
    assert handler.supports(Path("UPPER.TXT"))
    assert not handler.supports(Path("doc.md"))
    assert not handler.supports(Path("main.py"))
    assert not handler.supports(Path("paper.pdf"))


def test_empty_file_returns_empty(handler: TextHandler, tmp_path: Path) -> None:
    f = tmp_path / "empty.txt"
    f.write_text("   \n\n  \n", encoding="utf-8")
    assert handler.chunks(f) == []


def test_short_file_single_chunk(handler: TextHandler, tmp_path: Path) -> None:
    f = tmp_path / "short.txt"
    f.write_text("Just one paragraph.\n\nAnd a second one.", encoding="utf-8")
    chunks = handler.chunks(f)
    assert len(chunks) == 1
    assert "Just one paragraph." in chunks[0]
    assert "And a second one." in chunks[0]


def test_long_file_multiple_bounded_chunks(handler: TextHandler, tmp_path: Path) -> None:
    paragraphs = []
    for i in range(12):
        marker = chr(ord("a") + i)
        sentence = (marker * 8 + ". ")
        paragraphs.append((sentence * 18).strip())  # ~ 380+ chars each
    f = tmp_path / "long.txt"
    f.write_text("\n\n".join(paragraphs), encoding="utf-8")

    chunks = handler.chunks(f)
    assert len(chunks) > 1
    assert all(len(c) <= _CEILING for c in chunks)


def test_crlf_normalized(handler: TextHandler, tmp_path: Path) -> None:
    f = tmp_path / "crlf.txt"
    f.write_bytes(b"line one   \r\nline two\r\n\r\n\r\n\r\nlast")
    chunks = handler.chunks(f)
    assert chunks
    blob = "\n".join(chunks)
    assert "\r" not in blob
    assert "\n\n\n" not in blob  # 3+ blank lines collapsed
