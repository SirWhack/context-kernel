"""Materializer — sole writer to the materialized tree. See ARCHITECTURE.md §2.3, invariant 1."""

from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from context_kernel.graph.protocol import KnowledgeStore
from context_kernel.ingester.change_detection import source_tree_hash
from context_kernel.materializer.errors import MaterializationError
from context_kernel.materializer.headers import FreshnessHeader, parse, render
from context_kernel.materializer.pinned import extract, merge
from context_kernel.materializer.templates import render_agents_md, render_claude_md_bridge
from context_kernel.materializer.views import render_view
from context_kernel.types import ScopePath, Sha256, ViewSpec

if TYPE_CHECKING:
    from context_kernel.config_store import MaterializerConfig

__all__ = ["MaterializationError", "materialize", "materialize_view"]


def _write_if_changed(path: Path, content: str) -> bool:
    """Write content to path only if it differs from current content. Returns True if written."""
    if path.exists() and path.read_text(encoding="utf-8") == content:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return True


def materialize(
    scope: ScopePath,
    store: KnowledgeStore,
    tree_root: Path,
    config: "MaterializerConfig",
) -> list[Path]:
    """Write AGENTS.md + CLAUDE.md bridge for this scope. Returns paths of files written."""
    scope_dir = tree_root / scope
    agents_path = scope_dir / "AGENTS.md"
    claude_path = scope_dir / "CLAUDE.md"

    gc = store.graph_commit()
    sth = source_tree_hash(scope_dir, tree_root)

    if agents_path.exists():
        existing = agents_path.read_text(encoding="utf-8")
        existing_header = parse(existing)
        if existing_header and existing_header.graph_commit == gc and existing_header.source_tree_hash == sth:
            written: list[Path] = []
            if _write_if_changed(claude_path, render_claude_md_bridge()):
                written.append(claude_path)
            return written

    pinned_blocks: list[str] = []
    if agents_path.exists():
        pinned_blocks = extract(agents_path.read_text(encoding="utf-8"))

    header = FreshnessHeader(
        graph_commit=gc,
        source_tree_hash=sth,
        materialized_at=datetime.now(timezone.utc),
    )
    summary = store.get_summary(scope)

    rendered = render_agents_md(header, summary)
    if pinned_blocks:
        rendered = merge(rendered, pinned_blocks)

    written: list[Path] = []
    if _write_if_changed(agents_path, rendered):
        written.append(agents_path)
    if _write_if_changed(claude_path, render_claude_md_bridge()):
        written.append(claude_path)
    return written


_VIEW_SOURCE_TREE_SENTINEL = Sha256("0" * 64)


def _view_output_path(spec: ViewSpec, tree_root: Path) -> Path:
    views_dir = tree_root / ".context-kernel" / "views"
    if spec.kind == "by-topic":
        tag = spec.params.get("tag", spec.name)
        return views_dir / "by-topic" / f"{tag}.md"
    return views_dir / f"{spec.name}.md"


def materialize_view(
    spec: ViewSpec,
    store: KnowledgeStore,
    tree_root: Path,
    config: "MaterializerConfig",
) -> list[Path]:
    """Write one configured cross-cutting view under .context-kernel/views/. Returns paths written."""
    out_path = _view_output_path(spec, tree_root)
    gc = store.graph_commit()

    if out_path.exists():
        existing_header = parse(out_path.read_text(encoding="utf-8"))
        if existing_header and existing_header.graph_commit == gc:
            return []

    header = FreshnessHeader(
        graph_commit=gc,
        source_tree_hash=_VIEW_SOURCE_TREE_SENTINEL,
        materialized_at=datetime.now(timezone.utc),
    )

    body = render_view(spec, store)
    content = render(header) + "\n\n" + body

    written: list[Path] = []
    if _write_if_changed(out_path, content):
        written.append(out_path)
    return written
