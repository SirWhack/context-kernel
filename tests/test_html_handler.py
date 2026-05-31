"""Tests for HTMLHandler — structural-skeleton extraction from HTML source."""

from __future__ import annotations

from pathlib import Path

from context_kernel.ingester.handlers import RawEntity, RawRelationship
from context_kernel.ingester.html_handler import HTMLHandler

_FIXTURE = """<!DOCTYPE html>
<html lang="en">
<head>
    <title>Acme Dashboard</title>
    <link rel="stylesheet" href="styles/main.css">
</head>
<body>
    <h1>Getting Started</h1>
    <div id="app" class="container main">
        <h2>Quick Links</h2>
        <a href="/docs">Docs</a>
        <a href="https://example.com">External</a>
        <a href="#">Skip me</a>
        <a href="">Skip me too</a>
        <a href="/docs">Duplicate docs</a>
    </div>
    <p>Just some prose with no structure of its own.</p>
    <script src="js/app.js"></script>
</body>
</html>
"""


def _extract(
    tmp_path: Path, filename: str, source: str
) -> tuple[list[RawEntity], list[RawRelationship]]:
    path = tmp_path / filename
    path.write_text(source, encoding="utf-8")
    handler = HTMLHandler()
    assert handler.supports(path)
    return handler.extract(path)


def _by_kind(entities: list[RawEntity], kind: str) -> list[RawEntity]:
    return [e for e in entities if e.kind == kind]


def test_supports_html_and_htm(tmp_path: Path) -> None:
    handler = HTMLHandler()
    assert handler.supports(tmp_path / "page.html")
    assert handler.supports(tmp_path / "page.HTM")
    assert not handler.supports(tmp_path / "page.md")
    assert not handler.supports(tmp_path / "page.py")


def test_emits_module_anchor_with_title_and_counts(tmp_path: Path) -> None:
    entities, _ = _extract(tmp_path, "index.html", _FIXTURE)

    anchors = _by_kind(entities, "module")
    assert len(anchors) == 1
    anchor = anchors[0]
    assert anchor.name == "index"
    assert "Acme Dashboard" in anchor.description
    assert "2 headings" in anchor.description
    assert "1 elements with id" in anchor.description
    assert "1 scripts" in anchor.description
    assert "Depth:" in anchor.description and "LOC" in anchor.description


def test_emits_heading_entities(tmp_path: Path) -> None:
    entities, _ = _extract(tmp_path, "index.html", _FIXTURE)

    headings = _by_kind(entities, "heading")
    names = {e.name for e in headings}
    assert "getting-started" in names
    assert "quick-links" in names
    desc = next(e.description for e in headings if e.name == "getting-started")
    assert "h1" in desc and "Getting Started" in desc


def test_emits_id_element_entity_with_tag_and_classes(tmp_path: Path) -> None:
    entities, _ = _extract(tmp_path, "index.html", _FIXTURE)

    elements = _by_kind(entities, "element")
    assert len(elements) == 1
    app = elements[0]
    assert app.name == "#app"
    assert "div" in app.description
    assert "container main" in app.description


def test_emits_script_entity(tmp_path: Path) -> None:
    entities, _ = _extract(tmp_path, "index.html", _FIXTURE)

    scripts = _by_kind(entities, "script")
    assert {e.name for e in scripts} == {"js/app.js"}


def test_emits_link_entities_deduped_and_skips_empty(tmp_path: Path) -> None:
    entities, _ = _extract(tmp_path, "index.html", _FIXTURE)

    links = {e.name for e in _by_kind(entities, "link")}
    assert "styles/main.css" in links  # <link href>
    assert "/docs" in links            # <a href>
    assert "https://example.com" in links
    assert "#" not in links            # skipped
    assert "" not in links             # skipped
    # /docs appears twice in source but is de-duplicated.
    assert sum(1 for e in entities if e.name == "/docs") == 1


def test_emits_references_relationships(tmp_path: Path) -> None:
    _, relationships = _extract(tmp_path, "index.html", _FIXTURE)

    assert relationships, "expected at least one reference relationship"
    assert all(r.kind == "references" for r in relationships)
    assert all(r.source_name == "index" for r in relationships)
    targets = {r.target_name for r in relationships}
    assert "js/app.js" in targets         # script src
    assert "styles/main.css" in targets   # link href
    assert "/docs" in targets             # a href
    assert "#" not in targets             # not referenced


def test_empty_file_returns_nothing(tmp_path: Path) -> None:
    entities, relationships = _extract(tmp_path, "blank.html", "   \n  ")
    assert entities == []
    assert relationships == []


def test_prose_only_page_still_returns_anchor(tmp_path: Path) -> None:
    # Section 7.1: near-pure prose is acceptable — return the anchor, don't
    # fall back to a ChunkHandler.
    source = "<html><body><p>Lorem ipsum dolor sit amet.</p></body></html>"
    entities, relationships = _extract(tmp_path, "prose.html", source)
    assert len(entities) == 1
    assert entities[0].kind == "module"
    assert entities[0].name == "prose"
    assert relationships == []


def test_malformed_html_does_not_raise(tmp_path: Path) -> None:
    source = '<html><h1>Hi<div id="x"><script src="a.js"></html'
    entities, _ = _extract(tmp_path, "broken.html", source)
    # Lenient parser still recovers the skeleton; must never raise.
    names = {e.name for e in entities}
    assert "broken" in names
    assert "#x" in names


def test_child_entities_are_capped(tmp_path: Path) -> None:
    # 500 id'd elements -> capped at 200 children, anchor notes it.
    body = "".join(f'<div id="n{i}"></div>' for i in range(500))
    source = f"<html><body>{body}</body></html>"
    entities, _ = _extract(tmp_path, "big.html", source)

    children = [e for e in entities if e.kind != "module"]
    assert len(children) == 200
    anchor = next(e for e in entities if e.kind == "module")
    assert "capped at 200" in anchor.description


def test_corpus_sudoku_page_if_present() -> None:
    # Validate against the real vibe-coded corpus page when available.
    # This is a Vite scaffold: #root element + /src/main.tsx script.
    repo_root = Path(__file__).resolve().parent.parent
    page = repo_root / "test-repos/vibe-coded/sudoku/web/index.html"
    if not page.exists():
        return
    handler = HTMLHandler()
    entities, relationships = handler.extract(page)

    kinds = {e.kind for e in entities}
    assert "module" in kinds
    assert any(e.kind == "element" for e in entities)
    assert any(e.kind == "script" for e in entities)
    # Every script src becomes a `references` edge from the file anchor.
    script_names = {e.name for e in entities if e.kind == "script"}
    ref_targets = {r.target_name for r in relationships if r.kind == "references"}
    assert script_names
    assert script_names <= ref_targets
