"""The ontology — the kernel's declarative type system (ADR-0024, ADR-0025).

The vocabulary (node/edge kinds, families) plus policy (weights/tiers), projection
(path→tier), and the concept schema + instances. ADR-0025 distributes it across a
**shipped base** (this package's `ontology.base.yaml`) and **per-project overlays**,
composed at ingest by `compose_ontology` under the rule *global meaning, local binding*:

- structural kinds — base-only, closed (parsers emit them).
- semantic kinds   — base + per-project ADD (definitions feed the prompt); no redefining.
- policy           — base-only (run-scoped overrides stay in config.toml / CK_SCORING_*).
- projection       — per-project bindings → global tiers.
- concepts         — instances in overlays; portfolio overlay → global hubs, project
                     overlay → project-scoped. The base declares the concept *type schema*.

This module does file I/O (it is **not** `scoring.py`, which stays pure) and never raises:
a missing/malformed file or absent base yields `None`/empty and consumers fall back to
their hardcoded defaults — the errors-out-of-existence contract.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

import yaml

log = logging.getLogger(__name__)

# Reserved kernel files — declarative input, never ingested as source content.
ONTOLOGY_BASENAMES = frozenset(
    {"ontology.yaml", "ontology.yml", "ontology.toml", "ontology.base.yaml"}
)

# Families and their posture (ADR-0024 §1):
STRUCTURAL = "structural"  # parser-derived, literal, CLOSED — the LLM never emits these
SEMANTIC = "semantic"      # LLM-inferred, ADVISORY — definitions feed the extraction prompt
CONCEPT = "concept"        # deterministic alias grounding, CLOSED

# Concept locality (ADR-0025 §1): where an instance is declared sets its scope by default.
SCOPE_PORTFOLIO = "portfolio"  # one cross-repo hub (project=null bridge)
SCOPE_PROJECT = "project"      # per-project node


@dataclass(frozen=True)
class Kind:
    """One node or edge kind. `weight`/`centrality` are POLICY annotations (edges only)."""

    name: str
    family: str
    definition: str = ""
    weight: float | None = None
    centrality: bool = False
    prompt: bool = True


@dataclass(frozen=True)
class ConceptType:
    """A concept *type* (the schema): how instances of it ground and what edge they emit."""

    name: str            # "entity" | "aspect"
    grounding: str       # "alias-match" | "recall-then-judge"
    emits: str = ""      # edge kind minted on a match


@dataclass(frozen=True)
class Concept:
    """A concept *instance* (the data). `scope` resolves at composition from its source layer."""

    key: str
    type: str            # references a ConceptType.name
    pref_label: str
    alt_labels: tuple[str, ...] = ()
    definition: str = ""
    scope: str | None = None       # None until compose assigns by layer (or an explicit override)
    recall_keywords: tuple[str, ...] = ()
    structural_patterns: tuple[str, ...] = ()
    source_path: str | None = None  # the overlay file this instance came from (provenance/tier)


@dataclass(frozen=True)
class Ontology:
    version: int
    nodes: tuple[Kind, ...]
    edges: tuple[Kind, ...]
    content_hash: str
    source_path: str | None = None
    concept_types: tuple[ConceptType, ...] = ()
    concepts: tuple[Concept, ...] = ()

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
    """Locate an overlay `ontology.yaml` under `root` or its `.context-kernel/`. None if absent."""
    for cand in (
        root / "ontology.yaml",
        root / "ontology.yml",
        root / ".context-kernel" / "ontology.yaml",
        root / ".context-kernel" / "ontology.yml",
    ):
        if cand.exists():
            return cand
    return None


def _as_tuple(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    if isinstance(value, list):
        return tuple(str(v) for v in value)
    return ()


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


def _concept_type_from(name: str, raw: dict) -> ConceptType | None:
    if not isinstance(raw, dict):
        return None
    return ConceptType(
        name=str(name).strip(),
        grounding=str(raw.get("grounding", "")).strip(),
        emits=str(raw.get("emits", "")).strip(),
    )


def _concept_from(key: str, raw: dict, source_path: str | None) -> Concept | None:
    if not isinstance(raw, dict):
        return None
    label = str(raw.get("prefLabel") or raw.get("label") or key)
    scope = raw.get("scope")
    return Concept(
        key=str(key).strip(),
        type=str(raw.get("type", "entity")).strip().lower(),
        pref_label=label,
        alt_labels=_as_tuple(raw.get("altLabel", raw.get("aliases", []))),
        definition=str(raw.get("definition", raw.get("scopeNote", ""))),
        scope=str(scope).strip().lower() if scope else None,
        recall_keywords=_as_tuple(raw.get("recall_keywords", [])),
        structural_patterns=_as_tuple(raw.get("structural_patterns", [])),
        source_path=source_path,
    )


def _parse(raw_bytes: bytes, *, source_path: str | None) -> Ontology | None:
    try:
        data = yaml.safe_load(raw_bytes.decode("utf-8")) or {}
    except yaml.YAMLError:
        log.warning("ontology at %s is not valid YAML; falling back to defaults", source_path)
        return None
    if not isinstance(data, dict):
        return None

    nodes = tuple(
        k for k in (_kind_from(n, edge=False) for n in data.get("nodes", []) if isinstance(n, dict)) if k
    )
    edges = tuple(
        k for k in (_kind_from(e, edge=True) for e in data.get("edges", []) if isinstance(e, dict)) if k
    )
    ctypes_raw = data.get("concept_types", {})
    concept_types = tuple(
        ct for ct in (
            _concept_type_from(name, raw) for name, raw in
            (ctypes_raw.items() if isinstance(ctypes_raw, dict) else [])
        ) if ct
    )
    concepts_raw = data.get("concepts", {})
    concepts = tuple(
        c for c in (
            _concept_from(key, raw, source_path) for key, raw in
            (concepts_raw.items() if isinstance(concepts_raw, dict) else [])
        ) if c
    )
    if not nodes and not edges and not concepts:
        return None

    return Ontology(
        version=int(data.get("version", 1)),
        nodes=nodes,
        edges=edges,
        content_hash=hashlib.sha256(raw_bytes).hexdigest(),
        source_path=source_path,
        concept_types=concept_types,
        concepts=concepts,
    )


def load_ontology(root: Path) -> Ontology | None:
    """Load an overlay `ontology.yaml` from `root` (or its `.context-kernel/`). None if absent.

    The `content_hash` is over the raw bytes, so any edit (including comments) invalidates
    derived artifacts — intentional, and the file is also walked into the source tree, so its
    byte-identity already gates `graph_commit`.
    """
    path = find_ontology(root)
    if path is None:
        return None
    return _parse(path.read_bytes(), source_path=path.name)


def load_base_ontology() -> Ontology | None:
    """Load the base ontology that ships inside the kernel package (ADR-0025 §3)."""
    import importlib.resources as ir

    try:
        ref = ir.files("context_kernel").joinpath("ontology.base.yaml")
        raw = ref.read_bytes()
    except (FileNotFoundError, ModuleNotFoundError, OSError):
        log.warning("packaged ontology.base.yaml not found; falling back to hardcoded defaults")
        return None
    return _parse(raw, source_path="ontology.base.yaml")


def _merge(base: Ontology, overlays: list[tuple[str, Ontology]]) -> Ontology:
    """Compose base ⊕ overlays per the ADR-0025 merge table. `overlays` is [(scope, ont), …]
    where scope is SCOPE_PORTFOLIO or SCOPE_PROJECT, applied in order."""
    # Vocabulary: structural is base-only (locked); semantic is union-add, base def wins.
    nodes_by_name = {k.name: k for k in base.nodes}
    edges_by_name = {k.name: k for k in base.edges}
    concept_types = {ct.name: ct for ct in base.concept_types}
    concepts: dict[tuple[str | None, str], Concept] = {}

    def _add_kinds(into: dict[str, Kind], incoming: tuple[Kind, ...], *, layer: str):
        for k in incoming:
            if k.family == STRUCTURAL:
                log.debug("ontology overlay %s declares structural kind %r — ignored (base-only)", layer, k.name)
                continue
            if k.name in into:
                continue  # never redefine a base/earlier kind (would diverge extraction)
            into[k.name] = k

    for scope, ont in overlays:
        _add_kinds(nodes_by_name, ont.nodes, layer=scope)
        _add_kinds(edges_by_name, ont.edges, layer=scope)
        # concept_types are base-only schema; overlay declarations are ignored.
        for ct in ont.concept_types:
            log.debug("ontology overlay %s declares concept_type %r — ignored (base-only)", scope, ct.name)
        for c in ont.concepts:
            resolved = c.scope or scope  # explicit scope wins, else inherit the layer's locality
            tagged = Concept(
                key=c.key, type=c.type, pref_label=c.pref_label, alt_labels=c.alt_labels,
                definition=c.definition, scope=resolved,
                recall_keywords=c.recall_keywords, structural_patterns=c.structural_patterns,
                source_path=c.source_path,
            )
            ns = None if resolved == SCOPE_PORTFOLIO else scope
            concepts[(ns, c.key)] = tagged  # later overlay wins for same (namespace, key)

    combined = hashlib.sha256(
        "|".join([base.content_hash, *(o.content_hash for _, o in overlays)]).encode()
    ).hexdigest()
    return Ontology(
        version=base.version,
        nodes=tuple(nodes_by_name.values()),
        edges=tuple(edges_by_name.values()),
        content_hash=combined,
        source_path=base.source_path,
        concept_types=tuple(concept_types.values()),
        concepts=tuple(concepts.values()),
    )


def compose_ontology(portfolio_root: Path, project_root: Path | None = None) -> Ontology | None:
    """Effective ontology for a project: base ⊕ portfolio overlay ⊕ project overlay (ADR-0025).

    Returns the base alone when no overlays exist, or `None` only if even the packaged base is
    missing (then consumers fall back to hardcoded defaults). Concept locality is set by layer:
    portfolio-overlay concepts become cross-repo hubs, project-overlay concepts stay scoped.
    """
    base = load_base_ontology()
    overlays: list[tuple[str, Ontology]] = []

    portfolio_overlay = load_ontology(portfolio_root)
    if portfolio_overlay is not None:
        overlays.append((SCOPE_PORTFOLIO, portfolio_overlay))

    if project_root is not None and project_root.resolve() != portfolio_root.resolve():
        project_overlay = load_ontology(project_root)
        if project_overlay is not None:
            overlays.append((SCOPE_PROJECT, project_overlay))

    if base is None:
        # No packaged base: degrade to the lone portfolio overlay if present, else nothing.
        if not overlays:
            return None
        first_scope, first = overlays[0]
        return _merge(first, overlays[1:])

    return _merge(base, overlays)
