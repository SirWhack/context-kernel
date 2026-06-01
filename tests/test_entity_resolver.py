"""Unit tests for the code-anchored EntityResolver (ADR-0017). Deterministic, no I/O."""

from context_kernel.ingester.entity_resolver import (
    ExtractedEntity, ExtractedRelationship, normalize, resolve,
)


def E(name, kind, src, emb=None, desc="d"):
    return ExtractedEntity(name=name, kind=kind, source_file=src, description=desc, embedding=emb)


def test_normalize_conservative():
    assert normalize("StepPanel") == "steppanel"
    assert normalize("Turn Panel") == normalize("turn_panel") == "turnpanel"
    assert normalize("Circuit breaker") == normalize("circuit_breaker") == "circuitbreaker"
    # conservative: 'Protocol' is NOT stripped
    assert normalize("StepPanel Protocol") == "steppanelprotocol"


def test_unambiguous_merge_spans_code_and_docs():
    ents = [
        E("TurnPanelResponder", "class", "src/bot/turn_panel.py"),
        E("TurnPanelResponder", "workflow", "docs/16-step-panel.md"),
        E("TurnPanelResponder", "interface", "docs/adr/0012.md"),
    ]
    nodes, edges, stats = resolve(ents, [])
    assert len(nodes) == 1
    n = nodes[0]
    assert n.is_code is True                       # code-anchored
    assert n.kind == "class"
    assert set(n.sources) == {"src/bot/turn_panel.py", "docs/16-step-panel.md", "docs/adr/0012.md"}
    assert stats["code_and_doc_nodes"] == 1


def test_expanded_structured_handlers_count_as_code():
    ents = [
        E("Game", "struct", "src/game.rs"),
        E("Game", "interface", "docs/design.md"),
        E("Api", "type", "schema/api.graphql"),
        E("Api", "interface", "docs/api.md"),
        E("Widget", "class", "web/widget.jsx"),
        E("Widget", "workflow", "docs/ui.md"),
    ]
    nodes, _edges, stats = resolve(ents, [])
    by_name = {n.name: n for n in nodes}
    assert by_name["Game"].is_code is True
    assert by_name["Api"].is_code is True
    assert by_name["Widget"].is_code is True
    assert stats["code_and_doc_nodes"] == 3


def test_collision_guard_keeps_distinct_code_defs_attaches_by_embedding():
    ents = [
        E("Client", "class", "a/client.py", emb=[1.0, 0.0, 0.0]),
        E("Client", "class", "b/client.py", emb=[0.0, 1.0, 0.0]),
        E("Client", "interface", "docs/a.md", emb=[0.95, 0.05, 0.0]),   # ~ matches a/
        E("Client", "interface", "docs/none.md", emb=[0.0, 0.0, 1.0]),  # matches neither
    ]
    nodes, edges, stats = resolve(ents, [], similarity_threshold=0.82)
    by_src = {tuple(sorted(n.sources)): n for n in nodes}
    # two distinct code defs survive; docs/a.md folds into a/client.py; docs/none.md is its own concept
    assert ("a/client.py", "docs/a.md") in by_src
    assert ("b/client.py",) in by_src
    assert any(n.sources == ["docs/none.md"] and not n.is_code for n in nodes)
    assert stats["ambiguous_names"] == 1


def test_relationship_resolves_across_files_after_merge():
    ents = [
        E("TurnPanelResponder", "class", "src/bot/turn_panel.py"),
        E("TurnPanelResponder", "workflow", "docs/16.md"),
        E("StepPanel", "class", "src/bot/step_panel.py"),
        E("StepPanel", "interface", "docs/16.md"),
    ]
    # edge authored in the doc chunk, naming two code symbols
    rels = [ExtractedRelationship("TurnPanelResponder", "StepPanel", "realizes", "docs/16.md")]
    nodes, edges, stats = resolve(ents, rels)
    assert len(edges) == 1
    ids = {n.id for n in nodes}
    assert edges[0].source_id in ids and edges[0].target_id in ids
    assert stats["cross_altitude_edges"] == 1     # both endpoints are code+doc nodes


def test_unresolvable_endpoint_is_dropped_not_phantomed():
    ents = [E("StepPanel", "class", "src/bot/step_panel.py")]
    rels = [
        ExtractedRelationship("StepPanel", "some narrative phrase", "mentions", "docs/16.md"),
        ExtractedRelationship("StepPanel", "StepPanel", "self", "src/bot/step_panel.py"),  # self-loop
    ]
    nodes, edges, stats = resolve(ents, rels)
    assert edges == []
    assert stats["dropped_edges"] == 2


def test_file_path_target_resolves_to_module_node():
    ents = [
        E("agent", "module", "src/bot/agent.py"),
        E("TicketBotAgent", "class", "src/bot/agent.py"),
        E("agentic RAG", "decision", "docs/02-agent-loop.md"),
    ]
    rels = [
        ExtractedRelationship("agentic RAG", "src/bot/agent.py", "realizes", "docs/02-agent-loop.md"),
        ExtractedRelationship("agentic RAG", "agent.py", "mentions", "docs/02-agent-loop.md"),  # basename
    ]
    nodes, edges, stats = resolve(ents, rels)
    module = next(n for n in nodes if n.kind == "module")
    assert {e.target_id for e in edges} == {module.id}   # both path forms hit the module node
    assert len(edges) == 2


def test_stoplist_names_never_merge_across_files():
    ents = [
        E("__init__", "function", "a/x.py"),
        E("__init__", "function", "b/y.py"),
        E("main", "function", "c/z.py"),
    ]
    nodes, _, _ = resolve(ents, [])
    assert len(nodes) == 3                          # each stays local


def R(src, tgt, kind="imports", src_file="vec/factory.py"):
    return ExtractedRelationship(source_name=src, target_name=tgt, kind=kind, source_file=src_file)


class TestDottedImportResolution:
    """`from pkg.mod import Thing` emits target 'pkg.mod.Thing'; the whole dotted path never
    matched a bare entity name, so internal dependency edges were dropped wholesale and the
    graph went ~95% edgeless (regression for ADR-0021 first-class structural edges)."""

    def test_resolves_to_imported_symbol_last_segment(self):
        ents = [E("factory", "module", "vec/factory.py"),
                E("VectorDBBase", "class", "vec/main.py")]
        rels = [R("factory", "open_webui.retrieval.vector.main.VectorDBBase")]
        nodes, edges, _ = resolve(ents, rels)
        ids = {n.id for n in nodes}
        assert len(edges) == 1 and edges[0].kind == "imports"
        assert edges[0].source_id in ids and edges[0].target_id in ids

    def test_resolves_to_module_penultimate_segment(self):
        ents = [E("factory", "module", "vec/factory.py"),
                E("settings", "module", "vec/settings.py")]
        rels = [R("factory", "open_webui.settings")]  # last seg 'settings' = the module
        _, edges, _ = resolve(ents, rels)
        assert len(edges) == 1

    def test_external_import_is_dropped(self):
        ents = [E("factory", "module", "vec/factory.py")]
        rels = [R("factory", "fastapi.APIRouter")]   # no internal entity → correctly dropped
        _, edges, _ = resolve(ents, rels)
        assert edges == []

    def test_relative_import_all_dots_does_not_crash(self):
        # `from . import x` / `from .. import y` emit an all-dots target with no non-empty
        # segment; indexing segs[-1] unguarded raised IndexError and crashed the whole ingest
        # (and, with rm-state-first, wiped the graph). Must drop the edge, not raise.
        ents = [E("factory", "module", "vec/factory.py")]
        for dots in (".", "..", "..."):
            _, edges, _ = resolve(ents, [R("factory", dots)])
            assert edges == []

    def test_ambiguous_symbol_not_guessed(self):
        # 'Client' defined in two files → ambiguous base → a dotted import to it must NOT guess
        ents = [E("factory", "module", "vec/factory.py"),
                E("Client", "class", "a/client.py", emb=[1.0, 0.0]),
                E("Client", "class", "b/client.py", emb=[0.0, 1.0])]
        rels = [R("factory", "somepkg.Client")]
        _, edges, _ = resolve(ents, rels)
        assert edges == []
