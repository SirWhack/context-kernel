"""Tests for the Materializer module. See ARCHITECTURE.md §2.3."""

# TODO(test): AGENTS.md + CLAUDE.md bridge render; freshness header round-trip; pinned-block merge; view rendering; MaterializationError surface.
from context_kernel.materializer import (  # noqa: F401
    MaterializationError,
    materialize,
    materialize_view,
)
