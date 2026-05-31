"""Tests for the PDF ChunkHandler.

These tests do NOT depend on a real PDF or ``reportlab``: the page-text
extraction seam ``PDFHandler._extract_pages`` is monkeypatched to return known
page strings, so we exercise normalization + chunking deterministically.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from context_kernel.ingester._chunking import _CEILING
from context_kernel.ingester.pdf_handler import PDFHandler


@pytest.fixture
def handler() -> PDFHandler:
    return PDFHandler()


def test_supports_only_pdf(handler: PDFHandler) -> None:
    assert handler.supports(Path("paper.pdf"))
    assert handler.supports(Path("REPORT.PDF"))
    assert not handler.supports(Path("notes.txt"))
    assert not handler.supports(Path("doc.md"))
    assert not handler.supports(Path("main.py"))


def test_extraction_normalized_and_chunked(
    handler: PDFHandler, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pages = [
        "This is a hyphen-\nated word that was\nwrapped across lines.",
        "Second page with more\nwrapped prose to read.",
    ]
    monkeypatch.setattr(PDFHandler, "_extract_pages", lambda self, path: pages)

    chunks = handler.chunks(tmp_path / "doc.pdf")
    assert chunks
    blob = "\n".join(chunks)
    # De-hyphenation applied across the line break.
    assert "hyphenated" in blob
    assert "hyphen-" not in blob
    # Intra-page single newlines joined into spaces.
    assert "word that was wrapped across lines." in blob
    # Second page content present.
    assert "Second page with more wrapped prose to read." in blob


def test_many_pages_produce_bounded_chunks(
    handler: PDFHandler, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pages = []
    for p in range(20):
        marker = chr(ord("a") + (p % 26))
        body = " ".join(f"{marker * 6} sentence {i} here." for i in range(30))
        pages.append(body)
    monkeypatch.setattr(PDFHandler, "_extract_pages", lambda self, path: pages)

    chunks = handler.chunks(tmp_path / "big.pdf")
    assert len(chunks) > 1
    assert all(len(c) <= _CEILING for c in chunks)


def test_scanned_pdf_returns_empty(
    handler: PDFHandler, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Image-only PDF: extraction yields empty/near-empty text for all pages.
    monkeypatch.setattr(PDFHandler, "_extract_pages", lambda self, path: ["", "  ", ""])
    assert handler.chunks(tmp_path / "scan.pdf") == []


def test_extraction_failure_returns_empty_without_raising(
    handler: PDFHandler, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def boom(self, path):  # noqa: ANN001, ANN202 - test stub
        raise ValueError("corrupt PDF")

    monkeypatch.setattr(PDFHandler, "_extract_pages", boom)
    # Must not raise.
    assert handler.chunks(tmp_path / "corrupt.pdf") == []


def test_missing_path_returns_empty_without_raising(handler: PDFHandler, tmp_path: Path) -> None:
    # No monkeypatch: real _extract_pages on a nonexistent file -> pypdf raises
    # -> handler swallows and returns [].
    missing = tmp_path / "does-not-exist.pdf"
    assert handler.chunks(missing) == []


def test_garbage_file_returns_empty_without_raising(handler: PDFHandler, tmp_path: Path) -> None:
    f = tmp_path / "garbage.pdf"
    f.write_bytes(b"this is not a real pdf at all \x00\x01\x02")
    assert handler.chunks(f) == []
