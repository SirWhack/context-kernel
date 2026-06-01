"""Curated concept ontology grounding.

This is the production foothold for the THOUGHTS.md concept layer: entity
concepts are grounded deterministically by prefLabel/altLabel aliases. Aspect
classification and CodeSpan evidence remain separate, heavier passes.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from context_kernel.graph.protocol import Entity, Relationship
from context_kernel.ingester.entity_resolver import normalize
from context_kernel.ontology import SCOPE_PORTFOLIO, Ontology
from context_kernel.source_kinds import is_code_path


@dataclass(frozen=True)
class ConceptSpec:
    key: str
    pref_label: str
    concept_type: str
    alt_labels: tuple[str, ...]
    definition: str
    source_path: str
    scope: str = SCOPE_PORTFOLIO    # "portfolio" → cross-repo hub; "project" → scoped (ADR-0025)
    project: str | None = None      # the owning project for project-scoped concepts

    @property
    def aliases(self) -> tuple[str, ...]:
        return (self.pref_label, *self.alt_labels)

    @property
    def node_id(self) -> str:
        """Namespaced hub id: portfolio concepts share one id across repos (the bridge);
        project concepts are namespaced by project, so same-key concepts stay distinct."""
        namespace = "portfolio" if self.scope == SCOPE_PORTFOLIO else (self.project or "")
        return _hub_id(namespace, self.key)


def _hub_id(namespace: str, key: str) -> str:
    return hashlib.sha256(f"{namespace}|concept|{key}".encode()).hexdigest()


def concept_id(key: str) -> str:
    """Portfolio-namespaced hub id (the cross-repo bridge). Back-compat helper."""
    return _hub_id("portfolio", key)


def concepts_from_ontology(ontology: Ontology | None, *, project: str | None = None) -> list[ConceptSpec]:
    """Build grounding specs from a composed ontology's `concepts:` block (ADR-0025 §4).

    Replaces the old `ontology.toml` loader: concept INSTANCES now live in the per-project /
    portfolio overlay YAML, already tagged with locality by `compose_ontology`. `project` names
    the repo whose project-scoped concepts these are (used for hub-id namespacing)."""
    if ontology is None:
        return []
    specs: list[ConceptSpec] = []
    for c in ontology.concepts:
        scope = c.scope or SCOPE_PORTFOLIO
        specs.append(ConceptSpec(
            key=c.key,
            pref_label=c.pref_label,
            concept_type=c.type,
            alt_labels=c.alt_labels,
            definition=c.definition,
            source_path=c.source_path or "ontology.yaml",
            scope=scope,
            project=None if scope == SCOPE_PORTFOLIO else project,
        ))
    return specs


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

        cid = spec.node_id
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
