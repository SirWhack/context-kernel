"""Source-format handlers. See ADR-0011 for the two-protocol design."""

from __future__ import annotations

import ast
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from tree_sitter import Node

log = logging.getLogger(__name__)


# ── Intermediate types (handler → ingest loop) ──────────────────────────


@dataclass(frozen=True)
class RawEntity:
    name: str
    kind: str
    description: str


@dataclass(frozen=True)
class RawRelationship:
    source_name: str
    target_name: str
    kind: str
    description: str


# ── Handler protocols ────────────────────────────────────────────────────


class ChunkHandler(Protocol):
    """Produce text chunks for the Summarizer (markdown, prose, PDFs)."""

    def supports(self, path: Path) -> bool: ...

    def chunks(self, path: Path) -> list[str]: ...


class StructuredHandler(Protocol):
    """Extract entities directly from structured source (Python, TS/JS)."""

    def supports(self, path: Path) -> bool: ...

    def extract(self, path: Path) -> tuple[list[RawEntity], list[RawRelationship]]: ...


# ── Markdown (ChunkHandler) ─────────────────────────────────────────────

_CHUNK_SIZE = 1500
_CHUNK_OVERLAP = 200


class MarkdownHandler:
    """v1 source handler for markdown files."""

    def supports(self, path: Path) -> bool:
        return path.suffix.lower() in {".md", ".markdown"}

    def chunks(self, path: Path) -> list[str]:
        text = path.read_text(encoding="utf-8", errors="replace")
        if not text.strip():
            return []
        if len(text) <= _CHUNK_SIZE:
            return [text]
        result: list[str] = []
        start = 0
        while start < len(text):
            end = start + _CHUNK_SIZE
            if end < len(text):
                nl = text.rfind("\n", start, end)
                if nl > start:
                    end = nl + 1
            result.append(text[start:end])
            start = end - _CHUNK_OVERLAP if end < len(text) else end
        return result


# ── Python AST (StructuredHandler) ───────────────────────────────────────


def _unparse_annotation(node: ast.expr | None) -> str | None:
    if node is None:
        return None
    return ast.unparse(node)


def _signature(func: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    parts: list[str] = []
    for arg in func.args.args:
        ann = _unparse_annotation(arg.annotation)
        parts.append(f"{arg.arg}: {ann}" if ann else arg.arg)
    ret = _unparse_annotation(func.returns)
    params = ", ".join(parts)
    ret_str = f" -> {ret}" if ret else ""
    return f"{func.name}({params}){ret_str}"


def _is_private(name: str) -> bool:
    return name.startswith("_")


def _loc(node: ast.AST) -> int:
    """Lines of code spanned by an AST node."""
    if hasattr(node, "end_lineno") and hasattr(node, "lineno"):
        return (node.end_lineno or node.lineno) - node.lineno + 1
    return 0


def _base_names(cls: ast.ClassDef) -> list[str]:
    return [ast.unparse(b) for b in cls.bases]


def _is_protocol_or_abc(cls: ast.ClassDef) -> bool:
    bases = _base_names(cls)
    return any(b in {"Protocol", "ABC", "ABCMeta"} or b.endswith(".Protocol") or b.endswith(".ABC") for b in bases)


class PythonHandler:
    """Extract module/class/function entities from Python source via AST."""

    def supports(self, path: Path) -> bool:
        return path.suffix.lower() == ".py"

    def extract(self, path: Path) -> tuple[list[RawEntity], list[RawRelationship]]:
        source = path.read_text(encoding="utf-8", errors="replace")
        if not source.strip():
            return [], []

        try:
            tree = ast.parse(source, filename=str(path))
        except SyntaxError:
            log.warning("Syntax error in %s, skipping", path)
            return [], []

        rel_path = str(path)
        entities: list[RawEntity] = []
        relationships: list[RawRelationship] = []

        module_name = path.stem
        total_loc = source.count("\n") + 1

        # ── Collect top-level definitions ────────────────────────────
        classes: list[ast.ClassDef] = []
        functions: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
        imports: list[str] = []
        top_assignments: list[str] = []

        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.ClassDef):
                classes.append(node)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                functions.append(node)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                for alias in node.names:
                    imports.append(f"{module}.{alias.name}")
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        top_assignments.append(target.id)
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                top_assignments.append(node.target.id)

        # ── Module preamble entity ───────────────────────────────────
        docstring = ast.get_docstring(tree) or ""

        all_names: list[str] | None = None
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "__all__":
                        if isinstance(node.value, (ast.List, ast.Tuple)):
                            all_names = [
                                elt.value for elt in node.value.elts
                                if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
                            ]

        export_names: list[str]
        if all_names is not None:
            export_names = all_names
        else:
            export_names = [
                c.name for c in classes if not _is_private(c.name)
            ] + [
                f.name for f in functions if not _is_private(f.name)
            ] + [
                a for a in top_assignments if not _is_private(a)
            ]

        private_constants = [a for a in top_assignments if _is_private(a)]

        exports_section = _format_exports(export_names, classes)
        private_section = ", ".join(private_constants) if private_constants else "(none)"
        imports_section = ", ".join(imports) if imports else "(none)"

        module_desc = (
            f"Module: {rel_path}\n"
            f"  Docstring: {docstring!r}\n"
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
            f"  Depth: {len(export_names)} exports, {len(private_constants)} private constants, {total_loc} LOC"
        )
        entities.append(RawEntity(name=module_name, kind="module", description=module_desc))

        for imp in imports:
            relationships.append(RawRelationship(
                source_name=module_name,
                target_name=imp,
                kind="imports",
                description=f"{module_name} imports {imp}",
            ))

        # ── Class entities ───────────────────────────────────────────
        for cls in classes:
            entities.append(_extract_class(cls, rel_path))
            for base_name in _base_names(cls):
                relationships.append(RawRelationship(
                    source_name=cls.name,
                    target_name=base_name,
                    kind="inherits",
                    description=f"{cls.name} inherits from {base_name}",
                ))

        # ── Function entities ────────────────────────────────────────
        for func in functions:
            entities.append(_extract_function(func, rel_path))

        return entities, relationships


def _format_exports(export_names: list[str], classes: list[ast.ClassDef]) -> str:
    if not export_names:
        return "(none)"
    parts: list[str] = []
    class_names = {c.name for c in classes}
    protocol_names = {c.name for c in classes if _is_protocol_or_abc(c)}
    for name in export_names:
        if name in protocol_names:
            parts.append(f"{name} (Protocol)")
        elif name in class_names:
            parts.append(f"{name} (class)")
        else:
            parts.append(name)
    return ", ".join(parts)


def _extract_class(cls: ast.ClassDef, rel_path: str) -> RawEntity:
    docstring = ast.get_docstring(cls) or ""
    bases = _base_names(cls)

    public_methods: list[str] = []
    private_methods: list[str] = []
    public_attrs: list[str] = []
    private_attrs: list[str] = []

    for node in ast.iter_child_nodes(cls):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            sig = _signature(node)
            if _is_private(node.name):
                private_methods.append(sig)
            else:
                public_methods.append(sig)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            name = node.target.id
            ann = _unparse_annotation(node.annotation)
            entry = f"{name}: {ann}" if ann else name
            if _is_private(name):
                private_attrs.append(entry)
            else:
                public_attrs.append(entry)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    if _is_private(target.id):
                        private_attrs.append(target.id)
                    else:
                        public_attrs.append(target.id)

    interface_items = public_attrs + public_methods
    internals_items = private_attrs + private_methods

    interface_str = "\n    ".join(interface_items) if interface_items else "(none)"
    internals_str = "\n    ".join(internals_items) if internals_items else "(none)"
    bases_str = ", ".join(bases) if bases else "—"

    class_loc = _loc(cls)
    n_pub = len(public_methods)
    n_priv = len(private_methods)

    desc = (
        f"Class: {cls.name}\n"
        f"  File: {rel_path}\n"
    )
    if docstring:
        desc += f"  Docstring: {docstring!r}\n"
    desc += (
        f"\n"
        f"  Interface:\n"
        f"    {interface_str}\n"
        f"\n"
        f"  Internals:\n"
        f"    {internals_str}\n"
        f"\n"
        f"  Depth: {n_pub} public methods, {n_priv} private methods, {class_loc} LOC\n"
        f"  Bases: {bases_str}"
    )

    return RawEntity(name=cls.name, kind="class", description=desc)


def _extract_function(func: ast.FunctionDef | ast.AsyncFunctionDef, rel_path: str) -> RawEntity:
    sig = _signature(func)
    visibility = "private" if _is_private(func.name) else "public"
    func_loc = _loc(func)
    docstring = ast.get_docstring(func) or ""

    desc = f"Function: {sig}\n  File: {rel_path}\n"
    if docstring:
        desc += f"  Docstring: {docstring!r}\n"
    desc += (
        f"  Visibility: {visibility}\n"
        f"  Depth: {func_loc} LOC"
    )

    return RawEntity(name=func.name, kind="function", description=desc)


# ── TypeScript/JS (StructuredHandler) ──────────────────────────────────


_TS_EXTENSIONS = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"}


def _ts_node_text(node: Node) -> str:
    return node.text.decode("utf-8") if node.text else ""


def _ts_find_child(node: Node, type_name: str) -> Node | None:
    for child in node.children:
        if child.type == type_name:
            return child
    return None


def _ts_find_children(node: Node, type_name: str) -> list[Node]:
    return [c for c in node.children if c.type == type_name]


def _ts_loc(node: Node) -> int:
    return node.end_point[0] - node.start_point[0] + 1


def _ts_has_accessibility(node: Node, modifier: str) -> bool:
    acc = _ts_find_child(node, "accessibility_modifier")
    return acc is not None and _ts_node_text(acc) == modifier


def _ts_is_private_member(node: Node) -> bool:
    if _ts_has_accessibility(node, "private") or _ts_has_accessibility(node, "protected"):
        return True
    name_node = _ts_find_child(node, "property_identifier")
    if name_node and _ts_node_text(name_node).startswith("_"):
        return True
    return False


def _ts_method_signature(node: Node) -> str:
    name_node = _ts_find_child(node, "property_identifier")
    name = _ts_node_text(name_node) if name_node else "?"
    params_node = _ts_find_child(node, "formal_parameters")
    params = _ts_node_text(params_node) if params_node else "()"
    ret_node = _ts_find_child(node, "type_annotation")
    ret = _ts_node_text(ret_node) if ret_node else ""
    static = _ts_find_child(node, "static")
    prefix = "static " if static else ""
    return f"{prefix}{name}{params}{ret}"


def _ts_function_signature(node: Node) -> str:
    name_node = (
        _ts_find_child(node, "identifier")
        or _ts_find_child(node, "type_identifier")
    )
    name = _ts_node_text(name_node) if name_node else "?"
    params_node = _ts_find_child(node, "formal_parameters")
    params = _ts_node_text(params_node) if params_node else "()"
    ret_node = _ts_find_child(node, "type_annotation")
    ret = _ts_node_text(ret_node) if ret_node else ""
    return f"{name}{params}{ret}"


def _ts_field_signature(node: Node) -> str:
    name_node = _ts_find_child(node, "property_identifier")
    name = _ts_node_text(name_node) if name_node else "?"
    type_node = _ts_find_child(node, "type_annotation")
    type_str = _ts_node_text(type_node) if type_node else ""
    return f"{name}{type_str}"


def _ts_extract_class_like(node: Node, kind_label: str, rel_path: str) -> RawEntity:
    name_node = _ts_find_child(node, "type_identifier") or _ts_find_child(node, "identifier")
    name = _ts_node_text(name_node) if name_node else "?"

    heritage = _ts_find_child(node, "class_heritage")
    bases: list[str] = []
    if heritage:
        for clause in heritage.children:
            if clause.type in ("extends_clause", "extends_type_clause"):
                for c in clause.children:
                    if c.type in ("type_identifier", "identifier", "nested_type_identifier", "generic_type"):
                        bases.append(_ts_node_text(c))
            elif clause.type == "implements_clause":
                for c in clause.children:
                    if c.type in ("type_identifier", "identifier", "nested_type_identifier", "generic_type"):
                        bases.append(f"{_ts_node_text(c)} (implements)")

    body = (
        _ts_find_child(node, "class_body")
        or _ts_find_child(node, "interface_body")
        or _ts_find_child(node, "enum_body")
    )

    public_methods: list[str] = []
    private_methods: list[str] = []
    public_attrs: list[str] = []
    private_attrs: list[str] = []

    if body:
        for member in body.children:
            if member.type in ("{", "}", ",", ";"):
                continue

            if member.type == "method_definition" or member.type == "method_signature":
                sig = _ts_method_signature(member)
                if _ts_is_private_member(member):
                    private_methods.append(sig)
                else:
                    public_methods.append(sig)

            elif member.type in ("public_field_definition", "property_signature"):
                sig = _ts_field_signature(member)
                if _ts_is_private_member(member):
                    private_attrs.append(sig)
                else:
                    public_attrs.append(sig)

            elif member.type == "property_identifier":
                member_name = _ts_node_text(member)
                public_attrs.append(member_name)

    interface_items = public_attrs + public_methods
    internals_items = private_attrs + private_methods

    interface_str = "\n    ".join(interface_items) if interface_items else "(none)"
    internals_str = "\n    ".join(internals_items) if internals_items else "(none)"
    bases_str = ", ".join(bases) if bases else "—"

    class_loc = _ts_loc(node)
    n_pub = len(public_methods)
    n_priv = len(private_methods)

    desc = (
        f"{kind_label}: {name}\n"
        f"  File: {rel_path}\n"
        f"\n"
        f"  Interface:\n"
        f"    {interface_str}\n"
        f"\n"
        f"  Internals:\n"
        f"    {internals_str}\n"
        f"\n"
        f"  Depth: {n_pub} public methods, {n_priv} private methods, {class_loc} LOC\n"
        f"  Bases: {bases_str}"
    )

    return RawEntity(name=name, kind="class", description=desc)


def _ts_extract_function(name: str, node: Node, rel_path: str, *, exported: bool) -> RawEntity:
    sig = _ts_function_signature(node)
    visibility = "public" if exported else "private"
    func_loc = _ts_loc(node)

    desc = (
        f"Function: {sig}\n"
        f"  File: {rel_path}\n"
        f"  Visibility: {visibility}\n"
        f"  Depth: {func_loc} LOC"
    )
    return RawEntity(name=name, kind="function", description=desc)


def _ts_extract_arrow_function(name: str, node: Node, rel_path: str, *, exported: bool) -> RawEntity:
    params_node = _ts_find_child(node, "formal_parameters")
    params = _ts_node_text(params_node) if params_node else "()"
    ret_node = _ts_find_child(node, "type_annotation")
    ret = _ts_node_text(ret_node) if ret_node else ""
    sig = f"{name}{params}{ret}"
    visibility = "public" if exported else "private"
    func_loc = _ts_loc(node)

    desc = (
        f"Function: {sig}\n"
        f"  File: {rel_path}\n"
        f"  Visibility: {visibility}\n"
        f"  Depth: {func_loc} LOC"
    )
    return RawEntity(name=name, kind="function", description=desc)


class TypeScriptHandler:
    """Extract module/class/function entities from TS/JS source via tree-sitter."""

    def supports(self, path: Path) -> bool:
        return path.suffix.lower() in _TS_EXTENSIONS

    def extract(self, path: Path) -> tuple[list[RawEntity], list[RawRelationship]]:
        import tree_sitter_javascript as ts_js
        import tree_sitter_typescript as ts_ts
        from tree_sitter import Language, Parser

        source_bytes = path.read_bytes()
        source_text = source_bytes.decode("utf-8", errors="replace")
        if not source_text.strip():
            return [], []

        suffix = path.suffix.lower()
        if suffix == ".tsx":
            lang = Language(ts_ts.language_tsx())
        elif suffix == ".ts":
            lang = Language(ts_ts.language_typescript())
        else:
            lang = Language(ts_js.language())

        parser = Parser(lang)
        tree = parser.parse(source_bytes)

        if tree.root_node.has_error:
            all_errors = [c for c in tree.root_node.children if c.type == "ERROR"]
            if len(all_errors) == len(tree.root_node.children) or not tree.root_node.children:
                log.warning("Parse errors in %s, skipping", path)
                return [], []

        rel_path = str(path)
        entities: list[RawEntity] = []
        relationships: list[RawRelationship] = []

        module_name = path.stem
        total_loc = source_text.count("\n") + 1

        exported_names: list[str] = []
        private_names: list[str] = []
        imports: list[str] = []
        type_aliases: list[str] = []

        class_like_types = {"class_declaration", "abstract_class_declaration"}
        interface_types = {"interface_declaration"}
        enum_types = {"enum_declaration"}
        function_types = {"function_declaration", "generator_function_declaration"}

        for node in tree.root_node.children:
            is_exported = node.type == "export_statement"
            inner = node

            if is_exported:
                decl = None
                for child in node.children:
                    if child.type not in ("export", "default", ";", "type"):
                        decl = child
                        break
                if decl is None:
                    continue
                inner = decl

            if node.type == "import_statement":
                source_node = _ts_find_child(node, "string")
                if source_node:
                    frag = _ts_find_child(source_node, "string_fragment")
                    module_path = _ts_node_text(frag) if frag else _ts_node_text(source_node).strip("'\"")
                    clause = _ts_find_child(node, "import_clause")
                    if clause:
                        named = _ts_find_child(clause, "named_imports")
                        if named:
                            for spec in named.children:
                                if spec.type == "import_specifier":
                                    spec_name = _ts_find_child(spec, "identifier")
                                    if spec_name:
                                        imports.append(f"{module_path}.{_ts_node_text(spec_name)}")
                        ns = _ts_find_child(clause, "namespace_import")
                        if ns:
                            imports.append(module_path)
                        ident = _ts_find_child(clause, "identifier")
                        if ident and not named and not ns:
                            imports.append(module_path)
                    else:
                        imports.append(module_path)
                continue

            if node.type == "expression_statement":
                expr = _ts_find_child(node, "call_expression")
                if expr:
                    fn_node = _ts_find_child(expr, "identifier")
                    if fn_node and _ts_node_text(fn_node) == "require":
                        args = _ts_find_child(expr, "arguments")
                        if args:
                            s = _ts_find_child(args, "string")
                            if s:
                                frag = _ts_find_child(s, "string_fragment")
                                imports.append(_ts_node_text(frag) if frag else _ts_node_text(s).strip("'\""))
                continue

            if inner.type in class_like_types:
                kind_label = "Class"
                ent = _ts_extract_class_like(inner, kind_label, rel_path)
                entities.append(ent)
                if is_exported:
                    exported_names.append(ent.name)
                else:
                    private_names.append(ent.name)

                heritage = _ts_find_child(inner, "class_heritage")
                if heritage:
                    for clause in heritage.children:
                        if clause.type in ("extends_clause", "extends_type_clause"):
                            for c in clause.children:
                                if c.type in ("type_identifier", "identifier", "nested_type_identifier", "generic_type"):
                                    base = _ts_node_text(c)
                                    relationships.append(RawRelationship(
                                        source_name=ent.name, target_name=base,
                                        kind="inherits", description=f"{ent.name} extends {base}",
                                    ))
                        elif clause.type == "implements_clause":
                            for c in clause.children:
                                if c.type in ("type_identifier", "identifier", "nested_type_identifier", "generic_type"):
                                    iface = _ts_node_text(c)
                                    relationships.append(RawRelationship(
                                        source_name=ent.name, target_name=iface,
                                        kind="implements", description=f"{ent.name} implements {iface}",
                                    ))

            elif inner.type in interface_types:
                ent = _ts_extract_class_like(inner, "Interface", rel_path)
                entities.append(ent)
                if is_exported:
                    exported_names.append(ent.name)
                else:
                    private_names.append(ent.name)
                heritage = _ts_find_child(inner, "extends_type_clause")
                if heritage:
                    for c in heritage.children:
                        if c.type in ("type_identifier", "identifier", "nested_type_identifier", "generic_type"):
                            base = _ts_node_text(c)
                            relationships.append(RawRelationship(
                                source_name=ent.name, target_name=base,
                                kind="inherits", description=f"{ent.name} extends {base}",
                            ))

            elif inner.type in enum_types:
                ent = _ts_extract_class_like(inner, "Enum", rel_path)
                entities.append(ent)
                if is_exported:
                    exported_names.append(ent.name)
                else:
                    private_names.append(ent.name)

            elif inner.type in function_types:
                name_node = _ts_find_child(inner, "identifier")
                fname = _ts_node_text(name_node) if name_node else "?"
                ent = _ts_extract_function(fname, inner, rel_path, exported=is_exported)
                entities.append(ent)
                if is_exported:
                    exported_names.append(fname)
                else:
                    private_names.append(fname)

            elif inner.type == "lexical_declaration":
                for declarator in _ts_find_children(inner, "variable_declarator"):
                    name_node = _ts_find_child(declarator, "identifier")
                    if not name_node:
                        continue
                    vname = _ts_node_text(name_node)
                    initializer = None
                    for c in declarator.children:
                        if c.type in ("arrow_function", "function_expression", "function"):
                            initializer = c
                            break
                    if initializer:
                        ent = _ts_extract_arrow_function(vname, initializer, rel_path, exported=is_exported)
                        entities.append(ent)
                    else:
                        pass
                    if is_exported:
                        exported_names.append(vname)
                    else:
                        private_names.append(vname)

            elif inner.type == "type_alias_declaration":
                name_node = _ts_find_child(inner, "type_identifier")
                tname = _ts_node_text(name_node) if name_node else "?"
                type_aliases.append(tname)
                if is_exported:
                    exported_names.append(tname)
                else:
                    private_names.append(tname)

            elif is_exported and inner.type == "export_clause":
                for spec in inner.children:
                    if spec.type == "export_specifier":
                        n = _ts_find_child(spec, "identifier")
                        if n:
                            exported_names.append(_ts_node_text(n))

        for imp in imports:
            relationships.append(RawRelationship(
                source_name=module_name, target_name=imp,
                kind="imports", description=f"{module_name} imports {imp}",
            ))

        # Deduplicate export/private lists
        seen_exports: set[str] = set()
        unique_exports: list[str] = []
        for n in exported_names:
            if n not in seen_exports:
                seen_exports.add(n)
                unique_exports.append(n)
        exported_names = unique_exports

        entity_names = {e.name for e in entities}
        non_entity_private = [n for n in private_names if n not in entity_names or n in type_aliases]

        exports_section = ", ".join(exported_names) if exported_names else "(none)"
        private_section = ", ".join(non_entity_private) if non_entity_private else "(none)"
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
            f"  Depth: {len(exported_names)} exports, {len(non_entity_private)} private, {total_loc} LOC"
        )
        entities.insert(0, RawEntity(name=module_name, kind="module", description=module_desc))

        return entities, relationships
