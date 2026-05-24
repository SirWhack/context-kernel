"""Cross-module domain primitives. Types only; no behavior."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, NewType

# Opaque hash for a Graph state-in-time. See ARCHITECTURE.md §2.1.
GraphCommit = NewType("GraphCommit", str)

# 64-char hex digest used as content-addressed blob filename. See ARCHITECTURE.md §2.2.
Sha256 = NewType("Sha256", str)

# Portfolio-root-relative directory path; the unit of materialization. See ARCHITECTURE.md §2.3.
ScopePath = NewType("ScopePath", Path)


@dataclass(frozen=True)
class ViewSpec:
    """One configured [[view]] entry; rendered by the Materializer."""

    name: str
    kind: str
    params: dict[str, Any]
