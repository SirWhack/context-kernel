"""ConfigStore — loads .context-kernel/config.toml at the start of every `ck` invocation. See ARCHITECTURE.md §3.1."""

from dataclasses import dataclass, field
from pathlib import Path

from context_kernel.types import ViewSpec


@dataclass(frozen=True)
class IngesterConfig:
    summarizer_model: str
    embedder_model: str
    storage_backend: str


@dataclass(frozen=True)
class MaterializerConfig:
    views: list[ViewSpec] = field(default_factory=list)


@dataclass(frozen=True)
class OrientationConfig:
    default_max_tokens: int = 4096


@dataclass(frozen=True)
class Config:
    """Top-level configuration loaded from .context-kernel/config.toml."""

    ingester: IngesterConfig
    materializer: MaterializerConfig
    orientation: OrientationConfig
    portfolio_root: Path


def load(config_path: Path | None = None) -> Config:
    """Load configuration from disk, applying defaults for any missing keys."""
    raise NotImplementedError("TODO(impl)")
