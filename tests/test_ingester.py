"""Tests for the Ingester module. See ARCHITECTURE.md §2.2."""

from pathlib import Path

from context_kernel.graph.addressing import hash_bytes
from context_kernel.graph.protocol import EmbeddedChunk, Entity, Relationship, SearchResult, Summary
from context_kernel.ingester import ingest, ingest_portfolio
from context_kernel.ingester.blobs import write_embedding, write_summary
from context_kernel.change_detection import (
    changed_since,
    discover_scopes,
    source_tree_hash,
    walk_source_files,
)
from context_kernel.ingester.handlers import (
    ChunkHandler,
    MarkdownHandler,
    PythonHandler,
    RawEntity,
    RawRelationship,
    TypeScriptHandler,
)
from context_kernel.ingester.summarizer import (
    _SYSTEM_PROMPT,
    RELATIONSHIP_KINDS,
    _parse_llm_response,
)
from context_kernel.config_store import IngesterConfig
from context_kernel.types import GraphCommit, Sha256, ScopePath

import math
import struct


# ── PythonHandler ────────────────────────────────────────────────────────


class TestPythonHandlerSupports:
    def test_supports_py(self, tmp_path):
        h = PythonHandler()
        assert h.supports(tmp_path / "main.py")
        assert h.supports(tmp_path / "test_foo.py")

    def test_rejects_non_py(self, tmp_path):
        h = PythonHandler()
        assert not h.supports(tmp_path / "README.md")
        assert not h.supports(tmp_path / "style.css")
        assert not h.supports(tmp_path / "data.json")


class TestPythonHandlerExtract:
    def test_empty_file(self, tmp_path):
        f = tmp_path / "empty.py"
        f.write_text("")
        h = PythonHandler()
        entities, rels = h.extract(f)
        assert entities == []
        assert rels == []

    def test_syntax_error(self, tmp_path):
        f = tmp_path / "bad.py"
        f.write_text("def foo(:\n  pass")
        h = PythonHandler()
        entities, rels = h.extract(f)
        assert entities == []
        assert rels == []

    def test_module_entity(self, tmp_path):
        f = tmp_path / "example.py"
        f.write_text('"""Example module."""\nimport os\n\nX = 1\n')
        h = PythonHandler()
        entities, rels = h.extract(f)
        module_ents = [e for e in entities if e.kind == "module"]
        assert len(module_ents) == 1
        assert module_ents[0].name == "example"
        assert "Example module." in module_ents[0].description
        assert "os" in module_ents[0].description

    def test_class_entity(self, tmp_path):
        f = tmp_path / "models.py"
        f.write_text(
            '"""Models."""\n'
            "class Foo:\n"
            '    """A foo."""\n'
            "    def bar(self, x: int) -> str:\n"
            "        return str(x)\n"
            "    def _internal(self) -> None:\n"
            "        pass\n"
        )
        h = PythonHandler()
        entities, rels = h.extract(f)
        class_ents = [e for e in entities if e.kind == "class"]
        assert len(class_ents) == 1
        assert class_ents[0].name == "Foo"
        desc = class_ents[0].description
        assert "Interface:" in desc
        assert "bar(self, x: int) -> str" in desc
        assert "Internals:" in desc
        assert "_internal" in desc

    def test_function_entity(self, tmp_path):
        f = tmp_path / "utils.py"
        f.write_text(
            "def helper(x: int, y: str) -> bool:\n"
            "    return True\n"
        )
        h = PythonHandler()
        entities, rels = h.extract(f)
        func_ents = [e for e in entities if e.kind == "function"]
        assert len(func_ents) == 1
        assert func_ents[0].name == "helper"
        assert "helper(x: int, y: str) -> bool" in func_ents[0].description
        assert "public" in func_ents[0].description

    def test_private_function(self, tmp_path):
        f = tmp_path / "utils.py"
        f.write_text("def _secret() -> None:\n    pass\n")
        h = PythonHandler()
        entities, rels = h.extract(f)
        func_ents = [e for e in entities if e.kind == "function"]
        assert len(func_ents) == 1
        assert "private" in func_ents[0].description

    def test_depth_metrics(self, tmp_path):
        f = tmp_path / "deep.py"
        f.write_text(
            "class Deep:\n"
            "    def a(self) -> None:\n"
            "        pass\n"
            "    def b(self) -> None:\n"
            "        pass\n"
            "    def _c(self) -> None:\n"
            "        pass\n"
        )
        h = PythonHandler()
        entities, _ = h.extract(f)
        cls = [e for e in entities if e.kind == "class"][0]
        assert "2 public methods" in cls.description
        assert "1 private methods" in cls.description

    def test_inheritance_relationship(self, tmp_path):
        f = tmp_path / "child.py"
        f.write_text(
            "class Base:\n"
            "    pass\n"
            "class Child(Base):\n"
            "    pass\n"
        )
        h = PythonHandler()
        _, rels = h.extract(f)
        inherits = [r for r in rels if r.kind == "inherits"]
        assert len(inherits) == 1
        assert inherits[0].source_name == "Child"
        assert inherits[0].target_name == "Base"

    def test_import_relationships(self, tmp_path):
        f = tmp_path / "imp.py"
        f.write_text("from pathlib import Path\nimport os\n")
        h = PythonHandler()
        _, rels = h.extract(f)
        import_rels = [r for r in rels if r.kind == "imports"]
        names = {r.target_name for r in import_rels}
        assert "pathlib.Path" in names
        assert "os" in names

    def test_protocol_base_detection(self, tmp_path):
        f = tmp_path / "proto.py"
        f.write_text(
            "from typing import Protocol\n"
            "class Handler(Protocol):\n"
            "    def run(self) -> None: ...\n"
        )
        h = PythonHandler()
        entities, _ = h.extract(f)
        module_ent = [e for e in entities if e.kind == "module"][0]
        assert "Protocol" in module_ent.description
        cls_ent = [e for e in entities if e.kind == "class"][0]
        assert "Protocol" in cls_ent.description

    def test_ast_unparse_preserves_string_annotations(self, tmp_path):
        f = tmp_path / "fwd.py"
        f.write_text(
            'def process(config: "IngesterConfig") -> None:\n'
            "    pass\n"
        )
        h = PythonHandler()
        entities, _ = h.extract(f)
        func = [e for e in entities if e.kind == "function"][0]
        assert "'IngesterConfig'" in func.description

    def test_dunder_all_determines_exports(self, tmp_path):
        f = tmp_path / "pub.py"
        f.write_text(
            '__all__ = ["PublicClass"]\n'
            "class PublicClass:\n"
            "    pass\n"
            "class _InternalClass:\n"
            "    pass\n"
            "class UnlistedClass:\n"
            "    pass\n"
        )
        h = PythonHandler()
        entities, _ = h.extract(f)
        module_ent = [e for e in entities if e.kind == "module"][0]
        assert "PublicClass" in module_ent.description.split("Exports:")[1].split("Private:")[0]
        assert "UnlistedClass" not in module_ent.description.split("Exports:")[1].split("Private:")[0]

    def test_async_function(self, tmp_path):
        f = tmp_path / "async_mod.py"
        f.write_text(
            "async def fetch(url: str) -> bytes:\n"
            "    return b''\n"
        )
        h = PythonHandler()
        entities, _ = h.extract(f)
        func = [e for e in entities if e.kind == "function"][0]
        assert "fetch(url: str) -> bytes" in func.description

    def test_constants_in_module_preamble(self, tmp_path):
        f = tmp_path / "consts.py"
        f.write_text("_PRIVATE = 42\nPUBLIC = 99\n")
        h = PythonHandler()
        entities, _ = h.extract(f)
        module_ent = [e for e in entities if e.kind == "module"][0]
        assert "_PRIVATE" in module_ent.description
        assert "PUBLIC" in module_ent.description

    def test_deterministic_entity_ids(self, tmp_path):
        f = tmp_path / "det.py"
        f.write_text("class Stable:\n    pass\n")
        h = PythonHandler()
        e1, _ = h.extract(f)
        e2, _ = h.extract(f)
        assert [e.name for e in e1] == [e.name for e in e2]
        assert [e.description for e in e1] == [e.description for e in e2]


# ── TypeScriptHandler ───────────────────────────────────────────────────


class TestTypeScriptHandlerSupports:
    def test_supports_ts_extensions(self, tmp_path):
        h = TypeScriptHandler()
        for ext in [".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"]:
            assert h.supports(tmp_path / f"file{ext}"), f"should support {ext}"

    def test_rejects_non_ts(self, tmp_path):
        h = TypeScriptHandler()
        assert not h.supports(tmp_path / "main.py")
        assert not h.supports(tmp_path / "README.md")
        assert not h.supports(tmp_path / "data.json")


class TestTypeScriptHandlerExtract:
    def test_empty_file(self, tmp_path):
        f = tmp_path / "empty.ts"
        f.write_text("")
        h = TypeScriptHandler()
        entities, rels = h.extract(f)
        assert entities == []
        assert rels == []

    def test_module_entity(self, tmp_path):
        f = tmp_path / "app.ts"
        f.write_text(
            "import { Foo } from './foo';\n"
            "export class App {}\n"
            "const _internal = 42;\n"
        )
        h = TypeScriptHandler()
        entities, rels = h.extract(f)
        module_ents = [e for e in entities if e.kind == "module"]
        assert len(module_ents) == 1
        assert module_ents[0].name == "app"
        assert "App" in module_ents[0].description.split("Exports:")[1].split("Private:")[0]

    def test_class_entity(self, tmp_path):
        f = tmp_path / "service.ts"
        f.write_text(
            "export class MyService {\n"
            "    public name: string;\n"
            "    private _cache: Map<string, number>;\n"
            "    \n"
            "    constructor(name: string) {\n"
            "        this.name = name;\n"
            "    }\n"
            "    \n"
            "    run(x: number): Promise<void> {\n"
            "        return this._doWork(x);\n"
            "    }\n"
            "    \n"
            "    private _doWork(x: number): Promise<void> {\n"
            "        return Promise.resolve();\n"
            "    }\n"
            "}\n"
        )
        h = TypeScriptHandler()
        entities, rels = h.extract(f)
        class_ents = [e for e in entities if e.kind == "class"]
        assert len(class_ents) == 1
        assert class_ents[0].name == "MyService"
        desc = class_ents[0].description
        assert "Interface:" in desc
        assert "Internals:" in desc
        assert "_cache" in desc
        assert "_doWork" in desc

    def test_class_depth_metrics(self, tmp_path):
        f = tmp_path / "deep.ts"
        f.write_text(
            "export class Deep {\n"
            "    a(): void {}\n"
            "    b(): void {}\n"
            "    private _c(): void {}\n"
            "}\n"
        )
        h = TypeScriptHandler()
        entities, _ = h.extract(f)
        cls = [e for e in entities if e.kind == "class"][0]
        assert "2 public methods" in cls.description
        assert "1 private methods" in cls.description

    def test_interface_as_class_kind(self, tmp_path):
        f = tmp_path / "iface.ts"
        f.write_text(
            "export interface IService {\n"
            "    name: string;\n"
            "    run(x: number): Promise<void>;\n"
            "}\n"
        )
        h = TypeScriptHandler()
        entities, _ = h.extract(f)
        iface_ents = [e for e in entities if e.name == "IService"]
        assert len(iface_ents) == 1
        assert iface_ents[0].kind == "class"
        assert "Interface:" in iface_ents[0].description

    def test_enum_as_class_kind(self, tmp_path):
        f = tmp_path / "colors.ts"
        f.write_text(
            "export enum Color {\n"
            "    Red,\n"
            "    Green,\n"
            "    Blue,\n"
            "}\n"
        )
        h = TypeScriptHandler()
        entities, _ = h.extract(f)
        enum_ents = [e for e in entities if e.name == "Color"]
        assert len(enum_ents) == 1
        assert enum_ents[0].kind == "class"
        assert "Red" in enum_ents[0].description

    def test_function_declaration(self, tmp_path):
        f = tmp_path / "utils.ts"
        f.write_text(
            "export function helper(x: string): number {\n"
            "    return parseInt(x, 10);\n"
            "}\n"
        )
        h = TypeScriptHandler()
        entities, _ = h.extract(f)
        func_ents = [e for e in entities if e.kind == "function"]
        assert len(func_ents) == 1
        assert func_ents[0].name == "helper"
        assert "helper(x: string): number" in func_ents[0].description
        assert "public" in func_ents[0].description

    def test_arrow_function(self, tmp_path):
        f = tmp_path / "arrow.ts"
        f.write_text(
            "export const greet = (name: string): string => {\n"
            "    return `Hello ${name}`;\n"
            "};\n"
        )
        h = TypeScriptHandler()
        entities, _ = h.extract(f)
        func_ents = [e for e in entities if e.kind == "function"]
        assert len(func_ents) == 1
        assert func_ents[0].name == "greet"
        assert "public" in func_ents[0].description

    def test_export_visibility(self, tmp_path):
        f = tmp_path / "vis.ts"
        f.write_text(
            "export function publicFn(): void {}\n"
            "function privateFn(): void {}\n"
        )
        h = TypeScriptHandler()
        entities, _ = h.extract(f)
        pub = [e for e in entities if e.name == "publicFn"][0]
        priv = [e for e in entities if e.name == "privateFn"][0]
        assert "public" in pub.description
        assert "private" in priv.description

    def test_import_relationships(self, tmp_path):
        f = tmp_path / "imports.ts"
        f.write_text(
            "import { Foo, Bar } from './models';\n"
            "import * as utils from './utils';\n"
            "import Default from './default';\n"
        )
        h = TypeScriptHandler()
        _, rels = h.extract(f)
        import_rels = [r for r in rels if r.kind == "imports"]
        targets = {r.target_name for r in import_rels}
        assert "./models.Foo" in targets
        assert "./models.Bar" in targets
        assert "./utils" in targets
        assert "./default" in targets

    def test_type_annotations_preserved(self, tmp_path):
        f = tmp_path / "typed.ts"
        f.write_text(
            "export function process(config: AppConfig, items: Array<Item>): Promise<Result> {\n"
            "    return Promise.resolve({} as Result);\n"
            "}\n"
        )
        h = TypeScriptHandler()
        entities, _ = h.extract(f)
        func = [e for e in entities if e.kind == "function"][0]
        assert "config: AppConfig" in func.description
        assert "Promise<Result>" in func.description

    def test_tsx_parses(self, tmp_path):
        f = tmp_path / "component.tsx"
        f.write_text(
            "import React from 'react';\n"
            "\n"
            "export function Button({ label }: { label: string }) {\n"
            "    return <button>{label}</button>;\n"
            "}\n"
        )
        h = TypeScriptHandler()
        entities, _ = h.extract(f)
        func_ents = [e for e in entities if e.kind == "function"]
        assert len(func_ents) == 1
        assert func_ents[0].name == "Button"

    def test_js_file(self, tmp_path):
        f = tmp_path / "legacy.js"
        f.write_text(
            "function add(a, b) {\n"
            "    return a + b;\n"
            "}\n"
            "\n"
            "module.exports = { add };\n"
        )
        h = TypeScriptHandler()
        entities, _ = h.extract(f)
        func_ents = [e for e in entities if e.kind == "function"]
        assert len(func_ents) == 1
        assert func_ents[0].name == "add"

    def test_inheritance_relationships(self, tmp_path):
        f = tmp_path / "child.ts"
        f.write_text(
            "export class Child extends Base implements IService {\n"
            "    run(): void {}\n"
            "}\n"
        )
        h = TypeScriptHandler()
        _, rels = h.extract(f)
        inherits = [r for r in rels if r.kind == "inherits"]
        implements = [r for r in rels if r.kind == "implements"]
        assert len(inherits) == 1
        assert inherits[0].target_name == "Base"
        assert len(implements) == 1
        assert implements[0].target_name == "IService"

    def test_deterministic_entities(self, tmp_path):
        f = tmp_path / "det.ts"
        f.write_text("export class Stable { run(): void {} }\n")
        h = TypeScriptHandler()
        e1, _ = h.extract(f)
        e2, _ = h.extract(f)
        assert [e.name for e in e1] == [e.name for e in e2]
        assert [e.description for e in e1] == [e.description for e in e2]

    def test_type_alias_in_preamble(self, tmp_path):
        f = tmp_path / "types.ts"
        f.write_text(
            "export type ID = string;\n"
            "type Internal = number;\n"
        )
        h = TypeScriptHandler()
        entities, _ = h.extract(f)
        module_ent = [e for e in entities if e.kind == "module"][0]
        assert "ID" in module_ent.description.split("Exports:")[1].split("Private:")[0]


# ── TypeScript ingest integration ──────────────────────────────────────


class TestIngestTypeScript:
    def test_ingests_ts_file(self, tmp_path):
        (tmp_path / "app.ts").write_text(
            "export class App {\n"
            "    run(): void {}\n"
            "}\n"
        )
        store = _FakeStore()
        commit = ingest(store, tmp_path, tmp_path, IngesterConfig())
        names = {e.name for e in store.entities}
        assert "app" in names
        assert "App" in names

    def test_ts_and_py_together(self, tmp_path):
        (tmp_path / "backend.py").write_text("class Server:\n    pass\n")
        (tmp_path / "frontend.ts").write_text("export class Client { fetch(): void {} }\n")
        store = _FakeStore()
        ingest(store, tmp_path, tmp_path, IngesterConfig())
        names = {e.name for e in store.entities}
        assert "Server" in names
        assert "Client" in names

    def test_ts_entity_ids_deterministic(self, tmp_path):
        (tmp_path / "det.ts").write_text("export class Stable {}\n")
        store1 = _FakeStore()
        store2 = _FakeStore()
        ingest(store1, tmp_path, tmp_path, IngesterConfig())
        ingest(store2, tmp_path, tmp_path, IngesterConfig())
        ids1 = sorted(e.id for e in store1.entities)
        ids2 = sorted(e.id for e in store2.entities)
        assert ids1 == ids2


# ── MarkdownHandler ─────────────────────────────────────────────────────


class TestMarkdownHandler:
    def test_supports_md(self, tmp_path):
        h = MarkdownHandler()
        assert h.supports(tmp_path / "README.md")
        assert h.supports(tmp_path / "notes.markdown")

    def test_rejects_non_md(self, tmp_path):
        h = MarkdownHandler()
        assert not h.supports(tmp_path / "main.py")
        assert not h.supports(tmp_path / "style.css")

    def test_chunks_empty_file(self, tmp_path):
        f = tmp_path / "empty.md"
        f.write_text("")
        h = MarkdownHandler()
        assert h.chunks(f) == []

    def test_single_heading_section(self, tmp_path):
        f = tmp_path / "simple.md"
        f.write_text("# Title\n\nSome content here.")
        h = MarkdownHandler()
        chunks = h.chunks(f)
        assert len(chunks) == 1
        assert "Some content here." in chunks[0]

    def test_heading_path_in_chunks(self, tmp_path):
        f = tmp_path / "nested.md"
        f.write_text(
            "# Top\n\nIntro.\n\n"
            "## Section A\n\nContent A.\n\n"
            "### Subsection A1\n\nDeep content.\n"
        )
        h = MarkdownHandler()
        chunks = h.chunks(f)
        assert len(chunks) == 3
        assert "[heading: Top]" in chunks[0]
        assert "[heading: Top > Section A]" in chunks[1]
        assert "[heading: Top > Section A > Subsection A1]" in chunks[2]

    def test_preamble_before_first_heading(self, tmp_path):
        f = tmp_path / "preamble.md"
        f.write_text("Some preamble text.\n\n# Heading\n\nBody.")
        h = MarkdownHandler()
        chunks = h.chunks(f)
        assert len(chunks) == 2
        assert "preamble" in chunks[0]
        assert "[heading:" not in chunks[0]

    def test_multiple_headings_same_level(self, tmp_path):
        f = tmp_path / "flat.md"
        f.write_text(
            "# Doc\n\n"
            "## Alpha\n\nAlpha content.\n\n"
            "## Beta\n\nBeta content.\n"
        )
        h = MarkdownHandler()
        chunks = h.chunks(f)
        alpha_chunks = [c for c in chunks if "Alpha content" in c]
        beta_chunks = [c for c in chunks if "Beta content" in c]
        assert len(alpha_chunks) == 1
        assert len(beta_chunks) == 1
        assert "[heading: Doc > Alpha]" in alpha_chunks[0]
        assert "[heading: Doc > Beta]" in beta_chunks[0]

    def test_oversized_section_splits(self, tmp_path):
        f = tmp_path / "big.md"
        f.write_text("# Big\n\n" + "word " * 1000)
        h = MarkdownHandler()
        chunks = h.chunks(f)
        assert len(chunks) > 1

    def test_no_headings_produces_single_chunk(self, tmp_path):
        f = tmp_path / "plain.md"
        f.write_text("Just some plain text without any headings.")
        h = MarkdownHandler()
        chunks = h.chunks(f)
        assert len(chunks) == 1
        assert "plain text" in chunks[0]

    def test_heading_level_skip(self, tmp_path):
        f = tmp_path / "skip.md"
        f.write_text(
            "# Top\n\n"
            "### Deep\n\nSkipped H2.\n"
        )
        h = MarkdownHandler()
        chunks = h.chunks(f)
        deep_chunks = [c for c in chunks if "Skipped H2" in c]
        assert len(deep_chunks) == 1
        assert "[heading: Top > Deep]" in deep_chunks[0]


# ── Summarizer response parsing ───────────────────────────────────────


class TestSummarizerParsing:
    def test_valid_json(self):
        raw = '{"entities": [{"name": "pre-commit hook", "kind": "workflow", "description": "Runs ck ingest before commit"}], "relationships": []}'
        ents, rels = _parse_llm_response(raw)
        assert len(ents) == 1
        assert ents[0].name == "pre-commit hook"
        assert ents[0].kind == "workflow"
        assert rels == []

    def test_strips_markdown_fences(self):
        raw = '```json\n{"entities": [{"name": "X", "kind": "decision", "description": "D"}], "relationships": []}\n```'
        ents, _ = _parse_llm_response(raw)
        assert len(ents) == 1
        assert ents[0].name == "X"

    def test_invalid_json_returns_empty(self):
        ents, rels = _parse_llm_response("not json at all")
        assert ents == []
        assert rels == []

    def test_missing_name_skipped(self):
        raw = '{"entities": [{"name": "", "kind": "decision", "description": "D"}], "relationships": []}'
        ents, _ = _parse_llm_response(raw)
        assert ents == []

    def test_relationships_parsed(self):
        raw = '{"entities": [], "relationships": [{"source_name": "A", "target_name": "B", "kind": "motivates", "description": "A motivates B"}]}'
        _, rels = _parse_llm_response(raw)
        assert len(rels) == 1
        assert rels[0].source_name == "A"
        assert rels[0].target_name == "B"
        assert rels[0].kind == "motivates"

    def test_empty_response(self):
        raw = '{"entities": [], "relationships": []}'
        ents, rels = _parse_llm_response(raw)
        assert ents == []
        assert rels == []

    def test_multiple_entities_and_relationships(self):
        raw = """{
            "entities": [
                {"name": "graph is source of truth", "kind": "invariant", "description": "All materialized files derived from graph"},
                {"name": "no cloud LLM", "kind": "constraint", "description": "All inference runs locally on 7900 XTX"}
            ],
            "relationships": [
                {"source_name": "no cloud LLM", "target_name": "local Qwen3 selection", "kind": "motivates", "description": "Constraint drives model choice"}
            ]
        }"""
        ents, rels = _parse_llm_response(raw)
        assert len(ents) == 2
        assert {e.kind for e in ents} == {"invariant", "constraint"}
        assert len(rels) == 1

    def test_semantic_vocabulary_uses_realizes_not_implements(self):
        # ADR-0021: the extractor's semantic vocabulary has zero code-keyword overlap.
        # `implements` is structural-only (parser handlers); the LLM kind is `realizes`.
        assert "realizes" in RELATIONSHIP_KINDS
        assert "implements" not in RELATIONSHIP_KINDS
        assert "- realizes:" in _SYSTEM_PROMPT
        assert "- implements:" not in _SYSTEM_PROMPT

    def test_realizes_relationship_parsed(self):
        raw = '{"entities": [], "relationships": [{"source_name": "LLMSummarizer", "target_name": "ADR-0004", "kind": "realizes", "description": "code realizes the decision"}]}'
        _, rels = _parse_llm_response(raw)
        assert len(rels) == 1
        assert rels[0].kind == "realizes"


# ── Change Detection ────────────────────────────────────────────────────


class TestChangeDetection:
    def test_changed_since_none_returns_all(self, tmp_path):
        (tmp_path / "a.md").write_text("hello")
        (tmp_path / "b.md").write_text("world")
        result = changed_since(tmp_path, None)
        assert len(result) == 2

    def test_changed_since_unchanged_tree(self, tmp_path):
        (tmp_path / "a.md").write_text("hello")
        current_hash = source_tree_hash(tmp_path, tmp_path)
        result = changed_since(tmp_path, GraphCommit(current_hash))
        assert result == []

    def test_walk_excludes_git(self, tmp_path):
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        (git_dir / "config").write_text("gitconfig")
        (tmp_path / "README.md").write_text("hello")
        files = walk_source_files(tmp_path)
        assert len(files) == 1
        assert files[0].name == "README.md"

    def test_walk_excludes_context_kernel(self, tmp_path):
        ck = tmp_path / ".context-kernel"
        ck.mkdir()
        (ck / "log.md").write_text("log")
        (tmp_path / "src.md").write_text("source")
        files = walk_source_files(tmp_path)
        assert all(".context-kernel" not in str(f) for f in files)

    def test_walk_excludes_node_modules(self, tmp_path):
        nm = tmp_path / "node_modules" / "pkg"
        nm.mkdir(parents=True)
        (nm / "index.js").write_text("module")
        (tmp_path / "app.md").write_text("app")
        files = walk_source_files(tmp_path)
        assert len(files) == 1

    def test_walk_excludes_build_artifacts(self, tmp_path):
        # dist/build/out/coverage are universally build output, never source knowledge.
        for d in ("dist", "build", "out", "coverage"):
            art = tmp_path / d
            art.mkdir()
            (art / "bundle.js").write_text("minified")
        (tmp_path / "app.py").write_text("real source")
        files = walk_source_files(tmp_path)
        assert [f.name for f in files] == ["app.py"]

    def test_walk_honors_registered_exclusions(self, tmp_path):
        # Config-driven exclusions (e.g. [ingester].exclude_dirs = ["test-repos"]) are
        # registered after import and must still be honored by the live walker.
        from context_kernel.change_detection import (
            register_excluded_dirs,
            _REGISTERED_EXCLUDED_DIRS,
        )
        repos = tmp_path / "test-repos" / "open-webui"
        repos.mkdir(parents=True)
        (repos / "main.py").write_text("foreign corpus")
        (tmp_path / "app.py").write_text("real source")
        try:
            register_excluded_dirs(["test-repos"])
            files = walk_source_files(tmp_path)
            assert [f.name for f in files] == ["app.py"]
        finally:
            _REGISTERED_EXCLUDED_DIRS.discard("test-repos")

    def test_discover_scopes(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        (src / "main.py").write_text("code")
        (tmp_path / "README.md").write_text("readme")
        scopes = discover_scopes(tmp_path)
        scope_strs = [str(s) for s in scopes]
        assert "." in scope_strs
        assert "src" in scope_strs

    def test_source_tree_hash_deterministic(self, tmp_path):
        (tmp_path / "a.md").write_text("hello")
        h1 = source_tree_hash(tmp_path, tmp_path)
        h2 = source_tree_hash(tmp_path, tmp_path)
        assert h1 == h2

    def test_source_tree_hash_changes_on_edit(self, tmp_path):
        f = tmp_path / "a.md"
        f.write_text("version1")
        h1 = source_tree_hash(tmp_path, tmp_path)
        f.write_text("version2")
        h2 = source_tree_hash(tmp_path, tmp_path)
        assert h1 != h2


# ── Blobs ────────────────────────────────────────────────────────────────


class TestBlobs:
    def test_write_embedding_roundtrip(self, tmp_path):
        content = b"\x00\x01\x02\x03" * 256
        digest = write_embedding(tmp_path, content)
        assert len(digest) == 64
        blob = tmp_path / ".context-kernel" / "embeddings" / f"{digest}.bin"
        assert blob.exists()
        assert blob.read_bytes() == content

    def test_write_summary_roundtrip(self, tmp_path):
        md = "# Summary\n\nThis scope handles auth."
        digest = write_summary(tmp_path, md)
        blob = tmp_path / ".context-kernel" / "summaries" / f"{digest}.md"
        assert blob.exists()
        assert blob.read_text() == md

    def test_content_addressing(self, tmp_path):
        d1 = write_summary(tmp_path, "same content")
        d2 = write_summary(tmp_path, "same content")
        assert d1 == d2
        d3 = write_summary(tmp_path, "different content")
        assert d1 != d3


# ── Ingest integration ──────────────────────────────────────────────────


def _cosine_sim(a: bytes, b: bytes) -> float:
    n = len(a) // 4
    if n == 0 or len(b) // 4 != n:
        return 0.0
    af = struct.unpack(f"{n}f", a)
    bf = struct.unpack(f"{n}f", b)
    dot = sum(x * y for x, y in zip(af, bf))
    ma = math.sqrt(sum(x * x for x in af))
    mb = math.sqrt(sum(x * x for x in bf))
    if ma == 0 or mb == 0:
        return 0.0
    return dot / (ma * mb)


def _brute_force_search(chunks, query_embedding, k, scope=None):
    scored = []
    for c in chunks:
        if scope is not None and c.scope != scope:
            continue
        score = _cosine_sim(query_embedding, c.embedding)
        scored.append(SearchResult(
            chunk_text=c.chunk_text,
            source_path=c.source_path,
            score=score,
            kind=c.kind,
            scope=c.scope,
        ))
    scored.sort(key=lambda r: r.score, reverse=True)
    return scored[:k]


class _FakeStore:
    """Minimal KnowledgeStore for testing ingest()."""

    def __init__(self):
        self.last_commit: GraphCommit | None = None
        self.entities: list[Entity] = []
        self.relationships: list[Relationship] = []
        self.summaries: list[Summary] = []
        self.chunks: list[EmbeddedChunk] = []
        self.scope_entities: dict[ScopePath, list[Entity]] = {}

    def graph_commit(self) -> GraphCommit:
        return self.last_commit or GraphCommit("initial")

    def get_entity(self, entity_id: str) -> Entity | None:
        return None

    def get_neighbors(self, entity_id: str):
        return []

    def get_summary(self, scope: ScopePath) -> Summary | None:
        return None

    def get_embedding(self, digest: Sha256) -> bytes | None:
        return None

    def search_similar(self, query_embedding, k, scope=None):
        return _brute_force_search(self.chunks, query_embedding, k, scope)

    def list_summaries(self):
        return list(self.summaries)

    def list_entities_by_scope(self):
        return dict(self.scope_entities)

    def upsert(self, graph_commit, entities, relationships, summaries, chunks=None, scope_entities=None) -> None:
        self.last_commit = graph_commit
        self.entities = list(entities)
        self.relationships = list(relationships)
        self.summaries = list(summaries)
        if chunks:
            self.chunks = list(chunks)
        if scope_entities:
            self.scope_entities = dict(scope_entities)


class TestIngestPython:
    def test_ingests_python_file(self, tmp_path):
        (tmp_path / "app.py").write_text(
            "class App:\n"
            "    def run(self) -> None:\n"
            "        pass\n"
        )
        store = _FakeStore()
        commit = ingest(store, tmp_path, tmp_path, IngesterConfig())
        assert len(store.entities) >= 2
        names = {e.name for e in store.entities}
        assert "app" in names
        assert "App" in names

    def test_entity_ids_are_deterministic(self, tmp_path):
        (tmp_path / "det.py").write_text("class Stable:\n    pass\n")
        store1 = _FakeStore()
        store2 = _FakeStore()
        ingest(store1, tmp_path, tmp_path, IngesterConfig())
        ingest(store2, tmp_path, tmp_path, IngesterConfig())
        ids1 = sorted(e.id for e in store1.entities)
        ids2 = sorted(e.id for e in store2.entities)
        assert ids1 == ids2

    def test_graph_commit_is_deterministic(self, tmp_path):
        (tmp_path / "det.py").write_text("class Stable:\n    pass\n")
        store1 = _FakeStore()
        store2 = _FakeStore()
        c1 = ingest(store1, tmp_path, tmp_path, IngesterConfig())
        c2 = ingest(store2, tmp_path, tmp_path, IngesterConfig())
        assert c1 == c2

    def test_generates_scope_summary(self, tmp_path):
        (tmp_path / "foo.py").write_text("class Foo:\n    pass\n")
        store = _FakeStore()
        ingest(store, tmp_path, tmp_path, IngesterConfig())
        assert len(store.summaries) >= 1
        assert any("Foo" in s.markdown for s in store.summaries)

    def test_writes_summary_blob(self, tmp_path):
        (tmp_path / "foo.py").write_text("class Foo:\n    pass\n")
        store = _FakeStore()
        ingest(store, tmp_path, tmp_path, IngesterConfig())
        summaries_dir = tmp_path / ".context-kernel" / "summaries"
        assert summaries_dir.exists()
        assert len(list(summaries_dir.iterdir())) >= 1

    def test_inheritance_relationships(self, tmp_path):
        (tmp_path / "hier.py").write_text(
            "class Base:\n    pass\n"
            "class Child(Base):\n    pass\n"
        )
        store = _FakeStore()
        ingest(store, tmp_path, tmp_path, IngesterConfig())
        inherits = [r for r in store.relationships if r.kind == "inherits"]
        assert len(inherits) >= 1

    def test_skips_syntax_errors(self, tmp_path):
        (tmp_path / "bad.py").write_text("def broken(:\n")
        (tmp_path / "good.py").write_text("class Good:\n    pass\n")
        store = _FakeStore()
        ingest(store, tmp_path, tmp_path, IngesterConfig())
        names = {e.name for e in store.entities}
        assert "Good" in names

    def test_skips_empty_files(self, tmp_path):
        (tmp_path / "empty.py").write_text("")
        (tmp_path / "full.py").write_text("X = 1\n")
        store = _FakeStore()
        ingest(store, tmp_path, tmp_path, IngesterConfig())
        assert all(e.name != "empty" for e in store.entities)

    def test_empty_directory(self, tmp_path):
        store = _FakeStore()
        commit = ingest(store, tmp_path, tmp_path, IngesterConfig())
        assert commit is not None
        assert store.entities == []


class _FakeSummarizer:
    """Mock summarizer that returns canned entities for any chunk."""

    def __init__(self):
        self.calls: list[str] = []

    def summarize(self, text: str, *, context: str = "") -> tuple[list[RawEntity], list[RawRelationship]]:
        self.calls.append(text)
        self.last_context = context
        entities = [RawEntity(name="mock-entity", kind="decision", description=f"Extracted from: {text[:50]}")]
        return entities, []

    def summarize_scope(self, scope_name: str, entity_descriptions: list[str]) -> str | None:
        return f"LLM summary for {scope_name}: {len(entity_descriptions)} entities."


class TestIngestMarkdownWithoutSummarizer:
    def test_skips_md_without_summarizer(self, tmp_path):
        (tmp_path / "README.md").write_text("# Hello\n\nContent.")
        store = _FakeStore()
        ingest(store, tmp_path, tmp_path, IngesterConfig())
        assert store.entities == []
        assert store.summaries == []

    def test_processes_py_alongside_skipped_md(self, tmp_path):
        (tmp_path / "README.md").write_text("# Hello")
        (tmp_path / "app.py").write_text("class App:\n    pass\n")
        store = _FakeStore()
        ingest(store, tmp_path, tmp_path, IngesterConfig())
        names = {e.name for e in store.entities}
        assert "App" in names


class TestIngestMarkdownWithSummarizer:
    def test_md_produces_entities_with_summarizer(self, tmp_path):
        (tmp_path / "design.md").write_text("# Design\n\n## Invariants\n\nGraph is source of truth.\n")
        store = _FakeStore()
        ingest(store, tmp_path, tmp_path, IngesterConfig(), summarizer=_FakeSummarizer())
        assert len(store.entities) >= 1
        assert any(e.kind == "decision" for e in store.entities)

    def test_heading_context_reaches_summarizer(self, tmp_path):
        (tmp_path / "theory.md").write_text(
            "# Theory\n\n"
            "## Thesis\n\nWe believe graphs compose context.\n\n"
            "## Non-goals\n\nNo cloud fallback.\n"
        )
        store = _FakeStore()
        summarizer = _FakeSummarizer()
        ingest(store, tmp_path, tmp_path, IngesterConfig(), summarizer=summarizer)
        # Heading path reaches the summarizer as chunk context (entities may merge by name).
        assert any("Thesis" in t for t in summarizer.calls)
        assert any("Non-goals" in t for t in summarizer.calls)

    def test_code_entities_reach_doc_extractor(self, tmp_path):
        # ADR-0016: Phase-1 code entities are fed into the Phase-2 extraction context.
        (tmp_path / "circuit_breaker.py").write_text("class CircuitBreaker:\n    def trip(self): ...\n")
        (tmp_path / "design.md").write_text("# Design\n\nThe pipeline uses a circuit breaker on outage.\n")
        store = _FakeStore()
        summarizer = _FakeSummarizer()
        ingest(store, tmp_path, tmp_path, IngesterConfig(), summarizer=summarizer)
        assert summarizer.last_context  # non-empty context was passed
        assert "## Known code entities" in summarizer.last_context
        assert "CircuitBreaker" in summarizer.last_context

    def test_md_and_py_together_with_summarizer(self, tmp_path):
        (tmp_path / "design.md").write_text("# Design\n\nSome design context.\n")
        (tmp_path / "app.py").write_text("class App:\n    pass\n")
        store = _FakeStore()
        ingest(store, tmp_path, tmp_path, IngesterConfig(), summarizer=_FakeSummarizer())
        names = {e.name for e in store.entities}
        assert "App" in names
        assert "mock-entity" in names


class TestIngestMixedSources:
    def test_multiple_python_files(self, tmp_path):
        (tmp_path / "a.py").write_text("class Alpha:\n    pass\n")
        (tmp_path / "b.py").write_text("class Beta:\n    pass\n")
        store = _FakeStore()
        ingest(store, tmp_path, tmp_path, IngesterConfig())
        names = {e.name for e in store.entities}
        assert "Alpha" in names
        assert "Beta" in names

    def test_nested_scopes(self, tmp_path):
        sub = tmp_path / "pkg"
        sub.mkdir()
        (tmp_path / "root.py").write_text("class Root:\n    pass\n")
        (sub / "child.py").write_text("class Child:\n    pass\n")
        store = _FakeStore()
        ingest(store, tmp_path, tmp_path, IngesterConfig())
        names = {e.name for e in store.entities}
        assert "Root" in names
        assert "Child" in names
        assert len(store.summaries) >= 2


# ── LLM scope summaries (ADR-0007) ───────────────────────────────────


class TestLLMScopeSummaries:
    def test_uses_llm_summary_when_summarizer_present(self, tmp_path):
        (tmp_path / "app.py").write_text("class App:\n    pass\n")
        store = _FakeStore()
        ingest(store, tmp_path, tmp_path, IngesterConfig(), summarizer=_FakeSummarizer())
        assert len(store.summaries) >= 1
        assert any("LLM summary" in s.markdown for s in store.summaries)

    def test_falls_back_to_mechanical_without_summarizer(self, tmp_path):
        (tmp_path / "app.py").write_text("class App:\n    pass\n")
        store = _FakeStore()
        ingest(store, tmp_path, tmp_path, IngesterConfig())
        assert len(store.summaries) >= 1
        assert any("Scope" in s.markdown and "modules" in s.markdown for s in store.summaries)
        assert not any("LLM summary" in s.markdown for s in store.summaries)

    def test_llm_summary_includes_scope_name(self, tmp_path):
        sub = tmp_path / "auth"
        sub.mkdir()
        (sub / "service.py").write_text("class AuthService:\n    pass\n")
        store = _FakeStore()
        ingest(store, tmp_path, tmp_path, IngesterConfig(), summarizer=_FakeSummarizer())
        auth_summaries = [s for s in store.summaries if "auth" in str(s.scope)]
        assert len(auth_summaries) >= 1
        assert "auth" in auth_summaries[0].markdown

    def test_falls_back_on_summarizer_scope_failure(self, tmp_path):
        class _FailingScopeSummarizer(_FakeSummarizer):
            def summarize_scope(self, scope_name, entity_descriptions):
                return None

        (tmp_path / "app.py").write_text("class App:\n    pass\n")
        store = _FakeStore()
        ingest(store, tmp_path, tmp_path, IngesterConfig(), summarizer=_FailingScopeSummarizer())
        assert len(store.summaries) >= 1
        assert any("Scope" in s.markdown and "modules" in s.markdown for s in store.summaries)


# ── Embedding at ingest (S5) ──────────────────────────────────────────


class TestIngestWithEmbedder:
    def test_embeds_entity_descriptions(self, tmp_path, embedder):
        (tmp_path / "app.py").write_text(
            "class UserService:\n"
            "    def get_user(self, user_id: int) -> str:\n"
            "        pass\n"
        )
        store = _FakeStore()
        ingest(store, tmp_path, tmp_path, IngesterConfig(), embedder=embedder)
        entity_chunks = [c for c in store.chunks if c.kind == "entity"]
        assert len(entity_chunks) >= 2  # module + class at minimum

    def test_embeds_scope_summaries(self, tmp_path, embedder):
        (tmp_path / "app.py").write_text("class Foo:\n    pass\n")
        store = _FakeStore()
        ingest(store, tmp_path, tmp_path, IngesterConfig(), embedder=embedder)
        summary_chunks = [c for c in store.chunks if c.kind == "summary"]
        assert len(summary_chunks) >= 1

    def test_embedding_bytes_expected_length(self, tmp_path, embedder):
        (tmp_path / "app.py").write_text("class Bar:\n    pass\n")
        store = _FakeStore()
        ingest(store, tmp_path, tmp_path, IngesterConfig(), embedder=embedder)
        for chunk in store.chunks:
            assert len(chunk.embedding) == 1024 * 4  # 1024 floats * 4 bytes

    def test_no_embedder_no_chunks(self, tmp_path):
        (tmp_path / "app.py").write_text("class Baz:\n    pass\n")
        store = _FakeStore()
        ingest(store, tmp_path, tmp_path, IngesterConfig())
        assert store.chunks == []

    def test_chunk_source_paths_populated(self, tmp_path, embedder):
        (tmp_path / "svc.py").write_text("class Svc:\n    pass\n")
        store = _FakeStore()
        ingest(store, tmp_path, tmp_path, IngesterConfig(), embedder=embedder)
        entity_chunks = [c for c in store.chunks if c.kind == "entity"]
        assert all(c.source_path == "svc.py" for c in entity_chunks)

    def test_chunks_are_deterministic(self, tmp_path, embedder):
        (tmp_path / "det.py").write_text("class Stable:\n    pass\n")
        store1 = _FakeStore()
        store2 = _FakeStore()
        ingest(store1, tmp_path, tmp_path, IngesterConfig(), embedder=embedder)
        ingest(store2, tmp_path, tmp_path, IngesterConfig(), embedder=embedder)
        ids1 = sorted(c.id for c in store1.chunks)
        ids2 = sorted(c.id for c in store2.chunks)
        assert ids1 == ids2

    def test_search_similar_returns_ranked(self, tmp_path, embedder):
        (tmp_path / "auth.py").write_text(
            "class AuthService:\n"
            "    def verify_token(self, token: str) -> bool:\n"
            "        pass\n"
        )
        (tmp_path / "math_utils.py").write_text(
            "def add(a: int, b: int) -> int:\n"
            "    return a + b\n"
        )
        store = _FakeStore()
        ingest(store, tmp_path, tmp_path, IngesterConfig(), embedder=embedder)
        query_emb = embedder.embed("authentication and tokens", mode="query")
        results = store.search_similar(query_emb, k=3)
        assert len(results) > 0
        assert results[0].score >= results[-1].score

    def test_search_similar_scope_filter(self, tmp_path, embedder):
        sub = tmp_path / "pkg"
        sub.mkdir()
        (tmp_path / "root.py").write_text("class Root:\n    pass\n")
        (sub / "child.py").write_text("class Child:\n    pass\n")
        store = _FakeStore()
        ingest(store, tmp_path, tmp_path, IngesterConfig(), embedder=embedder)
        query_emb = embedder.embed("class", mode="query")
        filtered = store.search_similar(query_emb, k=20, scope=ScopePath(Path("pkg")))
        assert all(r.scope == ScopePath(Path("pkg")) for r in filtered)


# ── Cross-project namespacing (S9) ─────────────────────────────────────


class TestIngestProjectNamespacing:
    def test_project_name_prefixes_scopes(self, tmp_path):
        (tmp_path / "app.py").write_text("class App:\n    pass\n")
        store = _FakeStore()
        ingest(store, tmp_path, tmp_path, IngesterConfig(), project_name="proj-a")
        scope_strs = [str(s) for s in store.scope_entities.keys()]
        assert all(s.startswith("proj-a") for s in scope_strs)

    def test_project_name_changes_entity_ids(self, tmp_path):
        (tmp_path / "app.py").write_text("class App:\n    pass\n")
        store_a = _FakeStore()
        store_b = _FakeStore()
        ingest(store_a, tmp_path, tmp_path, IngesterConfig(), project_name="proj-a")
        ingest(store_b, tmp_path, tmp_path, IngesterConfig(), project_name="proj-b")
        ids_a = {e.id for e in store_a.entities}
        ids_b = {e.id for e in store_b.entities}
        assert ids_a.isdisjoint(ids_b)

    def test_no_project_name_matches_legacy_behavior(self, tmp_path):
        (tmp_path / "app.py").write_text("class App:\n    pass\n")
        store_legacy = _FakeStore()
        store_none = _FakeStore()
        ingest(store_legacy, tmp_path, tmp_path, IngesterConfig())
        ingest(store_none, tmp_path, tmp_path, IngesterConfig(), project_name=None)
        ids_legacy = sorted(e.id for e in store_legacy.entities)
        ids_none = sorted(e.id for e in store_none.entities)
        assert ids_legacy == ids_none

    def test_no_project_name_scopes_unprefixed(self, tmp_path):
        sub = tmp_path / "src"
        sub.mkdir()
        (sub / "app.py").write_text("class App:\n    pass\n")
        store = _FakeStore()
        ingest(store, tmp_path, tmp_path, IngesterConfig(), project_name=None)
        scope_strs = [str(s) for s in store.scope_entities.keys()]
        assert "src" in scope_strs

    def test_two_projects_same_store_no_collision(self, tmp_path):
        dir_a = tmp_path / "a"
        dir_b = tmp_path / "b"
        dir_a.mkdir()
        dir_b.mkdir()
        (dir_a / "app.py").write_text("class App:\n    pass\n")
        (dir_b / "app.py").write_text("class App:\n    pass\n")
        store = _FakeStore()
        ingest(store, dir_a, tmp_path, IngesterConfig(), project_name="proj-a")
        entities_a = list(store.entities)
        scopes_a = dict(store.scope_entities)
        ingest(store, dir_b, tmp_path, IngesterConfig(), project_name="proj-b")
        entities_b = list(store.entities)
        ids_a = {e.id for e in entities_a}
        ids_b = {e.id for e in entities_b}
        assert ids_a.isdisjoint(ids_b)
        assert any("proj-a" in str(s) for s in scopes_a.keys())
        scope_strs_b = [str(s) for s in store.scope_entities.keys()]
        assert any("proj-b" in s for s in scope_strs_b)

    def test_project_name_prefixes_summary_scopes(self, tmp_path):
        (tmp_path / "app.py").write_text("class App:\n    pass\n")
        store = _FakeStore()
        ingest(store, tmp_path, tmp_path, IngesterConfig(), project_name="my-proj")
        summary_scopes = [str(s.scope) for s in store.summaries]
        assert all("my-proj" in s for s in summary_scopes)

    def test_portfolio_ingest_writes_one_combined_snapshot(self, tmp_path):
        dir_a = tmp_path / "a"
        dir_b = tmp_path / "b"
        dir_a.mkdir()
        dir_b.mkdir()
        (dir_a / "app.py").write_text("class AppA:\n    pass\n")
        (dir_b / "app.py").write_text("class AppB:\n    pass\n")

        store = _FakeStore()
        commit1 = ingest_portfolio(
            store,
            tmp_path,
            tmp_path,
            IngesterConfig(),
            [(Path("a"), "a"), (Path("b"), "b")],
        )

        names = {e.name for e in store.entities}
        assert {"AppA", "AppB"} <= names
        assert {str(s) for s in store.scope_entities} == {"a", "b"}

        (dir_a / "app.py").write_text("class AppA:\n    VALUE = 1\n")
        commit2 = ingest_portfolio(
            store,
            tmp_path,
            tmp_path,
            IngesterConfig(),
            [(Path("a"), "a"), (Path("b"), "b")],
        )
        assert commit2 != commit1

    def test_ingest_descriptions_use_relative_paths(self, tmp_path):
        (tmp_path / "app.py").write_text('"""Doc."""\nclass App:\n    pass\n')
        store = _FakeStore()
        ingest(store, tmp_path, tmp_path, IngesterConfig())
        assert store.entities
        assert all(str(tmp_path) not in e.description for e in store.entities)
        assert any("app.py" in e.description for e in store.entities)

    def test_curated_entity_concepts_ground_into_portfolio_graph(self, tmp_path):
        (tmp_path / "ontology.toml").write_text(
            "[concepts.panel]\n"
            'prefLabel = "panel"\n'
            'type = "entity"\n'
            'altLabel = ["StepPanel"]\n'
            'definition = "A UI panel concept."\n'
        )
        (tmp_path / "ui.py").write_text("class StepPanel:\n    pass\n")
        store = _FakeStore()
        ingest(store, tmp_path, tmp_path, IngesterConfig())

        concept = next(e for e in store.entities if e.kind == "concept" and e.name == "panel")
        step = next(e for e in store.entities if e.name == "StepPanel")
        edges = [r for r in store.relationships if r.kind == "implemented-by"]
        assert concept.source_tier == 0.8
        assert any(r.source_id == concept.id and r.target_id == step.id for r in edges)

    def test_portfolio_concept_hub_bridges_projects(self, tmp_path):
        (tmp_path / "ontology.toml").write_text(
            "[concepts.panel]\n"
            'prefLabel = "panel"\n'
            'type = "entity"\n'
            'altLabel = ["StepPanel", "Panel"]\n'
        )
        dir_a = tmp_path / "frontend"
        dir_b = tmp_path / "backend"
        dir_a.mkdir()
        dir_b.mkdir()
        (dir_a / "ui.tsx").write_text("export class StepPanel {}\n")
        (dir_b / "panel.py").write_text("class Panel:\n    pass\n")

        store = _FakeStore()
        ingest_portfolio(
            store,
            tmp_path,
            tmp_path,
            IngesterConfig(),
            [(Path("frontend"), "frontend"), (Path("backend"), "backend")],
        )

        concept = next(e for e in store.entities if e.kind == "concept" and e.name == "panel")
        targets = {r.target_id for r in store.relationships if r.source_id == concept.id and r.kind == "implemented-by"}
        target_names = {e.name for e in store.entities if e.id in targets}
        assert {"StepPanel", "Panel"} <= target_names


# ── Ingester observability (S8) ────────────────────────────────────────


class TestIngestLogging:
    def test_emits_ingested_log(self, tmp_path, caplog):
        import logging
        (tmp_path / "app.py").write_text("class App:\n    pass\n")
        store = _FakeStore()
        with caplog.at_level(logging.INFO, logger="context_kernel.ingester"):
            ingest(store, tmp_path, tmp_path, IngesterConfig())
        ingested_records = [r for r in caplog.records if r.getMessage() == "ingested"]
        assert len(ingested_records) == 1
        rec = ingested_records[0]
        assert rec.files_processed >= 1
        assert rec.entities >= 1
        assert rec.relationships >= 0
        assert rec.graph_commit is not None
        assert rec.duration_ms >= 0


class _StaleClaimSummarizer(_FakeSummarizer):
    """Summarizer that flags a doc-vs-code contradiction as a `stale-claim` (ADR-0016)."""

    def summarize(self, text: str, *, context: str = "") -> tuple[list[RawEntity], list[RawRelationship]]:
        self.calls.append(text)
        self.last_context = context
        # The doc claims LLMSummarizer is unbuilt, but the .py file shows it exists.
        entities = [RawEntity(name="LLMSummarizer", kind="stale-claim",
                              description="HANDOFF.md says the summarizer is not yet wired")]
        return entities, []


class TestContradictionDetection:
    """Issue #4 / ADR-0016: doc-vs-code contradictions are surfaced and kept out of the graph."""

    def _ingest(self, tmp_path, caplog):
        import logging
        (tmp_path / "summarizer.py").write_text("class LLMSummarizer:\n    def summarize(self): ...\n")
        (tmp_path / "HANDOFF.md").write_text("# Handoff\n\nThe summarizer is not yet wired.\n")
        store = _FakeStore()
        with caplog.at_level(logging.INFO, logger="context_kernel.ingester"):
            ingest(store, tmp_path, tmp_path, IngesterConfig(), summarizer=_StaleClaimSummarizer())
        return store

    def test_stale_claim_not_persisted_as_entity(self, tmp_path, caplog):
        store = self._ingest(tmp_path, caplog)
        assert "stale-claim" not in {e.kind for e in store.entities}
        assert all("stale-claim" not in e.kinds for e in store.entities)

    def test_code_entity_uncontaminated(self, tmp_path, caplog):
        # The contradiction must not be merged into the code node it contradicts (ADR-0017).
        store = self._ingest(tmp_path, caplog)
        code = [e for e in store.entities if e.name == "LLMSummarizer"]
        assert len(code) == 1
        assert code[0].kind != "stale-claim"
        assert "stale-claim" not in code[0].kinds

    def test_contradiction_is_logged(self, tmp_path, caplog):
        self._ingest(tmp_path, caplog)
        warnings = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
        assert any("contradiction" in m and "HANDOFF.md" in m for m in warnings)

    def test_contradiction_count_in_ingested_log(self, tmp_path, caplog):
        self._ingest(tmp_path, caplog)
        rec = next(r for r in caplog.records if r.getMessage() == "ingested")
        assert rec.contradictions == 1
