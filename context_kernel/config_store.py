"""ConfigStore — loads .context-kernel/config.toml at the start of every `ck` invocation. See ARCHITECTURE.md §3.1."""

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from context_kernel.types import ViewSpec


@dataclass(frozen=True)
class IngesterConfig:
    summarizer_model: str = "qwen3-30b-a3b-instruct-2507"
    summarizer_endpoint: str = "http://127.0.0.1:8080/v1"
    embedder_model: str = "qwen3-embedding-0.6b"
    embedder_endpoint: str = "http://127.0.0.1:8081/v1"
    embedder_dim: int = 1024
    storage_backend: str = "networkx"
    summary_target_tokens: int = 500


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
    env_path = os.environ.get("CK_CONFIG_PATH")
    if config_path is None and env_path:
        config_path = Path(env_path)

    raw: dict = {}
    if config_path and config_path.exists():
        with open(config_path, "rb") as f:
            raw = tomllib.load(f)

    ingester_raw = raw.get("ingester", {})
    materializer_raw = raw.get("materializer", {})
    orientation_raw = raw.get("orientation", {})

    views = [
        ViewSpec(name=v["name"], kind=v["kind"], params=v.get("params", {}))
        for v in materializer_raw.get("views", [])
    ]

    portfolio_root = Path(raw.get("portfolio_root", ".")).resolve()

    return Config(
        ingester=IngesterConfig(**{
            k: v for k, v in ingester_raw.items()
            if k in IngesterConfig.__dataclass_fields__
        }),
        materializer=MaterializerConfig(views=views),
        orientation=OrientationConfig(**{
            k: v for k, v in orientation_raw.items()
            if k in OrientationConfig.__dataclass_fields__
        }),
        portfolio_root=portfolio_root,
    )
