"""Decide which source files need re-ingesting. Unchanged source = no-op per invariant 4."""

import hashlib
from pathlib import Path

from context_kernel.types import GraphCommit, Sha256, ScopePath

_EXCLUDED_DIRS = frozenset({".git", ".context-kernel", "node_modules", "__pycache__"})
_MATERIALIZED_FILES = frozenset({"AGENTS.md", "CLAUDE.md"})


def _is_excluded(path: Path) -> bool:
    if path.name in _MATERIALIZED_FILES:
        return True
    return any(part in _EXCLUDED_DIRS or (part.startswith(".") and part not in {"."}) for part in path.parts)


def walk_source_files(root: Path) -> list[Path]:
    """Return all non-excluded files under root, sorted for deterministic hashing."""
    files: list[Path] = []
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(root)
        if _is_excluded(rel):
            continue
        files.append(p)
    return files


def source_tree_hash(scope_dir: Path, tree_root: Path) -> Sha256:
    """Hash all source files in a scope directory for freshness comparison."""
    h = hashlib.sha256()
    for f in walk_source_files(scope_dir):
        rel = f.relative_to(tree_root)
        h.update(str(rel).encode())
        h.update(f.read_bytes())
    return Sha256(h.hexdigest())


def discover_scopes(tree_root: Path) -> list[ScopePath]:
    """Return all directories under tree_root that contain at least one non-excluded file."""
    scope_dirs: set[Path] = set()
    for f in walk_source_files(tree_root):
        scope_dirs.add(f.parent)
    scopes = sorted(scope_dirs)
    return [ScopePath(d.relative_to(tree_root)) for d in scopes]


def changed_since(sources_root: Path, last_commit: GraphCommit | None) -> list[Path]:
    """Return source files whose content differs from what's in the last GraphCommit."""
    files = walk_source_files(sources_root)
    if last_commit is None:
        return files
    current = source_tree_hash(sources_root, sources_root)
    if current == last_commit:
        return []
    return files
