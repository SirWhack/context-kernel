"""Shared source-kind classification helpers.

Kept outside ingester/scoring so graph construction, authority scoring, and
query-time source selection agree on what counts as code-like source.
"""

from __future__ import annotations

CODE_EXT = (
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".mjs",
    ".cjs",
    ".rs",
    ".graphql",
    ".gql",
    ".html",
    ".htm",
)

IAC_EXT = (
    ".tf.json",
    ".tf",
    ".tfvars",
    ".hcl",
    ".bicep",
)

OPS_EXT = IAC_EXT + (
    ".yaml",
    ".yml",
)


def has_suffix(path: str, suffixes: tuple[str, ...]) -> bool:
    return path.lower().endswith(suffixes)


def is_code_path(path: str) -> bool:
    return has_suffix(path, CODE_EXT)


def is_ops_path(path: str) -> bool:
    return has_suffix(path, OPS_EXT)
