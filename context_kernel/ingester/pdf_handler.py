"""PDF source handler (ChunkHandler).

PDFs are prose containers: once the text is extracted they have no API
surface, so this is a RAG ChunkHandler that emits text chunks for the
Summarizer. Page text is extracted with ``pypdf`` (imported lazily inside
``chunks`` like ``TypeScriptHandler`` lazy-imports tree-sitter), normalized for
the quirks PDF extraction introduces (hyphenation across line breaks, hard
mid-sentence wrapping, page breaks), and then run through the SAME
``chunk_prose`` helper as plain text / markdown so every prose format yields
uniformly-sized chunks.

Failure is defined out of existence at the interface: any extraction problem
(corrupt file, missing ``pypdf``, unreadable page) logs a warning and returns
``[]`` rather than raising. Scanned/image-only PDFs (no extractable text) also
return ``[]`` — OCR is out of scope.
"""

from __future__ import annotations

import logging
from pathlib import Path

from context_kernel.ingester._chunking import chunk_prose, normalize_pdf_text

log = logging.getLogger(__name__)

# A document whose extracted text is below this many non-whitespace chars is
# treated as scanned/image-only (no usable text) -> returns [].
_MIN_TEXT_CHARS = 16


class PDFHandler:
    """Chunk PDF files for the Summarizer; never raises (returns [] on failure)."""

    def supports(self, path: Path) -> bool:
        return path.suffix.lower() == ".pdf"

    def _extract_pages(self, path: Path) -> list[str]:
        """Return the extracted text of each page, in order.

        Separable seam (mirrors the contract used by the structured handlers):
        tests monkeypatch this to supply known page strings without a real PDF
        or ``reportlab``. May raise — the caller in ``chunks`` wraps it.
        """
        import pypdf  # lazy: keeps the dependency off the import path until used

        reader = pypdf.PdfReader(str(path))
        return [(page.extract_text() or "") for page in reader.pages]

    def chunks(self, path: Path) -> list[str]:
        try:
            pages = self._extract_pages(path)
        except Exception as exc:  # corrupt PDF, missing pypdf, unreadable page
            log.warning("Failed to read PDF %s, skipping: %s", path, exc)
            return []

        raw = "\n\n".join(pages)
        # Scanned/image-only PDFs yield empty/near-empty text for all pages.
        if len(raw.strip()) < _MIN_TEXT_CHARS:
            log.warning(
                "PDF %s has no extractable text (scanned/image-only?), skipping", path
            )
            return []

        return chunk_prose(normalize_pdf_text(raw))
