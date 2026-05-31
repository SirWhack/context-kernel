"""HTML source handler (StructuredHandler).

HTML is borderline structured (DESIGN-REFERENCE §7.1): it has no public API
surface the way Python/TS does, but its skeleton — title, headings,
id-bearing elements, and asset/link references — is real navigable structure.
This handler extracts that skeleton with the stdlib ``html.parser.HTMLParser``
(zero dependencies, no tree-sitter), emitting one ``module`` anchor per file
plus capped child entities for headings, id'd elements, scripts, and links.

Entity kinds: ``module`` (file anchor), ``heading``, ``element``, ``script``,
``link``. Relationships: the anchor ``references`` each script src / link href /
anchor href so ``find`` can traverse asset and link graphs.
"""

from __future__ import annotations

import logging
import re
from html.parser import HTMLParser
from pathlib import Path

from context_kernel.ingester.handlers import RawEntity, RawRelationship

log = logging.getLogger(__name__)

# Cap total child entities so a pathological page (thousands of id'd nodes)
# cannot blow up the graph. The anchor notes when this cap was hit.
_MAX_CHILD_ENTITIES = 200

_HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
_WS_RE = re.compile(r"\s+")
_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(text: str) -> str:
    """``Getting Started`` -> ``getting-started``. Empty -> ``section``."""
    slug = _SLUG_RE.sub("-", text.lower()).strip("-")
    return slug or "section"


class _Collector(HTMLParser):
    """Single-pass scan collecting the structural skeleton of a document."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title: str = ""
        # Ordered, de-duplicated structural findings.
        self.headings: list[tuple[int, str]] = []  # (level, text)
        self.elements: list[tuple[str, str, str]] = []  # (id, tag, classes)
        self.scripts: list[str] = []  # src values
        self.links: list[str] = []  # href values (link + a)

        self._seen_ids: set[str] = set()
        self._seen_links: set[str] = set()
        # Heading capture state (stack handles nested/malformed markup).
        self._heading_stack: list[tuple[int, list[str]]] = []
        # Title capture state.
        self._in_title = False
        self._title_parts: list[str] = []

    # ── tag handling ────────────────────────────────────────────────
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        attr_map = {k.lower(): (v or "") for k, v in attrs}

        if tag == "title":
            self._in_title = True

        # id-bearing element (any tag) → one element entity, de-duped by id.
        el_id = attr_map.get("id", "").strip()
        if el_id and el_id not in self._seen_ids:
            self._seen_ids.add(el_id)
            self.elements.append((el_id, tag, attr_map.get("class", "").strip()))

        if tag in _HEADING_TAGS:
            self._heading_stack.append((int(tag[1]), []))

        if tag == "script":
            src = attr_map.get("src", "").strip()
            if src:
                self.scripts.append(src)

        if tag == "link":
            self._add_link(attr_map.get("href", ""))

        if tag == "a":
            self._add_link(attr_map.get("href", ""))

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "title":
            self._in_title = False
        if tag in _HEADING_TAGS and self._heading_stack:
            level, parts = self._heading_stack.pop()
            text = _WS_RE.sub(" ", "".join(parts)).strip()
            if text:
                self.headings.append((level, text))

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._title_parts.append(data)
        # Innermost open heading accumulates its text.
        if self._heading_stack:
            self._heading_stack[-1][1].append(data)

    # ── helpers ─────────────────────────────────────────────────────
    def _add_link(self, href: str | None) -> None:
        href = (href or "").strip()
        if not href or href == "#":
            return
        if href in self._seen_links:
            return
        self._seen_links.add(href)
        self.links.append(href)

    def finalize(self) -> None:
        """Flush any unterminated <title>/<heading> (lenient/malformed input)."""
        self.title = _WS_RE.sub(" ", "".join(self._title_parts)).strip()
        while self._heading_stack:
            level, parts = self._heading_stack.pop()
            text = _WS_RE.sub(" ", "".join(parts)).strip()
            if text:
                self.headings.append((level, text))


class HTMLHandler:
    """Extract a structural skeleton from HTML files via stdlib HTMLParser.

    Borderline structured source (DESIGN-REFERENCE §7.1): always returns the
    file anchor even for near-pure-prose pages — it is a StructuredHandler and
    never falls back to chunking.
    """

    def supports(self, path: Path) -> bool:
        return path.suffix.lower() in {".html", ".htm"}

    def extract(self, path: Path) -> tuple[list[RawEntity], list[RawRelationship]]:
        source = path.read_text(encoding="utf-8", errors="replace")
        if not source.strip():
            return [], []

        collector = _Collector()
        try:
            collector.feed(source)
            collector.close()
        except Exception as exc:  # HTMLParser is lenient, but never raise.
            log.warning("Failed to parse %s, skipping: %s", path, exc)
            return [], []
        collector.finalize()

        rel_path = str(path)
        module_name = path.stem
        total_loc = source.count("\n") + 1

        entities: list[RawEntity] = []
        relationships: list[RawRelationship] = []

        # ── Child entities, capped collectively ──────────────────────
        children: list[RawEntity] = []

        for level, text in collector.headings:
            children.append(RawEntity(
                name=_slugify(text),
                kind="heading",
                description=f"Heading (h{level}): {text}\n  File: {rel_path}",
            ))

        for el_id, tag, classes in collector.elements:
            cls = classes if classes else "(none)"
            children.append(RawEntity(
                name=f"#{el_id}",
                kind="element",
                description=f"Element: <{tag} id=\"{el_id}\">\n  File: {rel_path}\n  Classes: {cls}",
            ))

        for src in collector.scripts:
            children.append(RawEntity(
                name=src,
                kind="script",
                description=f"Script source: {src}\n  Referenced by: {rel_path}",
            ))

        for href in collector.links:
            children.append(RawEntity(
                name=href,
                kind="link",
                description=f"Link target: {href}\n  Referenced by: {rel_path}",
            ))

        capped = len(children) > _MAX_CHILD_ENTITIES
        if capped:
            children = children[:_MAX_CHILD_ENTITIES]

        # ── File anchor (module-kind, PythonHandler module style) ─────
        title_line = f"  Title: {collector.title!r}\n" if collector.title else ""
        cap_line = (
            f"\n  NOTE: child entities capped at {_MAX_CHILD_ENTITIES}"
            if capped else ""
        )
        module_desc = (
            f"HTML document: {rel_path}\n"
            f"{title_line}"
            f"\n"
            f"  Structure:\n"
            f"    {len(collector.headings)} headings\n"
            f"    {len(collector.elements)} elements with id\n"
            f"    {len(collector.scripts)} scripts\n"
            f"    {len(collector.links)} links\n"
            f"\n"
            f"  Depth: {len(children)} child entities, {total_loc} LOC"
            f"{cap_line}"
        )
        entities.append(RawEntity(name=module_name, kind="module", description=module_desc))
        entities.extend(children)

        # ── references relationships (anchor → asset/link targets) ────
        for target in collector.scripts + collector.links:
            relationships.append(RawRelationship(
                source_name=module_name,
                target_name=target,
                kind="references",
                description=f"{module_name} references {target}",
            ))

        return entities, relationships
