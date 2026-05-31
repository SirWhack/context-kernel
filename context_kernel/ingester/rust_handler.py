"""Rust source handler: parse a ``.rs`` file into entities + relationships.

Mirrors :class:`context_kernel.ingester.handlers.TypeScriptHandler` — a
``StructuredHandler`` that uses tree-sitter (lazy-imported inside ``extract``),
walks ``root_node.children``, and never raises. On any failure it logs a warning
and returns ``([], [])``.

Entity kinds / naming
---------------------
* One anchor entity of kind ``module`` named after the file stem.
* ``struct`` / ``enum`` / ``trait`` items -> kinds ``struct`` / ``enum`` / ``trait``.
* ``fn`` items -> kind ``function`` (visibility ``public`` iff ``pub``).
* ``impl Type { ... }`` and ``impl Trait for Type { ... }``: each method is emitted
  as a ``function`` entity named ``Type::method`` (qualified so methods of distinct
  types don't collide). The impl block itself gets no entity.
* Inline ``mod name { ... }`` -> a child ``module`` entity; its items descend one
  level. ``mod name;`` (file declaration) -> an import-like reference only.

Relationships (``RawRelationship(source_name, target_name, kind, description)``)
-------------------------------------------------------------------------------
* ``use a::b::C;`` -> ``(module, C, "imports")`` — last path segment, matching the
  Python/TS handlers' dotted-import convention. Brace lists emit one per symbol.
* ``impl Trait for Type`` -> ``(Type, Trait, "implements")``.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from context_kernel.ingester.handlers import RawEntity, RawRelationship

if TYPE_CHECKING:
    from tree_sitter import Node

log = logging.getLogger(__name__)

# Top-level item node types that become child entities.
_DECL_KINDS = {
    "struct_item": "struct",
    "enum_item": "enum",
    "trait_item": "trait",
    "function_item": "function",
}


class RustHandler:
    """Extract module/struct/enum/trait/function entities from Rust via tree-sitter."""

    def supports(self, path: Path) -> bool:
        return path.suffix.lower() == ".rs"

    def extract(self, path: Path) -> tuple[list[RawEntity], list[RawRelationship]]:
        import tree_sitter_rust as ts_rust
        from tree_sitter import Language, Parser

        source = path.read_bytes()
        source_text = source.decode("utf-8", errors="replace")
        if not source_text.strip():
            return [], []

        lang = Language(ts_rust.language())
        parser = Parser(lang)
        tree = parser.parse(source)
        root = tree.root_node

        if root.has_error:
            all_errors = [c for c in root.children if c.type == "ERROR"]
            if len(all_errors) == len(root.children) or not root.children:
                log.warning("Parse errors in %s, skipping", path)
                return [], []

        rel_path = str(path)
        module_name = path.stem
        total_loc = source_text.count("\n") + 1

        entities: list[RawEntity] = []
        relationships: list[RawRelationship] = []
        exports: list[str] = []
        private: list[str] = []
        imports: list[str] = []

        self._walk_items(
            root.children,
            parent=module_name,
            depth=0,
            source=source,
            rel_path=rel_path,
            entities=entities,
            relationships=relationships,
            exports=exports,
            private=private,
            imports=imports,
        )

        exports_section = ", ".join(exports) if exports else "(none)"
        private_section = ", ".join(private) if private else "(none)"
        imports_section = ", ".join(imports) if imports else "(none)"
        module_desc = (
            f"Module: {rel_path}\n"
            f"\n"
            f"  Exports:\n"
            f"    {exports_section}\n"
            f"\n"
            f"  Private:\n"
            f"    {private_section}\n"
            f"\n"
            f"  Imports:\n"
            f"    {imports_section}\n"
            f"\n"
            f"  Depth: {len(exports)} exports, {len(private)} private, {total_loc} LOC"
        )
        entities.insert(0, RawEntity(name=module_name, kind="module", description=module_desc))

        return entities, relationships

    def _walk_items(
        self,
        children,
        *,
        parent: str,
        depth: int,
        source: bytes,
        rel_path: str,
        entities: list[RawEntity],
        relationships: list[RawRelationship],
        exports: list[str],
        private: list[str],
        imports: list[str],
    ) -> None:
        """Process sibling items under ``parent``.

        ``exports``/``private``/``imports`` are only populated at the top level
        (depth 0); inner ``mod`` items still emit entities + relationships but
        don't pollute the file's orientation block.
        """
        top_level = depth == 0

        for child in children:
            if child.type == "use_declaration":
                for sym in _rs_use_targets(child, source):
                    relationships.append(RawRelationship(
                        source_name=parent, target_name=sym,
                        kind="imports", description=f"{parent} imports {sym}",
                    ))
                    if top_level:
                        imports.append(sym)

            elif child.type == "mod_item":
                name = _rs_field_text(child, "name", source)
                if not name:
                    continue
                body = child.child_by_field_name("body")
                if body is None:
                    # `mod name;` — a file declaration, treated as import-like.
                    relationships.append(RawRelationship(
                        source_name=parent, target_name=name,
                        kind="imports", description=f"{parent} declares module {name}",
                    ))
                    if top_level:
                        imports.append(name)
                    continue
                # Inline `mod name { ... }` — emit a module entity and descend.
                if top_level:
                    (exports if _rs_is_pub(child) else private).append(name)
                entities.append(RawEntity(
                    name=name, kind="module",
                    description=_rs_inline_mod_desc(name, body, rel_path, source),
                ))
                if depth == 0:
                    self._walk_items(
                        body.children, parent=name, depth=depth + 1, source=source,
                        rel_path=rel_path, entities=entities, relationships=relationships,
                        exports=exports, private=private, imports=imports,
                    )

            elif child.type in _DECL_KINDS:
                name = _rs_field_text(child, "name", source)
                if not name:
                    continue
                if top_level:
                    (exports if _rs_is_pub(child) else private).append(name)
                entities.append(RawEntity(
                    name=name, kind=_DECL_KINDS[child.type],
                    description=_rs_decl_desc(child, rel_path, source),
                ))

            elif child.type == "impl_item":
                self._handle_impl(
                    child, source=source, rel_path=rel_path,
                    entities=entities, relationships=relationships,
                )

    def _handle_impl(
        self,
        node: Node,
        *,
        source: bytes,
        rel_path: str,
        entities: list[RawEntity],
        relationships: list[RawRelationship],
    ) -> None:
        type_node = node.child_by_field_name("type")
        trait_node = node.child_by_field_name("trait")
        type_name = _rs_simple_name(_rs_node_text(type_node, source)) if type_node else "?"

        if trait_node is not None:
            trait_name = _rs_simple_name(_rs_node_text(trait_node, source))
            relationships.append(RawRelationship(
                source_name=type_name, target_name=trait_name,
                kind="implements", description=f"{type_name} implements {trait_name}",
            ))

        body = node.child_by_field_name("body")
        if body is None:
            return
        for m in body.children:
            if m.type != "function_item":
                continue
            mname = _rs_field_text(m, "name", source)
            if not mname:
                continue
            qualified = f"{type_name}::{mname}"
            entities.append(RawEntity(
                name=qualified, kind="function",
                description=_rs_fn_desc(m, rel_path, source, owner=type_name),
            ))


# ── Description helpers (mirror the TypeScript handler's style) ───────────


def _rs_inline_mod_desc(name: str, body: Node, rel_path: str, source: bytes) -> str:
    items = []
    for c in body.children:
        if c.type in _DECL_KINDS or c.type == "mod_item":
            n = c.child_by_field_name("name")
            if n is not None:
                items.append(_rs_node_text(n, source))
    items_str = ", ".join(items) if items else "(none)"
    return f"Module: {name}\n  File: {rel_path}\n\n  Items:\n    {items_str}"


def _rs_decl_desc(node: Node, rel_path: str, source: bytes) -> str:
    if node.type == "struct_item":
        return _rs_struct_desc(node, rel_path, source)
    if node.type == "enum_item":
        return _rs_enum_desc(node, rel_path, source)
    if node.type == "trait_item":
        return _rs_trait_desc(node, rel_path, source)
    return _rs_fn_desc(node, rel_path, source)


def _rs_struct_desc(node: Node, rel_path: str, source: bytes) -> str:
    name = _rs_field_text(node, "name", source) or "?"
    body = node.child_by_field_name("body")
    pub_fields: list[str] = []
    priv_fields: list[str] = []
    if body is not None:
        for f in body.children:
            if f.type != "field_declaration":
                continue
            nm = _rs_field_text(f, "name", source)
            if nm:
                (pub_fields if _rs_is_pub(f) else priv_fields).append(nm)
    interface_str = ", ".join(pub_fields) if pub_fields else "(none)"
    internals_str = ", ".join(priv_fields) if priv_fields else "(none)"
    return (
        f"Struct: {name}\n  File: {rel_path}\n"
        f"\n  Interface:\n    {interface_str}\n"
        f"\n  Internals:\n    {internals_str}"
    )


def _rs_enum_desc(node: Node, rel_path: str, source: bytes) -> str:
    name = _rs_field_text(node, "name", source) or "?"
    body = node.child_by_field_name("body")
    variants = []
    if body is not None:
        for v in body.children:
            if v.type == "enum_variant":
                nm = _rs_field_text(v, "name", source)
                if nm:
                    variants.append(nm)
    variants_str = ", ".join(variants) if variants else "(none)"
    return f"Enum: {name}\n  File: {rel_path}\n\n  Variants:\n    {variants_str}"


def _rs_trait_desc(node: Node, rel_path: str, source: bytes) -> str:
    name = _rs_field_text(node, "name", source) or "?"
    body = node.child_by_field_name("body")
    methods = []
    if body is not None:
        for m in body.children:
            if m.type in ("function_signature_item", "function_item"):
                methods.append(_rs_fn_signature(m, source))
    methods_str = "\n    ".join(methods) if methods else "(none)"
    return f"Trait: {name}\n  File: {rel_path}\n\n  Methods:\n    {methods_str}"


def _rs_fn_signature(node: Node, source: bytes) -> str:
    name = _rs_field_text(node, "name", source) or "?"
    params = node.child_by_field_name("parameters")
    sig = _rs_node_text(params, source) if params is not None else "()"
    ret = node.child_by_field_name("return_type")
    suffix = f" -> {_rs_node_text(ret, source)}" if ret is not None else ""
    return f"{name}{sig}{suffix}"


def _rs_fn_desc(node: Node, rel_path: str, source: bytes, *, owner: str | None = None) -> str:
    sig = _rs_fn_signature(node, source)
    visibility = "public" if _rs_is_pub(node) else "private"
    owner_line = f"  Owner: {owner}\n" if owner else ""
    return (
        f"Function: {sig}\n  File: {rel_path}\n{owner_line}"
        f"  Visibility: {visibility}"
    )


# ── Node helpers ──────────────────────────────────────────────────────────


def _rs_node_text(node: Node, source: bytes) -> str:
    return source[node.start_byte:node.end_byte].decode("utf-8", "replace")


def _rs_field_text(node: Node, field: str, source: bytes) -> str | None:
    c = node.child_by_field_name(field)
    return _rs_node_text(c, source) if c is not None else None


def _rs_is_pub(node: Node) -> bool:
    return any(c.type == "visibility_modifier" for c in node.children)


def _rs_strip_generics(text: str) -> str:
    return text.split("<")[0].strip()


def _rs_simple_name(text: str) -> str:
    """Last ``::`` segment with generics stripped — e.g. ``fmt::Display`` -> ``Display``.

    Matches the last-segment convention used for ``use`` imports, so an impl's
    trait/type names resolve to the same bare identifiers other handlers emit.
    """
    base = _rs_strip_generics(text)
    return base.split("::")[-1].strip() if base else base


def _rs_use_targets(use_node: Node, source: bytes) -> list[str]:
    """Resolve a ``use`` declaration to imported symbol names (last segment).

    Mirrors the Python/TS convention of taking the final path component. Brace
    lists (``use a::b::{C, D}``) yield one target per imported symbol.
    """
    arg = use_node.child_by_field_name("argument")
    return _rs_collect_use(arg, source) if arg is not None else []


def _rs_collect_use(node: Node, source: bytes) -> list[str]:
    if node.type in ("scoped_use_list", "use_list"):
        out: list[str] = []
        for c in node.children:
            if c.type in ("identifier", "type_identifier"):
                out.append(_rs_node_text(c, source))
            elif c.type in ("scoped_identifier", "scoped_use_list", "use_list", "use_as_clause"):
                out.extend(_rs_collect_use(c, source))
        return out
    if node.type == "use_as_clause":
        alias = node.child_by_field_name("alias")
        if alias is not None:
            return [_rs_node_text(alias, source)]
        path = node.child_by_field_name("path")
        return _rs_collect_use(path, source) if path is not None else []
    if node.type == "scoped_identifier":
        name = node.child_by_field_name("name")
        if name is not None and name.type in ("scoped_use_list", "use_list"):
            return _rs_collect_use(name, source)
        if name is not None:
            return [_rs_node_text(name, source)]
        last = None
        for c in node.children:
            if c.type in ("identifier", "type_identifier"):
                last = c
        return [_rs_node_text(last, source)] if last is not None else []
    if node.type in ("identifier", "type_identifier"):
        return [_rs_node_text(node, source)]
    return []
