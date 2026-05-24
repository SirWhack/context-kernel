"""Tests for the ConfigStore. See ARCHITECTURE.md §3.1."""

# TODO(test): defaults applied when config file absent; view specs parsed; portfolio_root resolution.
from context_kernel.config_store import (  # noqa: F401
    Config,
    IngesterConfig,
    MaterializerConfig,
    OrientationConfig,
    load,
)
