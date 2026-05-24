"""IngestionError. See ARCHITECTURE.md §5."""

from pathlib import Path


class IngestionError(Exception):
    """Raised by Ingester with source-file context."""

    def __init__(self, message: str, source: Path | None = None) -> None:
        super().__init__(message)
        self.source = source
