"""Reference doc pointers and gap detection for AGENTS.md. See ADR-0014."""

from __future__ import annotations

import os
import re
from pathlib import Path

from context_kernel.graph.protocol import Entity
from context_kernel.types import ScopePath

_CODE_KINDS = frozenset({"module", "class", "function"})
_FILE_RE = re.compile(r"^File:\s*(.+)$", re.MULTILINE)


def find_reference_doc(scope: ScopePath, tree_root: Path) -> Path | None:
    """Return the reference doc path if ``docs/reference/<scope-leaf>.md`` exists under *tree_root*."""
    leaf = Path(scope).name
    candidate = tree_root / "docs" / "reference" / f"{leaf}.md"
    return candidate if candidate.exists() else None


def detect_documentation_gap(
    scope: ScopePath,
    entities: list[Entity],
    tree_root: Path,
    *,
    threshold: int = 10,
) -> str | None:
    """Return a gap recommendation if the scope has high entity density but no reference doc."""
    code_entities = [e for e in entities if e.kind in _CODE_KINDS]
    if len(code_entities) < threshold:
        return None
    if find_reference_doc(scope, tree_root) is not None:
        return None

    files: set[str] = set()
    for e in code_entities:
        for m in _FILE_RE.finditer(e.description):
            files.add(m.group(1).strip())

    return render_gap_recommendation(scope, len(code_entities), max(len(files), 1))


def render_reference_pointer(ref_doc_path: Path, scope: ScopePath, tree_root: Path) -> str:
    """Render a ``## Reference documentation`` section with a relative link to the reference doc."""
    scope_dir = tree_root / scope
    rel = os.path.relpath(ref_doc_path, scope_dir)
    return (
        "## Reference documentation\n"
        "\n"
        f"For operational understanding of this subsystem, see [{ref_doc_path.name}]({rel}).\n"
    )


def render_gap_recommendation(scope: ScopePath, entity_count: int, file_count: int) -> str:
    """Render a ``## Recommended documentation`` section advising the operator to author a reference doc."""
    leaf = Path(scope).name
    return (
        "## Recommended documentation\n"
        "\n"
        f"This scope has {entity_count} code entities across {file_count} files "
        f"but no reference documentation. To create one: `/init-reference {leaf}`\n"
    )
