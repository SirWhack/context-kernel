"""<!-- pinned --> block merge. The only place hand-edits survive regeneration. See ARCHITECTURE.md §2.3, §4."""

import re

_PINNED_RE = re.compile(
    r"<!-- pinned -->\n(.*?)<!-- /pinned -->",
    re.DOTALL,
)


def extract(existing: str) -> list[str]:
    """Return the contents of all <!-- pinned --> blocks in an existing materialized file."""
    return [m.group(1) for m in _PINNED_RE.finditer(existing)]


def merge(rendered: str, pinned_blocks: list[str]) -> str:
    """Merge pinned blocks back into a freshly rendered output."""
    if not pinned_blocks:
        return rendered
    suffix = "\n".join(
        f"<!-- pinned -->\n{block}<!-- /pinned -->" for block in pinned_blocks
    )
    return rendered.rstrip() + "\n\n" + suffix + "\n"
