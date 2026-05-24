"""<!-- pinned --> block merge. The only place hand-edits survive regeneration. See ARCHITECTURE.md §2.3, §4."""


def extract(existing: str) -> list[str]:
    """Return the contents of all <!-- pinned --> blocks in an existing materialized file."""
    raise NotImplementedError("TODO(impl)")


def merge(rendered: str, pinned_blocks: list[str]) -> str:
    """Merge pinned blocks back into a freshly rendered output."""
    raise NotImplementedError("TODO(impl)")
