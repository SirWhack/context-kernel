"""Tests for the FreshnessGate module. See ARCHITECTURE.md §2.4."""

# TODO(test): header mismatch triggers regen; happy path returns fresh content silently; StaleReadError only on regen failure.
from context_kernel.freshness_gate import StaleReadError, check  # noqa: F401
