"""Tests for the declarative ontology / type system (ADR-0024, Phase 1)."""

from __future__ import annotations

from pathlib import Path

import pytest

from context_kernel.ingester.summarizer import (
    ENTITY_KINDS,
    RELATIONSHIP_KINDS,
    _SYSTEM_PROMPT,
    LLMSummarizer,
    _cache_key,
)
from context_kernel.ontology import (
    Ontology,
    is_ontology_file,
    load_ontology,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]

_SAMPLE = """\
version: 1
nodes:
  - {kind: module, family: structural, definition: A source file.}
  - {kind: decision, family: semantic, definition: A resolved choice.}
  - {kind: stale-claim, family: semantic, prompt: false, definition: A contradicting claim.}
  - {kind: concept, family: concept, definition: A hub node.}
edges:
  - {kind: imports, family: structural, weight: 0.3, centrality: false, definition: A module imports another.}
  - {kind: governed-by, family: semantic, weight: 0.95, centrality: true, definition: Constrained by a rule.}
"""


def _write(tmp_path: Path, text: str, name: str = "ontology.yaml") -> Path:
    (tmp_path / name).write_text(text, encoding="utf-8")
    return tmp_path


def test_is_ontology_file_matches_reserved_names():
    assert is_ontology_file(Path("ontology.yaml"))
    assert is_ontology_file(Path("a/b/ontology.toml"))
    assert is_ontology_file(Path("ONTOLOGY.YAML"))
    assert not is_ontology_file(Path("config.yaml"))
    assert not is_ontology_file(Path("ontology_notes.md"))


def test_load_returns_none_when_absent(tmp_path: Path):
    assert load_ontology(tmp_path) is None


def test_load_returns_none_on_malformed_yaml(tmp_path: Path):
    _write(tmp_path, "nodes: [unclosed\n")
    assert load_ontology(tmp_path) is None


def test_load_returns_none_when_no_kinds(tmp_path: Path):
    _write(tmp_path, "version: 1\npolicy: {authority_default: 0.3}\n")
    assert load_ontology(tmp_path) is None


def test_load_parses_kinds_families_and_policy_annotations(tmp_path: Path):
    ont = load_ontology(_write(tmp_path, _SAMPLE))
    assert isinstance(ont, Ontology)
    assert ont.version == 1
    by_name = {k.name: k for k in (*ont.nodes, *ont.edges)}
    assert by_name["module"].family == "structural"
    assert by_name["decision"].family == "semantic"
    # weight/centrality are edge-only policy annotations
    assert by_name["governed-by"].weight == pytest.approx(0.95)
    assert by_name["governed-by"].centrality is True
    assert by_name["imports"].centrality is False
    assert by_name["module"].weight is None


def test_validation_sets_are_semantic_only_but_include_nonprompt_kinds(tmp_path: Path):
    ont = load_ontology(_write(tmp_path, _SAMPLE))
    # structural/concept kinds are NOT in the LLM validation sets
    assert ont.entity_kinds() == {"decision", "stale-claim"}
    assert ont.relationship_kinds() == {"governed-by"}


def test_prompt_bullets_exclude_nonprompt_and_nonsemantic(tmp_path: Path):
    ont = load_ontology(_write(tmp_path, _SAMPLE))
    bullets = ont.entity_bullets()
    assert "- decision:" in bullets
    assert "stale-claim" not in bullets  # prompt: false
    assert "module" not in bullets        # structural
    assert ont.relationship_bullets() == "- governed-by: Constrained by a rule."


def test_finds_file_under_dot_context_kernel(tmp_path: Path):
    ck = tmp_path / ".context-kernel"
    ck.mkdir()
    (ck / "ontology.yaml").write_text(_SAMPLE, encoding="utf-8")
    assert load_ontology(tmp_path) is not None


def test_content_hash_changes_with_content(tmp_path: Path):
    a = load_ontology(_write(tmp_path, _SAMPLE))
    b = load_ontology(_write(tmp_path, _SAMPLE + "\n# a comment\n"))
    assert a.content_hash != b.content_hash  # comments count — file is byte-hashed


def test_cache_key_incorporates_ontology_hash():
    base = _cache_key("text", "model", "", "")
    withont = _cache_key("text", "model", "", "deadbeef")
    assert base != withont


def test_summarizer_without_ontology_uses_default_prompt():
    s = LLMSummarizer("http://x", "m")
    assert s._system_prompt == _SYSTEM_PROMPT
    assert s._entity_kinds == ENTITY_KINDS
    assert s._relationship_kinds == RELATIONSHIP_KINDS
    assert s._ontology_hash == ""


def test_summarizer_with_ontology_derives_prompt_and_hash(tmp_path: Path):
    ont = load_ontology(_write(tmp_path, _SAMPLE))
    s = LLMSummarizer("http://x", "m", ontology=ont)
    assert s._ontology_hash == ont.content_hash
    assert "- decision: A resolved choice." in s._system_prompt
    assert "- governed-by: Constrained by a rule." in s._system_prompt
    assert s._entity_kinds == {"decision", "stale-claim"}


def test_committed_ontology_reproduces_default_prompt_exactly():
    """The repo's ontology.yaml must stay byte-for-byte in sync with the code fallback.

    This is the anti-drift guard (ADR-0024): the prompt built from the committed
    vocabulary must equal the hardcoded `_SYSTEM_PROMPT`. If someone edits one without
    the other, this fails — which is the whole point of a single source of truth.
    """
    ont = load_ontology(_REPO_ROOT)
    assert ont is not None, "repo ontology.yaml should load"
    from context_kernel.ingester.summarizer import build_system_prompt

    rebuilt = build_system_prompt(ont.entity_bullets(), ont.relationship_bullets())
    assert rebuilt == _SYSTEM_PROMPT
    assert ont.entity_kinds() == ENTITY_KINDS
    assert ont.relationship_kinds() == RELATIONSHIP_KINDS
