"""FreshnessGate — read-boundary enforcement of invariant 2 ('no stale serve'). See ARCHITECTURE.md §2.4."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

from context_kernel.graph.protocol import KnowledgeStore
from context_kernel.change_detection import source_tree_hash
from context_kernel.materializer.headers import parse

if TYPE_CHECKING:
    from context_kernel.config_store import Config

log = logging.getLogger(__name__)


class StaleReadError(Exception):
    """Raised only if regeneration itself fails. Happy path returns fresh content silently."""


def _scope_from_path(path: Path, tree_root: Path) -> Path:
    return path.parent.relative_to(tree_root)


def check(path: Path, store: KnowledgeStore, tree_root: Path, config: "Config | None" = None) -> bytes:
    """Compare path's freshness header against current state; regenerate if stale; return fresh bytes."""
    from context_kernel.materializer import materialize
    from context_kernel.ingester import ingest, ingest_portfolio
    from context_kernel.config_store import IngesterConfig, MaterializerConfig
    from context_kernel.types import ScopePath

    scope = ScopePath(_scope_from_path(path, tree_root))
    scope_dir = tree_root / scope
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    header = parse(text)

    sth_current = source_tree_hash(scope_dir, tree_root)
    gc_current = store.graph_commit()

    if header and header.graph_commit == gc_current and header.source_tree_hash == sth_current:
        log.info("freshness hit", extra={"scope": str(scope), "graph_commit": str(gc_current)})
        return path.read_bytes()

    stale_gc = str(header.graph_commit) if header else None
    source_tree_is_stale = header is None or header.source_tree_hash != sth_current
    log.info(
        "freshness miss",
        extra={
            "scope": str(scope),
            "stale_graph_commit": stale_gc,
            "current_graph_commit": str(gc_current),
            "source_tree_stale": source_tree_is_stale,
        },
    )

    try:
        if source_tree_is_stale:
            if config:
                from context_kernel.ingester.embedder import HttpEmbedder
                from context_kernel.ingester.summarizer import LLMSummarizer
                from context_kernel.types import LLMMetrics

                metrics = LLMMetrics()
                summarizer_key = os.environ.get(config.ingester.summarizer_api_key_env) or os.environ.get("CK_API_KEY")
                embedder_key = os.environ.get(config.ingester.embedder_api_key_env) or os.environ.get("CK_API_KEY")
                summarizer = LLMSummarizer(
                    endpoint=config.ingester.summarizer_endpoint,
                    model=config.ingester.summarizer_model,
                    cache_dir=tree_root / ".context-kernel" / "cache",
                    api_key=summarizer_key,
                    metrics=metrics,
                )
                embedder = HttpEmbedder(
                    endpoint=config.ingester.embedder_endpoint,
                    model=config.ingester.embedder_model,
                    dim=config.ingester.embedder_dim,
                    api_key=embedder_key,
                    metrics=metrics,
                )
                projects = [
                    (project.path, None if project.path == Path(".") else project.name)
                    for project in config.projects
                ]
                ingest_portfolio(
                    store,
                    tree_root,
                    tree_root,
                    config.ingester,
                    projects,
                    summarizer=summarizer,
                    embedder=embedder,
                    metrics=metrics,
                )
            else:
                ingest(store, tree_root, tree_root, IngesterConfig())

        mat_config = config.materializer if config else MaterializerConfig()
        materialize(scope, store, tree_root, mat_config)
    except Exception as exc:
        raise StaleReadError(f"Regeneration failed for {path}: {exc}") from exc

    return path.read_bytes()
