"""Graph → JSON export for the VSCode visualizer (`ck graph`).

Pure transform, no I/O: turns a `KnowledgeStore` snapshot into a stable, versioned
graph document the extension can render. The shape is decoupled from the internal
`state.json` layout so the extension never depends on backend internals.

The node model is a **containment spine** for level-of-detail navigation: repo ⊃ scope ⊃
file ⊃ entity. The file→entity level is backed by the real `contains` edges (ADR-0021)
exposed as each node's `parent`; the file node is the `module` anchor entity itself
(`file.anchor_id`), not a synthetic box. The spine is orthogonal to the semantic
entity→entity `relationships`, which are the cross-links drawn between visible nodes.
Repos are kept separate —
entity IDs are project-namespaced, so no node is shared across repos. The only links
that cross a repo boundary run through global ontology **concept hubs** (`project`
is null), which the frontend renders as cross-repo bridges.
"""

from __future__ import annotations

from pathlib import PurePosixPath

from context_kernel.config_store import Config
from context_kernel.graph.protocol import Entity, KnowledgeStore

SCHEMA_VERSION = 2  # v2: added containment spine (node.scope/parent, file.anchor_id/scope)
# Scope key under which `_apply_concept_layer` files the global ontology concept hubs.
_CONCEPT_SCOPE = "."


def _is_concept(entity: Entity) -> bool:
    """A node bridges repos when it is an ontology concept rather than code/doc."""
    return entity.kind == "concept" or "concept" in entity.kinds


def _project_table(config: Config) -> list[dict]:
    """Ordered repos in this portfolio as {label, prefix}.

    `label` is the friendly repo name used for grouping/filtering. `prefix` is the
    portfolio-relative directory the repo lives in — joined to the portfolio root it must
    resolve to real files. A single-repo portfolio is rooted at the repo itself, so its
    prefix is "" (file paths are just the project-relative source). Declared sub-projects
    use their declared path as the prefix.
    """
    from pathlib import Path

    declared = [p for p in config.projects if p.name and p.path != Path(".")]
    if declared:
        return [{"label": p.name, "prefix": p.path.as_posix()} for p in declared]
    return [{"label": config.portfolio_root.name, "prefix": ""}]


def resolved_projects(config: Config) -> list[str]:
    """The repo labels the export buckets nodes into (used for the dropdown / --project)."""
    return [t["label"] for t in _project_table(config)]


def _entity_projects(config: Config, store: KnowledgeStore) -> dict[str, str | None]:
    """Map each entity id to its repo label (None = global concept hub).

    Only ontology concept hubs (`is_concept`) are cross-repo and get None. Every
    code/doc node belongs to a repo: in a multi-repo portfolio the scope key is
    project-prefixed (e.g. "model-time/src") and its first segment names the repo; in a
    single-repo portfolio scopes are unprefixed, so nodes map to the one repo label. The
    "." scope is overloaded — it holds the concept hubs *and* root-level doc entities —
    so root-doc nodes there fall back to the single repo label, not None. An entity seen
    under several scopes keeps its first real-repo label.
    """
    table = _project_table(config)
    declared_labels = {t["label"] for t in table if t["prefix"]}
    single_label = table[0]["label"]
    projects: dict[str, str | None] = {}
    for scope, entities in store.list_entities_by_scope().items():
        key = str(scope)
        if key == _CONCEPT_SCOPE:
            seg_project: str | None = None  # unknown from scope; resolve per-entity
        else:
            seg0 = PurePosixPath(key).parts[0]
            seg_project = seg0 if seg0 in declared_labels else single_label
        for entity in entities:
            if _is_concept(entity):
                # Locality is encoded by WHERE the concept is filed (ADR-0025 §3): portfolio
                # concepts live under the "." scope (seg_project None → cross-repo bridge);
                # project concepts are filed under their repo's scope → bucket into that repo.
                project = seg_project
            else:
                project = seg_project or single_label
            if entity.id not in projects:
                projects[entity.id] = project
            elif project is not None:
                # A real-repo label always overrides an earlier (or concurrent) None.
                projects[entity.id] = project
    return projects


def build_graph_export(
    store: KnowledgeStore,
    config: Config,
    *,
    project: str | None = None,
) -> dict:
    """Build the export document. If `project` is given, keep only that repo's nodes
    plus all concept hubs (so cross-repo bridges remain visible), then drop dangling edges."""
    project_of = _entity_projects(config, store)

    entities: dict[str, Entity] = {}
    for scope_entities in store.list_entities_by_scope().values():
        for entity in scope_entities:
            entities.setdefault(entity.id, entity)

    if project is not None:
        entities = {
            eid: e
            for eid, e in entities.items()
            if project_of.get(eid) == project or _is_concept(e)
        }

    # ── Containment spine (LOD navigation, orthogonal to the semantic edges) ──
    # Levels: repo (`project`) ⊃ scope ⊃ file/module-anchor ⊃ entity. The file→entity
    # level is backed by the real `contains` edges (ADR-0021); the upper levels are a
    # projection of scope + path. The resolver guarantees ≤1 code anchor per node, so
    # `parent` is single-valued and the spine is a tree. Nodes with no `contains` edge
    # (module anchors, concept hubs, doc-only entities) get parent=None and hang directly
    # under their scope. This is NOT the semantic graph — it controls collapse/expand only.
    parent_of: dict[str, str] = {}
    for rel in store.list_relationships():
        if rel.kind == "contains" and rel.source_id in entities and rel.target_id in entities:
            parent_of.setdefault(rel.target_id, rel.source_id)

    by_scope = store.list_entities_by_scope()
    scope_of: dict[str, str] = {}
    for scope in sorted(by_scope, key=str):
        for e in by_scope[scope]:
            scope_of.setdefault(e.id, str(scope))

    # The file node IS the `module` anchor entity (a real, scored, edge-participating
    # node) — not a synthetic scoreless box. (label, project-relative source) → anchor id.
    module_anchor: dict[tuple[str | None, str], str] = {}
    for e in entities.values():
        if e.kind == "module" or "module" in e.kinds:
            label = project_of.get(e.id)
            for s in e.sources:
                module_anchor.setdefault((label, s), e.id)

    nodes = [
        {
            "id": e.id,
            "name": e.name,
            "kind": e.kind,
            "project": project_of.get(e.id),
            "scope": scope_of.get(e.id),
            "parent": parent_of.get(e.id),
            "sources": list(e.sources),
            "is_concept": _is_concept(e),
            "confidence": e.confidence,
            "centrality": e.centrality,
            "source_tier": e.source_tier,
            "description": e.description,
        }
        for e in entities.values()
    ]

    # File nodes: `path` is portfolio-relative and resolvable (prefix + project-relative
    # source), while `project` is the friendly label used for grouping/filtering. A node
    # with both code and doc sources contributes to several files (expected). Concept hubs
    # (label None) have no files.
    prefix_of = {t["label"]: t["prefix"] for t in _project_table(config)}
    files: dict[str, dict] = {}
    for e in entities.values():
        label = project_of.get(e.id)
        if label is None:
            continue
        prefix = prefix_of.get(label, "")
        for src in e.sources:
            path = f"{prefix}/{src}" if prefix else src
            entry = files.setdefault(path, {
                "path": path,
                "project": label,
                # `anchor_id` ties the file to its `module` entity — the scored node that
                # represents this file when its entities are collapsed. None for doc/markdown
                # files, which have no structural anchor.
                "anchor_id": module_anchor.get((label, src)),
                "scope": None,
                "entity_ids": [],
            })
            entry["entity_ids"].append(e.id)
    for entry in files.values():
        anchor = entry["anchor_id"]
        entry["scope"] = (
            scope_of.get(anchor) if anchor
            else (scope_of.get(entry["entity_ids"][0]) if entry["entity_ids"] else None)
        )

    edges = []
    for rel in store.list_relationships():
        if rel.source_id not in entities or rel.target_id not in entities:
            continue
        src_proj = project_of.get(rel.source_id)
        tgt_proj = project_of.get(rel.target_id)
        cross_repo = src_proj is not None and tgt_proj is not None and src_proj != tgt_proj
        edges.append(
            {
                "source": rel.source_id,
                "target": rel.target_id,
                "kind": rel.kind,
                "weight": rel.weight,
                "drift": rel.drift,
                "cross_repo": cross_repo,
            }
        )

    project_names = resolved_projects(config)
    if project is not None:
        project_names = [n for n in project_names if n == project]

    return {
        "schema_version": SCHEMA_VERSION,
        "graph_commit": str(store.graph_commit()),
        "projects": project_names,
        "files": list(files.values()),
        "nodes": nodes,
        "edges": edges,
    }
