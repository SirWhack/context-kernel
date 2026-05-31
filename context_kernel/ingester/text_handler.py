"""Plain-text source handler (ChunkHandler).

Plain text (``.txt`` / ``.text``) has no structural skeleton the way
Python/TS/HTML do — it is pure prose. So, like ``MarkdownHandler``, this is a
RAG ChunkHandler: it normalizes the file and emits text chunks for the
Summarizer to extract entities + embeddings from. Chunking is delegated to the
shared ``chunk_prose`` helper so plain text, PDF, and markdown all produce
uniformly-sized chunks (see ``_chunking`` for the strategy + overlap rationale).
"""

from __future__ import annotations

import logging
from pathlib import Path

from context_kernel.ingester._chunking import chunk_prose, normalize_text

log = logging.getLogger(__name__)


class TextHandler:
    """Chunk plain-text files for the Summarizer (paragraph-aware, overlapped)."""

    def supports(self, path: Path) -> bool:
        return path.suffix.lower() in {".txt", ".text"}

    def chunks(self, path: Path) -> list[str]:
        text = path.read_text(encoding="utf-8", errors="replace")
        if not text.strip():
            return []
        return chunk_prose(normalize_text(text))
