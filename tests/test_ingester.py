"""Tests for the Ingester module. See ARCHITECTURE.md §2.2."""

# TODO(test): markdown handler; change detection no-op on unchanged source; blob round-trip; IngestionError surface.
from context_kernel.ingester import IngestionError, ingest  # noqa: F401
