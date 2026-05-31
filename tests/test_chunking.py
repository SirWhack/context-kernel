"""Unit tests for the shared prose chunker + normalizers (_chunking)."""

from __future__ import annotations

from context_kernel.ingester._chunking import (
    _CEILING,
    _TARGET,
    chunk_prose,
    normalize_pdf_text,
    normalize_text,
)


def _para(n_chars: int, marker: str = "x") -> str:
    """A single paragraph (no blank lines) of approximately n_chars."""
    sentence = (marker * 8 + ". ")
    reps = max(1, n_chars // len(sentence))
    return (sentence * reps).strip()


def test_empty_or_whitespace_returns_empty() -> None:
    assert chunk_prose("") == []
    assert chunk_prose("   \n\n  \t \n") == []


def test_short_text_single_chunk() -> None:
    text = "First paragraph here.\n\nSecond short paragraph."
    chunks = chunk_prose(text)
    assert len(chunks) == 1
    assert "First paragraph" in chunks[0]
    assert "Second short paragraph" in chunks[0]


def test_multi_paragraph_over_target_splits_into_multiple() -> None:
    # ~10 paragraphs of ~400 chars each => well over target => multiple chunks.
    paragraphs = [_para(400, marker=chr(ord("a") + i)) for i in range(10)]
    text = "\n\n".join(paragraphs)
    chunks = chunk_prose(text)
    assert len(chunks) > 1
    # Every chunk respects the hard ceiling.
    assert all(len(c) <= _CEILING for c in chunks)
    # No paragraph was split mid-paragraph: each paragraph's distinctive marker
    # block appears intact in some chunk.
    joined = "\n".join(chunks)
    for i in range(10):
        assert (chr(ord("a") + i) * 8) in joined


def test_single_oversized_paragraph_splits_at_sentences() -> None:
    # One paragraph far exceeding the ceiling, made of clear sentences.
    big = " ".join(f"Sentence number {i} has some words in it." for i in range(120))
    assert len(big) > _CEILING
    chunks = chunk_prose(big)
    assert len(chunks) > 1
    assert all(len(c) <= _CEILING for c in chunks)
    # Split happened at sentence boundaries: pieces (ignoring any overlap seed)
    # should end on sentence punctuation in the common case.
    assert any(c.rstrip().endswith(".") for c in chunks)


def test_overlap_present_between_consecutive_chunks() -> None:
    paragraphs = [_para(500, marker=chr(ord("a") + i)) for i in range(8)]
    text = "\n\n".join(paragraphs)
    chunks = chunk_prose(text)
    assert len(chunks) >= 2
    # The start of a later chunk should carry a tail from its predecessor:
    # find at least one consecutive pair sharing a non-trivial leading overlap.
    found_overlap = False
    for prev, nxt in zip(chunks, chunks[1:]):
        seed = nxt.split("\n\n", 1)[0].strip()
        if seed and seed in prev:
            found_overlap = True
            break
    assert found_overlap, "expected overlap tail carried into a following chunk"


def test_overlap_never_loops_on_tiny_paragraphs() -> None:
    # Many tiny paragraphs must terminate and not explode.
    text = "\n\n".join(["a."] * 50)
    chunks = chunk_prose(text)
    assert isinstance(chunks, list)
    assert chunks  # produced something
    assert all(len(c) <= _CEILING for c in chunks)


def test_normalize_text_crlf_blanklines_rstrip() -> None:
    raw = "line one   \r\nline two\r\n\r\n\r\n\r\nlast"
    out = normalize_text(raw)
    assert "\r" not in out
    assert "line one\n" in out  # trailing spaces stripped
    # 4 blank lines collapsed to a single blank line (\n\n).
    assert "\n\n\n" not in out
    assert "line two\n\nlast" in out


def test_normalize_pdf_dehyphenation_and_line_join() -> None:
    # "hyphen-\nated" should become "hyphenated"; single newlines within a
    # paragraph become spaces; a blank line stays a paragraph break.
    raw = (
        "This is a hyphen-\nated word that was\nwrapped across lines.\n\n"
        "Second paragraph\nalso wrapped."
    )
    out = normalize_pdf_text(raw)
    assert "hyphenated" in out
    assert "hyphen-" not in out
    # Intra-paragraph newlines joined to spaces.
    assert "word that was wrapped across lines." in out
    # Paragraph break preserved.
    assert "\n\n" in out
    assert "Second paragraph also wrapped." in out


def test_normalize_pdf_formfeed_is_paragraph_break() -> None:
    raw = "Page one text.\fPage two text."
    out = normalize_pdf_text(raw)
    assert "\f" not in out
    assert "Page one text.\n\nPage two text." in out


def test_normalize_pdf_collapses_spaces() -> None:
    raw = "word    with     many    spaces"
    out = normalize_pdf_text(raw)
    assert "  " not in out
    assert out == "word with many spaces"


def test_pdf_text_then_chunk_round_trip() -> None:
    # A realistic PDF-extracted blob runs cleanly through normalize -> chunk.
    pages = []
    for p in range(4):
        body = " ".join(
            f"Para{p}-sentence{i} explains some-\nthing across wrapped lines."
            for i in range(20)
        )
        pages.append(body)
    raw = "\f".join(pages)
    chunks = chunk_prose(normalize_pdf_text(raw))
    assert chunks
    assert all(len(c) <= _CEILING for c in chunks)
    # De-hyphenation survived chunking.
    assert any("something" in c for c in chunks)
    assert _TARGET <= _CEILING  # sanity on the configured budget
