"""Shared prose chunker + text normalizers for RAG ChunkHandlers.

Both the plain-text handler (``text_handler.py``) and the PDF handler
(``pdf_handler.py``) extract raw text and then feed it through the SAME
``chunk_prose`` function, so the Summarizer sees uniformly-sized chunks
across every prose format — matching the markdown path's ``_CHUNK_SIZE``
budget (``handlers.py``).

Chunking strategy (why this shape):

- **Target ~1500 chars** (``_TARGET``), hard ceiling ~1800 (``_CEILING``).
  Each chunk becomes one LLM Summarizer call, so the budget is chosen to
  match the markdown handler's ``_CHUNK_SIZE`` — keeping per-chunk cost and
  extraction quality consistent regardless of source format.

- **Paragraph-aware greedy packing.** We split on blank lines and greedily
  pack whole paragraphs into a chunk until the next paragraph would push it
  past the target, then flush. A fact rarely straddles a paragraph break, so
  keeping paragraphs whole preserves the local context the Summarizer needs.
  A single paragraph that alone exceeds the ceiling is split at sentence
  boundaries, then words (mirroring ``handlers._split_oversized``).

- **Small overlap (``_OVERLAP`` ~150 chars).** We carry the tail (≈1-2
  sentences) of each emitted chunk into the start of the next. This is the
  key RAG improvement over the markdown handler's hard, no-overlap split: a
  fact that lands near a chunk boundary is then retrievable from BOTH
  neighbours, so embedding search does not miss it because it was bisected.
  The overlap is deliberately small to bound summarizer cost (we pay to
  re-summarize the carried tail) and is never large enough to re-emit a whole
  chunk — which also guarantees forward progress on tiny inputs (no infinite
  loop).

All functions here are pure (operate on plain strings) and unit-testable in
isolation; the handlers only do I/O + format-specific normalization.
"""

from __future__ import annotations

import re

# Budget mirrors handlers._CHUNK_SIZE so all prose formats produce
# uniformly-sized chunks for the Summarizer.
_TARGET = 1500
_CEILING = 1800
# Tail carried from one chunk into the next for retrieval continuity.
_OVERLAP = 150

_SENTENCE_SEPS = (". ", "? ", "! ", "\n")
_BLANK_LINE_RE = re.compile(r"\n\s*\n")
_MULTI_BLANK_RE = re.compile(r"\n{3,}")
_SPACES_RE = re.compile(r"[ \t]{2,}")
# A word/line break ladder for splitting a single oversized paragraph.
_HARD_SEPS = ("\n", ". ", "? ", "! ", " ")


def normalize_text(text: str) -> str:
    """Normalize a plain-text document before chunking.

    CRLF -> LF, collapse 3+ consecutive blank lines to 2, rstrip each line.
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in text.split("\n")]
    text = "\n".join(lines)
    text = _MULTI_BLANK_RE.sub("\n\n", text)
    return text


def normalize_pdf_text(text: str) -> str:
    """Normalize text extracted from a PDF before chunking.

    PDF extraction yields hard-wrapped lines and words split across line
    breaks. We:
      - de-hyphenate words broken across a line break (``foo-\\nbar`` -> ``foobar``),
      - treat 2+ newlines and form-feed page breaks (``\\f``) as paragraph
        separators,
      - join the single newlines *within* a paragraph into spaces (PDFs wrap
        mid-sentence),
      - collapse runs of spaces.

    Running header/footer de-duplication is intentionally NOT done here: it
    needs per-page structure the chunker doesn't see, and naive line-frequency
    stripping risks dropping legitimately repeated body text. Callers that have
    per-page text can strip recurring lines before concatenation if desired.
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # De-hyphenate words broken across a line break.
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)
    # Form-feed page breaks act as paragraph separators.
    text = text.replace("\f", "\n\n")
    # Normalize paragraph separators (2+ newlines, possibly with whitespace)
    # to a sentinel so we can collapse the remaining single newlines safely.
    sentinel = "\x00PARA\x00"
    text = _BLANK_LINE_RE.sub(sentinel, text)
    # Join single (intra-paragraph) newlines into spaces.
    text = text.replace("\n", " ")
    # Restore paragraph breaks.
    text = text.replace(sentinel, "\n\n")
    # Collapse runs of spaces/tabs.
    text = _SPACES_RE.sub(" ", text)
    # Tidy whitespace hugging the paragraph breaks.
    text = re.sub(r" *\n\n *", "\n\n", text)
    return text


def _split_paragraphs(text: str) -> list[str]:
    """Split text into non-empty, stripped paragraphs on blank lines."""
    parts = _BLANK_LINE_RE.split(text)
    return [p.strip() for p in parts if p.strip()]


def _split_oversized(text: str, max_size: int) -> list[str]:
    """Split a single oversized paragraph at sentence/line/word boundaries.

    Mirrors ``handlers._split_oversized`` in spirit: prefer the latest
    sentence/line/word boundary before ``max_size``; hard-cut only if no
    boundary is found.
    """
    if len(text) <= max_size:
        return [text]
    result: list[str] = []
    start = 0
    n = len(text)
    while start < n:
        end = start + max_size
        if end < n:
            for sep in _HARD_SEPS:
                pos = text.rfind(sep, start, end)
                if pos > start:
                    end = pos + len(sep)
                    break
        piece = text[start:end].strip()
        if piece:
            result.append(piece)
        start = end
    return result


def _overlap_tail(chunk: str) -> str:
    """Return the trailing ~_OVERLAP chars of ``chunk`` on a sentence boundary.

    Used to seed the next chunk for retrieval continuity. Always strictly
    shorter than the chunk (bounded by _OVERLAP), guaranteeing forward
    progress.
    """
    if len(chunk) <= _OVERLAP:
        # For a tiny chunk, carrying the whole thing would risk no progress;
        # carry nothing.
        return ""
    tail = chunk[-_OVERLAP:]
    # Prefer to start the tail at a sentence boundary so it reads cleanly.
    best = -1
    for sep in _SENTENCE_SEPS:
        pos = tail.find(sep)
        if pos != -1:
            cut = pos + len(sep)
            if cut > best:
                best = cut
    if best != -1 and best < len(tail):
        tail = tail[best:]
    return tail.strip()


def chunk_prose(text: str) -> list[str]:
    """Greedily pack paragraphs into ~_TARGET-char chunks with small overlap.

    Returns ``[]`` for empty/whitespace-only input. Every returned chunk is
    ``<= _CEILING`` characters. Consecutive chunks share a small leading
    overlap (the prior chunk's sentence-aligned tail) so facts near a boundary
    remain retrievable from both neighbours.
    """
    if not text or not text.strip():
        return []

    paragraphs = _split_paragraphs(text)
    if not paragraphs:
        return []

    chunks: list[str] = []
    current = ""

    def flush() -> None:
        nonlocal current
        if current.strip():
            chunks.append(current.strip())
        current = ""

    for para in paragraphs:
        # A single paragraph larger than the ceiling must be hard-split.
        if len(para) > _CEILING:
            flush()
            for sub in _split_oversized(para, _TARGET):
                seed = _overlap_tail(chunks[-1]) if chunks else ""
                piece = f"{seed}\n\n{sub}" if seed else sub
                # Hard-split pieces are already <= _TARGET; with the seed they
                # stay within the ceiling because _OVERLAP < (_CEILING-_TARGET).
                chunks.append(piece.strip())
            continue

        candidate = f"{current}\n\n{para}" if current else para
        if len(candidate) <= _TARGET:
            current = candidate
            continue

        # Adding this paragraph would exceed the target: flush and start a
        # fresh chunk seeded with the previous chunk's overlap tail.
        flush()
        seed = _overlap_tail(chunks[-1]) if chunks else ""
        current = f"{seed}\n\n{para}" if seed else para

    flush()
    return chunks
