"""ConfigStore — loads .context-kernel/config.toml at the start of every `ck` invocation. See ARCHITECTURE.md §3.1."""

import os
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from context_kernel.scoring import ScoringConfig
from context_kernel.types import ViewSpec

_PROJECT_NAME_RE = re.compile(r"^[a-zA-Z0-9_][a-zA-Z0-9_.\-]*$")


@dataclass(frozen=True)
class ProjectSpec:
    path: Path

    @property
    def name(self) -> str:
        return self.path.name


@dataclass(frozen=True)
class IngesterConfig:
    summarizer_model: str = "qwen3-30b-a3b-instruct-2507"
    summarizer_endpoint: str = "http://127.0.0.1:8080/v1"
    embedder_model: str = "qwen3-embedding-0.6b"
    embedder_endpoint: str = "http://127.0.0.1:8081/v1"
    embedder_dim: int = 1024
    storage_backend: str = "networkx"
    summary_target_tokens: int = 500
    parallel_requests: int = 1
    summarizer_api_key_env: str = "DEEPSEEK_API_KEY"
    embedder_api_key_env: str = "CF_WORKER_AI_TOKEN"
    contextual_extraction: bool = True   # ADR-0016: feed code entities + vocab into doc extraction
    code_context_tokens: int = 2000      # token budget for the known-code-entities prefix
    aspect_max_candidates: int = 500     # ADR-0025 §4: per-aspect recall cap before the judge
    exclude_dirs: tuple[str, ...] = ()   # extra dir names to skip when walking (e.g. "test-repos")
    scoring: ScoringConfig = field(default_factory=ScoringConfig)  # ADR-0015 resolved knobs


@dataclass(frozen=True)
class MaterializerConfig:
    views: list[ViewSpec] = field(default_factory=list)
    gap_detection_threshold: int = 10


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
    projects: list[ProjectSpec] = field(default_factory=lambda: [ProjectSpec(path=Path("."))])


def _validate_projects(projects: list[ProjectSpec], portfolio_root: Path) -> None:
    seen_names: set[str] = set()
    for project in projects:
        if project.path.is_absolute():
            raise ValueError(f"Project path must be relative: {project.path}")
        name = project.name
        if not name:
            raise ValueError(f"Project path resolves to empty name: {project.path}")
        if not _PROJECT_NAME_RE.match(name):
            raise ValueError(
                f"Project name {name!r} (from path {project.path}) must match "
                f"{_PROJECT_NAME_RE.pattern}"
            )
        if name in seen_names:
            raise ValueError(f"Duplicate project name: {name!r}")
        seen_names.add(name)
        resolved = portfolio_root / project.path
        if not resolved.exists():
            raise ValueError(f"Project path does not exist: {resolved}")


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

    projects_raw = raw.get("projects")
    if projects_raw:
        projects = [ProjectSpec(path=Path(p["path"])) for p in projects_raw]
        _validate_projects(projects, portfolio_root)
    else:
        projects = [ProjectSpec(path=Path("."))]

    ingester_kwargs = {
        k: v for k, v in ingester_raw.items()
        if k in IngesterConfig.__dataclass_fields__ and k != "scoring"
    }
    for key in ("summarizer_endpoint", "embedder_endpoint", "summarizer_model", "embedder_model"):
        if key in ingester_kwargs:
            ingester_kwargs[key] = os.path.expandvars(ingester_kwargs[key])
    # TOML arrays parse to lists; the frozen dataclass wants a hashable tuple.
    if "exclude_dirs" in ingester_kwargs:
        ingester_kwargs["exclude_dirs"] = tuple(ingester_kwargs["exclude_dirs"])

    # ADR-0015 precedence: default → [ingester.scoring] config → CK_SCORING_* env (highest).
    scoring = ScoringConfig.resolve(ingester_raw.get("scoring", {}), os.environ)

    return Config(
        ingester=IngesterConfig(**ingester_kwargs, scoring=scoring),
        materializer=MaterializerConfig(
            views=views,
            gap_detection_threshold=materializer_raw.get("gap_detection_threshold", 10),
        ),
        orientation=OrientationConfig(**{
            k: v for k, v in orientation_raw.items()
            if k in OrientationConfig.__dataclass_fields__
        }),
        portfolio_root=portfolio_root,
        projects=projects,
    )
