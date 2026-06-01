"""Curated concept ontology grounding.

This is the production foothold for the THOUGHTS.md concept layer: entity
concepts are grounded deterministically by prefLabel/altLabel aliases. Aspect
classification and CodeSpan evidence remain separate, heavier passes.
"""

from __future__ import annotations

import hashlib
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from context_kernel.graph.protocol import Entity, Relationship
from context_kernel.ingester.entity_resolver import normalize
from context_kernel.ontology import SCOPE_PORTFOLIO, Ontology
from context_kernel.source_kinds import is_code_path

log = logging.getLogger(__name__)


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
    recall_keywords: tuple[str, ...] = ()       # aspect recall (substring) — ADR-0025 §4
    structural_patterns: tuple[str, ...] = ()   # aspect recall (regex)

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
    # `|concept-hub|`, NOT `|concept|`: the EntityResolver mints ordinary doc-entity ids as
    # sha256(f"{project}|concept|{normalize(name)}") (entity_resolver._concept_id). A curated
    # concept key that normalizes to a doc entity's name (e.g. "session", "dataset") would
    # otherwise collide, and _apply_concept_layer's dedup guard would silently drop the hub.
    return hashlib.sha256(f"{namespace}|concept-hub|{key}".encode()).hexdigest()


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
            recall_keywords=c.recall_keywords,
            structural_patterns=c.structural_patterns,
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

    # Entity-concepts ground by deterministic alias-match here; aspect-concepts are handled
    # separately by ground_aspect_concepts (recall-then-judge, ADR-0025 §4).
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


# AspectJudge(aspect_label, definition, candidate_name, candidate_evidence) -> bool.
# The LLM-backed judge lives behind the Summarizer Parnas-secret; tests pass a fake.
AspectJudge = Callable[[str, str, str, str], bool]


def _recall_candidates(code_entities: list[Entity], spec: ConceptSpec) -> list[Entity]:
    """Coarse, high-recall gather for an aspect: a code entity is a candidate if its
    name+description contains any recall_keyword (substring) or matches any structural_pattern
    (regex). Matched against entity text, not raw source — patterns tuned for source lines will
    under-match here; the judge supplies precision regardless (recall-only precision was 0.35
    in the spike). Bad regexes are skipped, never raised."""
    keywords = [k.lower() for k in spec.recall_keywords if k]
    patterns = []
    for p in spec.structural_patterns:
        try:
            patterns.append(re.compile(p))
        except re.error:
            log.debug("aspect %s: skipping invalid structural_pattern %r", spec.key, p)
    if not keywords and not patterns:
        return []
    hits: list[Entity] = []
    for e in code_entities:
        haystack = f"{e.name}\n{e.description}"
        low = haystack.lower()
        if any(k in low for k in keywords) or any(p.search(haystack) for p in patterns):
            hits.append(e)
    return hits


def ground_aspect_concepts(
    entities: list[Entity],
    specs: list[ConceptSpec],
    judge: AspectJudge,
    *,
    max_candidates: int = 200,
    max_workers: int = 8,
) -> tuple[list[Entity], list[Relationship]]:
    """Recall-then-judge grounding for aspect-concepts (ADR-0025 §4).

    Recall gathers candidates cheaply; the LLM `judge` confirms each (precision). Judge calls
    are embarrassingly parallel and run on a bounded pool (the judge — LLMSummarizer.judge_aspect
    — is thread-safe and content-addressed). Confirmed candidates get a `manifested-by` edge from
    the aspect hub. Candidates are capped per aspect with a loud log (no silent truncation).
    Hubs/edges are returned UNSCORED — the caller scores them like entity-concepts."""
    code_entities = [
        e for e in entities
        if e.kind != "concept" and any(is_code_path(src) for src in e.sources)
    ]
    aspect_specs = [s for s in specs if s.concept_type == "aspect"]
    if not aspect_specs:
        return [], []

    # Recall per aspect (capped), then flatten to a single judge work-list.
    recalled: list[tuple[ConceptSpec, list[Entity]]] = []
    tasks: list[tuple[ConceptSpec, Entity]] = []
    for spec in aspect_specs:
        candidates = _recall_candidates(code_entities, spec)
        if len(candidates) > max_candidates:
            log.warning(
                "aspect %s: %d recall candidates capped to %d (raise max_candidates to judge all)",
                spec.key, len(candidates), max_candidates,
            )
            candidates = candidates[:max_candidates]
        recalled.append((spec, candidates))
        tasks.extend((spec, c) for c in candidates)

    if not tasks:
        return [], []

    def _run(task: tuple[ConceptSpec, Entity]) -> bool:
        spec, c = task
        return judge(spec.pref_label, spec.definition, c.name, c.description)

    with ThreadPoolExecutor(max_workers=max(1, max_workers)) as ex:
        verdicts = list(ex.map(_run, tasks))

    confirmed: dict[str, list[Entity]] = {}
    for (spec, c), ok in zip(tasks, verdicts):
        if ok:
            confirmed.setdefault(spec.key, []).append(c)

    out_entities: list[Entity] = []
    out_relationships: list[Relationship] = []
    for spec, candidates in recalled:
        hits = confirmed.get(spec.key, [])
        if not hits:
            continue
        cid = spec.node_id
        definition = spec.definition or f"Curated aspect concept for {spec.pref_label}."
        desc = (
            f"Concept: {spec.pref_label}\n"
            f"  Type: aspect\n"
            f"  Definition: {definition}\n"
            f"  Grounding: recall-then-judge ({len(hits)}/{len(candidates)} candidates confirmed)"
        )
        out_entities.append(Entity(
            id=cid,
            name=spec.pref_label,
            kind="concept",
            description=desc,
            aliases=spec.aliases,
            sources=(spec.source_path,),
            kinds=("concept", "aspect-concept"),
        ))
        for c in hits:
            out_relationships.append(Relationship(
                source_id=cid,
                target_id=c.id,
                kind="manifested-by",
                description=f"{spec.pref_label} is manifested by {c.name}",
            ))

    return out_entities, out_relationships
