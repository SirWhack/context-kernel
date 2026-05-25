"""<!-- pinned --> block merge. The only place hand-edits survive regeneration. See ARCHITECTURE.md §2.3, §4."""

from __future__ import annotations

import dataclasses
import re

_PINNED_RE = re.compile(
    r"<!-- pinned(?::(\w[\w-]*))? -->\n(.*?)<!-- /pinned -->",
    re.DOTALL,
)

_OPEN_RE = re.compile(r"<!-- pinned(?::(\w[\w-]*))? -->")


@dataclasses.dataclass(frozen=True)
class PinnedBlock:
    label: str | None
    content: str


def _normalize_content(raw: str) -> str:
    """Strip leading/trailing blank lines, preserve internal structure."""
    lines = raw.split("\n")
    while lines and lines[0].strip() == "":
        lines.pop(0)
    while lines and lines[-1].strip() == "":
        lines.pop()
    return "\n".join(lines)


def extract(existing: str) -> tuple[list[PinnedBlock], list[str]]:
    """Extract all <!-- pinned --> blocks from a materialized file.

    Returns (blocks, warnings). Warnings cover malformed/duplicate/nested cases.
    """
    warnings: list[str] = []
    blocks: list[PinnedBlock] = []
    matched_spans: set[tuple[int, int]] = set()

    for m in _PINNED_RE.finditer(existing):
        label = m.group(1)
        content = _normalize_content(m.group(2))
        blocks.append(PinnedBlock(label=label, content=content))
        matched_spans.add((m.start(), m.end()))

    for m in _OPEN_RE.finditer(existing):
        in_matched = any(s <= m.start() < e for s, e in matched_spans)
        if not in_matched:
            label = m.group(1)
            tag = f"<!-- pinned:{label} -->" if label else "<!-- pinned -->"
            warnings.append(f"Unpaired pinned block tag: {tag} (content will be lost)")

    seen_labels: dict[str, int] = {}
    deduped: list[PinnedBlock] = []
    for block in blocks:
        if block.label is not None and block.label in seen_labels:
            prev_idx = seen_labels[block.label]
            deduped = [b for i, b in enumerate(deduped) if i != prev_idx]
            seen_labels = {b.label: i for i, b in enumerate(deduped) if b.label is not None}
            warnings.append(f"Duplicate pinned label '{block.label}': keeping last, discarding earlier")
        if block.label is not None:
            seen_labels[block.label] = len(deduped)
        deduped.append(block)

    return deduped, warnings


def merge(rendered: str, pinned_blocks: list[PinnedBlock]) -> str:
    """Merge pinned blocks back into a freshly rendered output."""
    if not pinned_blocks:
        return rendered
    parts = []
    for block in pinned_blocks:
        if block.label:
            tag = f"<!-- pinned:{block.label} -->"
        else:
            tag = "<!-- pinned -->"
        parts.append(f"{tag}\n{block.content}\n<!-- /pinned -->")
    suffix = "\n\n".join(parts)
    return rendered.rstrip() + "\n\n" + suffix + "\n"
