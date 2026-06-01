"""Tests for the graph export transform (`ck graph`). See context_kernel/graph_export.py."""

from pathlib import Path

from context_kernel.config_store import (
    Config,
    IngesterConfig,
    MaterializerConfig,
    OrientationConfig,
    ProjectSpec,
)
from context_kernel.graph.protocol import Entity, Relationship
from context_kernel.graph_export import SCHEMA_VERSION, build_graph_export
from context_kernel.types import GraphCommit, ScopePath


class _Store:
    """Minimal KnowledgeStore exposing only what build_graph_export reads."""

    def __init__(self, scope_entities, relationships, commit="abcd1234"):
        self._scope_entities = scope_entities
        self._relationships = relationships
        self._commit = commit

    def graph_commit(self) -> GraphCommit:
        return GraphCommit(self._commit)

    def list_entities_by_scope(self):
        return dict(self._scope_entities)

    def list_relationships(self):
        return list(self._relationships)


def _scope(s: str) -> ScopePath:
    return ScopePath(Path(s))


def _cfg(*project_names: str, portfolio_root: Path = Path(".")) -> Config:
    return Config(
        ingester=IngesterConfig(),
        materializer=MaterializerConfig(),
        orientation=OrientationConfig(),
        portfolio_root=portfolio_root,
        projects=[ProjectSpec(path=Path(n)) for n in project_names],
    )


def _entity(eid, name, kind="function", sources=(), kinds=(), confidence=1.0):
    return Entity(
        id=eid, name=name, kind=kind, description=f"desc {name}",
        sources=tuple(sources), kinds=tuple(kinds), confidence=confidence,
    )


def _two_projects_with_hub():
    """projA/foo.py:Foo and projB/bar.py:Bar, bridged by a global 'panel' concept hub."""
    foo = _entity("id-foo", "Foo", sources=("src/foo.py",))
    bar = _entity("id-bar", "Bar", sources=("src/bar.py",))
    hub = _entity("id-hub", "panel", kind="concept", kinds=("concept",))
    scope_entities = {
        _scope("projA/src"): [foo],
        _scope("projB/src"): [bar],
        _scope("."): [hub],
    }
    rels = [
        Relationship(source_id="id-hub", target_id="id-foo", kind="implemented-by", description=""),
        Relationship(source_id="id-hub", target_id="id-bar", kind="implemented-by", description=""),
    ]
    return _Store(scope_entities, rels), foo, bar, hub


def test_buckets_projects_and_marks_concept_hub():
    store, *_ = _two_projects_with_hub()
    data = build_graph_export(store, _cfg("projA", "projB"))

    assert data["schema_version"] == SCHEMA_VERSION
    assert data["graph_commit"] == "abcd1234"
    assert sorted(data["projects"]) == ["projA", "projB"]

    by_id = {n["id"]: n for n in data["nodes"]}
    assert by_id["id-foo"]["project"] == "projA"
    assert by_id["id-bar"]["project"] == "projB"
    assert by_id["id-hub"]["project"] is None
    assert by_id["id-hub"]["is_concept"] is True
    assert by_id["id-foo"]["is_concept"] is False

    paths = {f["path"] for f in data["files"]}
    assert "projA/src/foo.py" in paths
    assert "projB/src/bar.py" in paths


def test_project_filter_keeps_repo_plus_concept_hubs():
    store, *_ = _two_projects_with_hub()
    data = build_graph_export(store, _cfg("projA", "projB"), project="projA")

    ids = {n["id"] for n in data["nodes"]}
    assert ids == {"id-foo", "id-hub"}  # projB dropped, hub kept as bridge
    assert data["projects"] == ["projA"]

    # The hub→bar edge is dangling once projB is filtered out and must be dropped.
    edge_targets = {(e["source"], e["target"]) for e in data["edges"]}
    assert ("id-hub", "id-foo") in edge_targets
    assert ("id-hub", "id-bar") not in edge_targets


def test_cross_repo_flag():
    foo = _entity("id-foo", "Foo", sources=("src/foo.py",))
    bar = _entity("id-bar", "Bar", sources=("src/bar.py",))
    store = _Store(
        {_scope("projA/src"): [foo], _scope("projB/src"): [bar]},
        [
            # Direct code↔code across repos → cross_repo True.
            Relationship(source_id="id-foo", target_id="id-bar", kind="related", description=""),
        ],
    )
    data = build_graph_export(store, _cfg("projA", "projB"))
    assert data["edges"][0]["cross_repo"] is True

    # A hub edge has one null-project end, so it is not itself a cross_repo edge.
    store2, *_ = _two_projects_with_hub()
    data2 = build_graph_export(store2, _cfg("projA", "projB"))
    assert all(e["cross_repo"] is False for e in data2["edges"])


def test_single_project_portfolio_buckets_to_portfolio_name():
    # No declared sub-projects: scope keys are unprefixed (e.g. "src/bot"), so the first
    # segment is a top-level dir, NOT a repo. Every code/doc node maps to the one repo.
    foo = _entity("id-foo", "Foo", sources=("src/foo.py",))
    helper = _entity("id-helper", "Helper", sources=("evals/util.py",))
    store = _Store({_scope("src"): [foo], _scope("evals"): [helper]}, [])
    data = build_graph_export(store, _cfg(portfolio_root=Path("/tmp/Ticket Agent")))

    assert data["projects"] == ["Ticket Agent"]
    by_id = {n["id"]: n for n in data["nodes"]}
    # Nodes are grouped under the friendly repo label...
    assert by_id["id-foo"]["project"] == "Ticket Agent"
    assert by_id["id-helper"]["project"] == "Ticket Agent"
    # ...but file paths stay portfolio-relative and resolvable (no label prefix), because
    # a single-repo portfolio is rooted at the repo itself.
    assert {f["path"] for f in data["files"]} == {"src/foo.py", "evals/util.py"}
    assert all(f["project"] == "Ticket Agent" for f in data["files"])


def test_multi_source_entity_yields_multiple_file_nodes():
    multi = _entity("id-multi", "Widget", sources=("src/widget.py", "docs/widget.md"))
    store = _Store({_scope("projA/src"): [multi]}, [])
    data = build_graph_export(store, _cfg("projA"))

    files = {f["path"]: f for f in data["files"]}
    assert "projA/src/widget.py" in files
    assert "projA/docs/widget.md" in files
    for f in files.values():
        assert f["entity_ids"] == ["id-multi"]


def test_contains_edge_yields_parent_spine():
    """The containment spine: a module anchor is the file node; its members point to it."""
    mod = _entity("id-mod", "widget", kind="module", sources=("src/widget.py",))
    cls = _entity("id-cls", "Widget", kind="class", sources=("src/widget.py",))
    fn = _entity("id-fn", "build", kind="function", sources=("src/widget.py",))
    store = _Store(
        {_scope("projA/src"): [mod, cls, fn]},
        [
            Relationship(source_id="id-mod", target_id="id-cls", kind="contains", description=""),
            Relationship(source_id="id-mod", target_id="id-fn", kind="contains", description=""),
        ],
    )
    data = build_graph_export(store, _cfg("projA"))
    by_id = {n["id"]: n for n in data["nodes"]}

    # Members hang under the module anchor; the anchor itself has no parent.
    assert by_id["id-cls"]["parent"] == "id-mod"
    assert by_id["id-fn"]["parent"] == "id-mod"
    assert by_id["id-mod"]["parent"] is None
    # Every node carries its scope for the upper levels of the spine.
    assert by_id["id-cls"]["scope"] == "projA/src"

    # The file node is the module anchor entity, not a synthetic box.
    f = {f["path"]: f for f in data["files"]}["projA/src/widget.py"]
    assert f["anchor_id"] == "id-mod"
    assert f["scope"] == "projA/src"


def test_doc_file_has_no_anchor():
    """A markdown file has no structural anchor — anchor_id is None, spine still holds."""
    doc = _entity("id-doc", "Concept", kind="decision", sources=("docs/x.md",))
    store = _Store({_scope("projA/docs"): [doc]}, [])
    data = build_graph_export(store, _cfg("projA"))

    f = {f["path"]: f for f in data["files"]}["projA/docs/x.md"]
    assert f["anchor_id"] is None
    assert f["scope"] == "projA/docs"
    assert {n["id"]: n for n in data["nodes"]}["id-doc"]["parent"] is None
