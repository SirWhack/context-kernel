"""Source-format handlers. v1: markdown only; Python AST + TS/JS + PDF deferred per PLAN.md S3/S4/S11."""

from pathlib import Path
from typing import Protocol


class SourceHandler(Protocol):
    """Parse one source file into the chunks the Summarizer will see."""

    def supports(self, path: Path) -> bool: ...

    def chunks(self, path: Path) -> list[str]: ...


_CHUNK_SIZE = 1500
_CHUNK_OVERLAP = 200


class MarkdownHandler:
    """v1 source handler for markdown files."""

    def supports(self, path: Path) -> bool:
        return path.suffix.lower() in {".md", ".markdown"}

    def chunks(self, path: Path) -> list[str]:
        text = path.read_text(encoding="utf-8", errors="replace")
        if not text.strip():
            return []
        if len(text) <= _CHUNK_SIZE:
            return [text]
        result: list[str] = []
        start = 0
        while start < len(text):
            end = start + _CHUNK_SIZE
            if end < len(text):
                nl = text.rfind("\n", start, end)
                if nl > start:
                    end = nl + 1
            result.append(text[start:end])
            start = end - _CHUNK_OVERLAP if end < len(text) else end
        return result
