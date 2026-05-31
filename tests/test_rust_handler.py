"""Tests for the Rust source handler."""
from __future__ import annotations

from pathlib import Path

import pytest

from context_kernel.ingester.rust_handler import RustHandler


@pytest.fixture
def handler():
    return RustHandler()


def _rs(handler, tmp_path: Path, source: str, name: str = "sample.rs"):
    p = tmp_path / name
    p.write_text(source)
    return handler.extract(p)


SAMPLE = """\
use std::collections::HashMap;
use crate::error::AppError;
use std::io::{Read, Write};

pub struct Config {
    pub host: String,
    port: u16,
}

pub enum State {
    Idle,
    Running(u32),
    Done { code: i32 },
}

pub trait Handler {
    fn handle(&self, msg: String) -> Result<(), AppError>;
    fn name(&self) -> &str;
}

pub fn run(cfg: Config) -> u16 {
    cfg.port
}

fn helper() {}

impl Handler for Config {
    fn handle(&self, msg: String) -> Result<(), AppError> {
        Ok(())
    }
    fn name(&self) -> &str {
        "cfg"
    }
}

impl Config {
    pub fn new() -> Self {
        Config { host: String::new(), port: 0 }
    }
}

mod inner {
    pub fn tick() {}
}
"""


def test_supports():
    h = RustHandler()
    assert h.supports(Path("a/b/c.rs"))
    assert h.supports(Path("X.RS"))
    assert not h.supports(Path("c.py"))


def test_empty_file(handler, tmp_path):
    entities, rels = _rs(handler, tmp_path, "")
    assert entities == []
    assert rels == []


def test_whitespace_only(handler, tmp_path):
    entities, rels = _rs(handler, tmp_path, "   \n\n  \n")
    assert entities == []
    assert rels == []


def test_module_anchor(handler, tmp_path):
    entities, _ = _rs(handler, tmp_path, SAMPLE)
    mods = [e for e in entities if e.kind == "module" and e.name == "sample"]
    assert len(mods) == 1
    desc = mods[0].description
    assert "Depth:" in desc
    assert "LOC" in desc
    assert "Exports:" in desc


def test_struct_entity(handler, tmp_path):
    entities, _ = _rs(handler, tmp_path, SAMPLE)
    s = [e for e in entities if e.kind == "struct" and e.name == "Config"]
    assert s, "expected a Config struct entity"
    assert "host" in s[0].description  # pub field
    assert "port" in s[0].description  # private field


def test_enum_entity(handler, tmp_path):
    entities, _ = _rs(handler, tmp_path, SAMPLE)
    e = [x for x in entities if x.kind == "enum" and x.name == "State"]
    assert e, "expected a State enum entity"
    for variant in ("Idle", "Running", "Done"):
        assert variant in e[0].description


def test_trait_entity(handler, tmp_path):
    entities, _ = _rs(handler, tmp_path, SAMPLE)
    t = [x for x in entities if x.kind == "trait" and x.name == "Handler"]
    assert t, "expected a Handler trait entity"
    assert "handle" in t[0].description
    assert "name" in t[0].description


def test_free_function_entity(handler, tmp_path):
    entities, _ = _rs(handler, tmp_path, SAMPLE)
    fn = [x for x in entities if x.kind == "function" and x.name == "run"]
    assert fn, "expected a free function `run`"
    assert "run" in fn[0].description
    assert "public" in fn[0].description.lower()


def test_private_function_visibility(handler, tmp_path):
    entities, _ = _rs(handler, tmp_path, SAMPLE)
    fn = [x for x in entities if x.kind == "function" and x.name == "helper"]
    assert fn, "expected a free function `helper`"
    assert "private" in fn[0].description.lower()


def test_impl_methods_are_qualified_functions(handler, tmp_path):
    entities, _ = _rs(handler, tmp_path, SAMPLE)
    fn_names = {e.name for e in entities if e.kind == "function"}
    # impl methods qualified as Type::method
    assert "Config::handle" in fn_names
    assert "Config::name" in fn_names
    assert "Config::new" in fn_names
    # no entity for the impl block itself
    assert not any(e.kind == "impl" for e in entities)


def test_implements_relationship(handler, tmp_path):
    _, rels = _rs(handler, tmp_path, SAMPLE)
    impls = {(r.source_name, r.target_name) for r in rels if r.kind == "implements"}
    assert ("Config", "Handler") in impls


def test_imports_relationship(handler, tmp_path):
    entities, rels = _rs(handler, tmp_path, SAMPLE)
    imported = {r.target_name for r in rels if r.kind == "imports"}
    # last-segment convention
    assert "HashMap" in imported
    assert "AppError" in imported
    # brace list yields each symbol
    assert "Read" in imported and "Write" in imported
    # also surfaced in the module orientation block
    mod = [e for e in entities if e.kind == "module" and e.name == "sample"][0]
    assert "AppError" in mod.description


def test_inline_module_entity(handler, tmp_path):
    entities, _ = _rs(handler, tmp_path, SAMPLE)
    inner = [e for e in entities if e.kind == "module" and e.name == "inner"]
    assert inner, "expected an entity for inline `mod inner`"
    # its item descends one level
    tick = [e for e in entities if e.name == "tick"]
    assert tick, "expected the inline module's `tick` function to be extracted"


def test_mod_declaration_is_import_like(handler, tmp_path):
    source = "mod external;\npub fn f() {}\n"
    entities, rels = _rs(handler, tmp_path, source)
    imported = {r.target_name for r in rels if r.kind == "imports"}
    assert "external" in imported
    # no module entity for a bare `mod name;`
    assert not any(e.kind == "module" and e.name == "external" for e in entities)


def test_use_alias_uses_alias_name(handler, tmp_path):
    source = "use a::b::Thing as T;\n"
    _, rels = _rs(handler, tmp_path, source)
    imported = {r.target_name for r in rels if r.kind == "imports"}
    assert "T" in imported


def test_malformed_file_does_not_raise(handler, tmp_path):
    source = "pub fn (((( {{{{ struct ?? \n"
    entities, rels = _rs(handler, tmp_path, source)
    assert isinstance(entities, list)
    assert isinstance(rels, list)
