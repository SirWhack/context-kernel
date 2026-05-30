"""Decide which source files need re-ingesting. Unchanged source = no-op per invariant 4.

Also the sole git-I/O layer for drift (ADR-0020): `commit_of` / `churn` / `size` read git
diff *content* between two commit IDs — no wall-clock — so drift is deterministic and
reproducible across clones. All three return safe defaults on any git failure (untracked
file, not a repo) so drift falls to 0 rather than raising.
"""

import hashlib
import os
import subprocess
from functools import lru_cache
from pathlib import Path

from context_kernel.types import GraphCommit, Sha256, ScopePath

_EXCLUDED_DIRS = frozenset({".git", ".context-kernel", "node_modules", "__pycache__"})
_MATERIALIZED_FILES = frozenset({"AGENTS.md", "CLAUDE.md"})

# Extra directory names to exclude, set per-invocation via the environment.
# Comma-separated, e.g. CK_EXTRA_EXCLUDED_DIRS="data,assets,deploy". Dotdirs
# (.git, .venv, .context-kernel, ...) are already excluded unconditionally.
_EXTRA_EXCLUDED_DIRS = frozenset(
    name.strip()
    for name in os.environ.get("CK_EXTRA_EXCLUDED_DIRS", "").split(",")
    if name.strip()
)


def _is_excluded(path: Path) -> bool:
    if path.name in _MATERIALIZED_FILES:
        return True
    return any(
        part in _EXCLUDED_DIRS
        or part in _EXTRA_EXCLUDED_DIRS
        or (part.startswith(".") and part not in {"."})
        for part in path.parts
    )


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


# ── Git churn layer (ADR-0020 drift) ────────────────────────────────────────


def _run_git(args: list[str], cwd: Path) -> str | None:
    """Run git in `cwd`; return stdout, or None on any failure (not a repo, git absent)."""
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout


@lru_cache(maxsize=None)
def commit_of(path: str) -> str | None:
    """The last commit hash that touched `path`, or None if untracked / not in a repo.

    This is the claimant's reference point: drift to a referent is measured over
    (commit_of(claimant), HEAD].
    """
    p = Path(path)
    out = _run_git(["log", "-1", "--format=%H", "--", str(p)], cwd=p.parent)
    if not out:
        return None
    return out.strip() or None


@lru_cache(maxsize=None)
def churn(path: str, since: str | None, until: str = "HEAD") -> int:
    """Lines changed (added + removed) to `path` in the commit range (since, until].

    `since is None` (untracked claimant) → 0: no interval, no drift. Binary files
    (numstat `-`) contribute 0. Pure git-content; no clock.
    """
    if since is None:
        return 0
    p = Path(path)
    out = _run_git(
        ["log", "--numstat", "--format=", f"{since}..{until}", "--", str(p)],
        cwd=p.parent,
    )
    if not out:
        return 0
    total = 0
    for line in out.splitlines():
        cols = line.strip().split("\t")
        if len(cols) < 2:
            continue
        added, removed = cols[0], cols[1]
        if added.isdigit():
            total += int(added)
        if removed.isdigit():
            total += int(removed)
    return total


@lru_cache(maxsize=None)
def size(path: str) -> int:
    """Current line count of `path` on disk (the referent size for drift normalization).

    Returns 0 on read failure → edge_drift then yields 0 (nothing to normalize against).
    """
    try:
        data = Path(path).read_bytes()
    except OSError:
        return 0
    if not data:
        return 0
    return data.count(b"\n") + (0 if data.endswith(b"\n") else 1)


def _clear_git_caches() -> None:
    """Drop memoized git/disk reads. For tests that mutate a repo within one process."""
    commit_of.cache_clear()
    churn.cache_clear()
    size.cache_clear()
