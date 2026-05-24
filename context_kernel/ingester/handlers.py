"""Source-format handlers. v1: markdown only; Python AST + TS/JS + PDF deferred per PLAN.md S3/S4/S11."""

from pathlib import Path
from typing import Protocol


class SourceHandler(Protocol):
    """Parse one source file into the chunks the Summarizer will see."""

    def supports(self, path: Path) -> bool: ...

    def chunks(self, path: Path) -> list[str]: ...


class MarkdownHandler:
    """v1 source handler for markdown files."""

    def supports(self, path: Path) -> bool:
        raise NotImplementedError("TODO(impl)")

    def chunks(self, path: Path) -> list[str]:
        raise NotImplementedError("TODO(impl)")
