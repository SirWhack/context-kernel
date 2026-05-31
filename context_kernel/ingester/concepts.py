"""Curated concept ontology grounding.

This is the production foothold for the THOUGHTS.md concept layer: entity
concepts are grounded deterministically by prefLabel/altLabel aliases. Aspect
classification and CodeSpan evidence remain separate, heavier passes.
"""

from __future__ import annotations

import hashlib
import tomllib
from dataclasses import dataclass
from pathlib import Path

from context_kernel.graph.protocol import Entity, Relationship
from context_kernel.ingester.entity_resolver import normalize
from context_kernel.source_kinds import is_code_path


@dataclass(frozen=True)
class ConceptSpec:
    key: str
    pref_label: str
    concept_type: str
    alt_labels: tuple[str, ...]
    definition: str
    source_path: str

    @property
    def aliases(self) -> tuple[str, ...]:
        return (self.pref_label, *self.alt_labels)


def _as_list(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    if isinstance(value, list):
        return tuple(str(v) for v in value)
    return ()


def load_ontology(portfolio_root: Path) -> tuple[Path | None, list[ConceptSpec]]:
    """Load `[concepts.<key>]` from `ontology.toml` or `.context-kernel/ontology.toml`."""
    candidates = [
        portfolio_root / "ontology.toml",
        portfolio_root / ".context-kernel" / "ontology.toml",
    ]
    path = next((p for p in candidates if p.exists()), None)
    if path is None:
        return None, []

    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    concepts = raw.get("concepts", {})
    if not isinstance(concepts, dict):
        return path, []

    rel = path.relative_to(portfolio_root).as_posix()
    specs: list[ConceptSpec] = []
    for key, spec in concepts.items():
        if not isinstance(spec, dict):
            continue
        label = str(spec.get("prefLabel") or spec.get("label") or key)
        specs.append(ConceptSpec(
            key=str(key),
            pref_label=label,
            concept_type=str(spec.get("type", "entity")).lower(),
            alt_labels=_as_list(spec.get("altLabel", spec.get("aliases", []))),
            definition=str(spec.get("definition", spec.get("scopeNote", ""))),
            source_path=rel,
        ))
    return path, specs


def concept_id(key: str) -> str:
    return hashlib.sha256(f"portfolio|concept|{key}".encode()).hexdigest()


def ground_entity_concepts(
    entities: list[Entity],
    specs: list[ConceptSpec],
) -> tuple[list[Entity], list[Relationship]]:
    """Create concept hub nodes and `implemented-by` edges for alias-matched code entities."""
    code_entities = [
        e for e in entities
        if e.kind != "concept" and any(is_code_path(src) for src in e.sources)
    ]
    out_entities: list[Entity] = []
    out_relationships: list[Relationship] = []
    seen_edges: set[tuple[str, str]] = set()

    for spec in specs:
        if spec.concept_type != "entity":
            continue
        alias_keys = {normalize(alias) for alias in spec.aliases if normalize(alias)}
        if not alias_keys:
            continue

        hits = [
            e for e in code_entities
            if normalize(e.name) in alias_keys
            or any(normalize(alias) in alias_keys for alias in e.aliases)
        ]
        if not hits:
            continue

        cid = concept_id(spec.key)
        alias_text = ", ".join(spec.alt_labels) if spec.alt_labels else "(none)"
        definition = spec.definition or f"Curated entity concept for {spec.pref_label}."
        desc = (
            f"Concept: {spec.pref_label}\n"
            f"  Type: entity\n"
            f"  Definition: {definition}\n"
            f"  Aliases: {alias_text}\n"
            f"  Grounding: deterministic ontology alias match"
        )
        out_entities.append(Entity(
            id=cid,
            name=spec.pref_label,
            kind="concept",
            description=desc,
            aliases=spec.aliases,
            sources=(spec.source_path,),
            kinds=("concept", "entity-concept"),
        ))

        for hit in hits:
            key = (cid, hit.id)
            if key in seen_edges:
                continue
            seen_edges.add(key)
            out_relationships.append(Relationship(
                source_id=cid,
                target_id=hit.id,
                kind="implemented-by",
                description=f"{spec.pref_label} is implemented by {hit.name}",
            ))

    return out_entities, out_relationships
