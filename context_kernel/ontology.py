"""The ontology — the kernel's declarative type system (ADR-0024).

Single source of truth for the **vocabulary**: the node and edge kinds the graph
speaks in, grouped into *families* that encode epistemics and the open/closed
posture. **Policy** (weights/tiers) and **projection** (path→tier rules) ride along
in the same file but are consumed by separate layers.

Phase 1 (ADR-0024) wires only the vocabulary: the LLM extraction prompt and the
kind-validation sets are derived from here instead of hardcoded in `summarizer.py`.
The `policy:` and `projection:` blocks are loaded but not yet authoritative —
`scoring.py` / `source_kinds.py` still own those (Phases 2–3).

This module does file I/O (it is **not** `scoring.py`, which stays pure). It never
raises on a missing or malformed file — a portfolio with no `ontology.yaml` returns
`None` and its consumers fall back to their hardcoded defaults, preserving the
errors-out-of-existence contract.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import yaml

log = logging.getLogger(__name__)

# Reserved kernel files — declarative input, never ingested as source content.
ONTOLOGY_BASENAMES = frozenset({"ontology.yaml", "ontology.yml", "ontology.toml"})

# Families and their posture (ADR-0024 §1):
STRUCTURAL = "structural"  # parser-derived, literal, CLOSED — the LLM never emits these
SEMANTIC = "semantic"      # LLM-inferred, ADVISORY — definitions feed the extraction prompt
CONCEPT = "concept"        # deterministic alias grounding, CLOSED


@dataclass(frozen=True)
class Kind:
    """One node or edge kind.

    `weight` / `centrality` are POLICY annotations carried on the term (edges only,
    OWL-annotation style). `prompt` controls whether a semantic kind appears as a
    bullet in the extraction prompt — a kind can be valid yet special-cased in the
    prompt's Rules section instead (e.g. `stale-claim`).
    """

    name: str
    family: str
    definition: str = ""
    weight: float | None = None
    centrality: bool = False
    prompt: bool = True


@dataclass(frozen=True)
class Ontology:
    version: int
    nodes: tuple[Kind, ...]
    edges: tuple[Kind, ...]
    content_hash: str
    source_path: str | None = None

    def _semantic(self, kinds: tuple[Kind, ...]) -> tuple[Kind, ...]:
        return tuple(k for k in kinds if k.family == SEMANTIC)

    def entity_kinds(self) -> frozenset[str]:
        """All semantic node kinds — the validation set (advisory: unknowns still accepted)."""
        return frozenset(k.name for k in self._semantic(self.nodes))

    def relationship_kinds(self) -> frozenset[str]:
        """All semantic edge kinds — the validation set."""
        return frozenset(k.name for k in self._semantic(self.edges))

    def entity_bullets(self) -> str:
        """Prompt bullets for the semantic node kinds flagged `prompt: true`."""
        return _bullets(k for k in self._semantic(self.nodes) if k.prompt)

    def relationship_bullets(self) -> str:
        """Prompt bullets for the semantic edge kinds flagged `prompt: true`."""
        return _bullets(k for k in self._semantic(self.edges) if k.prompt)


def _bullets(kinds: Iterable[Kind]) -> str:
    return "\n".join(f"- {k.name}: {k.definition}" for k in kinds)


def is_ontology_file(path: Path) -> bool:
    """True for the kernel's own declarative files — hashed into the commit, never extracted."""
    return path.name.lower() in ONTOLOGY_BASENAMES


def find_ontology(root: Path) -> Path | None:
    """Locate `ontology.yaml` under `root` or its `.context-kernel/`. None if absent."""
    for cand in (
        root / "ontology.yaml",
        root / "ontology.yml",
        root / ".context-kernel" / "ontology.yaml",
        root / ".context-kernel" / "ontology.yml",
    ):
        if cand.exists():
            return cand
    return None


def _kind_from(raw: dict, *, edge: bool) -> Kind | None:
    name = str(raw.get("kind", "")).strip()
    if not name:
        return None
    weight = raw.get("weight")
    return Kind(
        name=name,
        family=str(raw.get("family", "")).strip().lower(),
        definition=str(raw.get("definition", "")).strip(),
        weight=float(weight) if edge and weight is not None else None,
        centrality=bool(raw.get("centrality", False)) if edge else False,
        prompt=bool(raw.get("prompt", True)),
    )


def load_ontology(root: Path) -> Ontology | None:
    """Load `ontology.yaml` from `root` (or its `.context-kernel/`).

    Returns `None` if no file is found, the file is malformed, or it declares no
    kinds — every consumer treats `None` as "use the hardcoded defaults". The
    `content_hash` is over the raw bytes, so any edit (including comments) invalidates
    derived artifacts; this is intentional — the file is also walked into the source
    tree, so its byte-identity already gates `graph_commit`.
    """
    path = find_ontology(root)
    if path is None:
        return None
    raw_bytes = path.read_bytes()
    try:
        data = yaml.safe_load(raw_bytes.decode("utf-8")) or {}
    except yaml.YAMLError:
        log.warning("ontology.yaml at %s is not valid YAML; falling back to defaults", path)
        return None
    if not isinstance(data, dict):
        return None

    nodes = tuple(
        k for k in (_kind_from(n, edge=False) for n in data.get("nodes", []) if isinstance(n, dict)) if k
    )
    edges = tuple(
        k for k in (_kind_from(e, edge=True) for e in data.get("edges", []) if isinstance(e, dict)) if k
    )
    if not nodes and not edges:
        return None

    return Ontology(
        version=int(data.get("version", 1)),
        nodes=nodes,
        edges=edges,
        content_hash=hashlib.sha256(raw_bytes).hexdigest(),
        source_path=path.name,
    )
