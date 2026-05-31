"""GraphQL SDL (schema) source handler for the Context Kernel ingester.

Parses ``.graphql`` / ``.gql`` schema-definition files with a line/regex-based
parser (tree-sitter-graphql does not build in this environment). GraphQL SDL
top-level definitions are regular enough to parse reliably with regex:
``type X { ... }``, ``input X { ... }``, ``enum X { ... }``,
``interface X { ... }``, ``union X = A | B``, ``scalar X``, and the
``extend type X`` variants.

Emits one anchor ``module`` entity named after the file, one child entity per
top-level definition (named by its GraphQL type name — the join key other
schemas reference as field types), and ``references`` / ``implements``
relationships so ``find`` can traverse the schema along field-type edges.
The ``Query`` / ``Mutation`` / ``Subscription`` operation roots are treated
specially: each field becomes its own entity (e.g. ``Query.game``) since those
are the API operations engineers search for.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from context_kernel.ingester.handlers import RawEntity, RawRelationship

log = logging.getLogger(__name__)

# Built-in GraphQL scalars — never targets of a "references" edge.
_BUILTIN_SCALARS = {"Int", "Float", "String", "Boolean", "ID"}

# The three operation-root type names get special treatment.
#   name -> (entity kind, per-field entity kind)
_OPERATION_KINDS = {
    "Query": ("query", "query_field"),
    "Mutation": ("mutation", "mutation_field"),
    "Subscription": ("subscription", "subscription_field"),
}

# Top-level definition openers. ``extend`` is captured so we can merge/reference.
_DEF_RE = re.compile(
    r"^\s*(?P<extend>extend\s+)?"
    r"(?P<keyword>type|input|enum|interface|union|scalar)\s+"
    r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)"
    r"(?P<rest>.*)$"
)

# A field line inside a braced body: ``name(args): Type`` or ``name: Type``.
_FIELD_RE = re.compile(
    r"^\s*(?P<fname>[A-Za-z_][A-Za-z0-9_]*)\s*"
    r"(?:\((?P<args>.*)\))?\s*:\s*(?P<ftype>[^\s].*?)\s*$"
)

_GQL_EXTENSIONS = {".graphql", ".gql"}


def _base_type(type_expr: str) -> str:
    """Strip list/non-null wrappers from a GraphQL type expression -> base name.

    ``[[Int!]!]!`` -> ``Int``; ``SudokuGame!`` -> ``SudokuGame``.
    """
    name = re.sub(r"[\[\]!]", "", type_expr).strip()
    m = re.match(r"[A-Za-z_][A-Za-z0-9_]*", name)
    return m.group(0) if m else ""


class GraphQLHandler:
    """Extract schema entities from GraphQL SDL files via a regex parser."""

    def supports(self, path: Path) -> bool:
        return path.suffix.lower() in _GQL_EXTENSIONS

    def extract(
        self, path: Path
    ) -> tuple[list[RawEntity], list[RawRelationship]]:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
            return self._extract(path, text)
        except Exception:  # never raise on malformed input
            log.warning("Failed to parse %s as GraphQL, skipping", path)
            return [], []

    # ------------------------------------------------------------------ #
    def _extract(
        self, path: Path, text: str
    ) -> tuple[list[RawEntity], list[RawRelationship]]:
        if not text.strip():
            return [], []

        rel_path = str(path)
        entities: list[RawEntity] = []
        relationships: list[RawRelationship] = []
        defined: list[str] = []  # names listed in the module description

        lines = self._strip_descriptions(text.splitlines())
        i = 0
        n = len(lines)
        while i < n:
            m = _DEF_RE.match(lines[i])
            if not m:
                i += 1
                continue

            keyword = m.group("keyword")
            name = m.group("name")
            rest = m.group("rest")
            is_extend = bool(m.group("extend"))

            if keyword == "scalar":
                if not is_extend:
                    entities.append(
                        RawEntity(
                            name=name,
                            kind="scalar",
                            description=(
                                f"GraphQL scalar: {name}\n  File: {rel_path}"
                            ),
                        )
                    )
                    defined.append(f"{name} (scalar)")
                i += 1
                continue

            if keyword == "union":
                members = self._union_members(rest, lines, i)
                if not is_extend:
                    desc = f"GraphQL union: {name}\n  File: {rel_path}\n"
                    desc += (
                        f"  Members: "
                        f"{' | '.join(members) if members else '(none)'}"
                    )
                    entities.append(
                        RawEntity(name=name, kind="union", description=desc)
                    )
                    defined.append(f"{name} (union)")
                for member in members:
                    relationships.append(
                        RawRelationship(
                            source_name=name,
                            target_name=member,
                            kind="references",
                            description=f"{name} is one of {member}",
                        )
                    )
                i = self._skip_union(lines, i)
                continue

            # Braced definitions: type / input / enum / interface.
            body, end = self._read_body(lines, i)

            if keyword == "enum":
                if not is_extend:
                    values = self._enum_values(body)
                    desc = f"GraphQL enum: {name}\n  File: {rel_path}\n"
                    desc += (
                        f"  Values: "
                        f"{', '.join(values) if values else '(none)'}"
                    )
                    entities.append(
                        RawEntity(name=name, kind="enum", description=desc)
                    )
                    defined.append(f"{name} (enum)")
                i = end
                continue

            if keyword == "interface":
                fields = self._fields(body)
                if not is_extend:
                    entities.append(
                        RawEntity(
                            name=name,
                            kind="interface",
                            description=self._object_desc(
                                "interface", name, rel_path, fields
                            ),
                        )
                    )
                    defined.append(f"{name} (interface)")
                self._emit_field_refs(name, fields, relationships)
                i = end
                continue

            # keyword == "type" or "input"
            if keyword == "type" and name in _OPERATION_KINDS:
                op_kind, field_kind = _OPERATION_KINDS[name]
                fields = self._fields(body)
                if not is_extend:
                    op_names = [f[0] for f in fields]
                    desc = (
                        f"GraphQL {op_kind} root: {name}\n  File: {rel_path}\n"
                    )
                    desc += (
                        "  Operations: "
                        + (", ".join(op_names) if op_names else "(none)")
                    )
                    entities.append(
                        RawEntity(name=name, kind=op_kind, description=desc)
                    )
                    defined.append(f"{name} ({op_kind})")
                # Each operation field is itself a searchable entity.
                for fname, ftype, args in fields:
                    op_entity_name = f"{name}.{fname}"
                    sig = (
                        f"{fname}({args}): {ftype}"
                        if args
                        else f"{fname}: {ftype}"
                    )
                    desc = (
                        f"GraphQL {op_kind} operation: {sig}\n"
                        f"  File: {rel_path}\n"
                        f"  Returns: {_base_type(ftype) or ftype}"
                    )
                    entities.append(
                        RawEntity(
                            name=op_entity_name,
                            kind=field_kind,
                            description=desc,
                        )
                    )
                    base = _base_type(ftype)
                    if base and base not in _BUILTIN_SCALARS:
                        relationships.append(
                            RawRelationship(
                                source_name=op_entity_name,
                                target_name=base,
                                kind="references",
                                description=f"{op_entity_name} returns {base}",
                            )
                        )
                i = end
                continue

            # Ordinary object or input type.
            kind = "input" if keyword == "input" else "type"
            fields = self._fields(body)
            if not is_extend:
                entities.append(
                    RawEntity(
                        name=name,
                        kind=kind,
                        description=self._object_desc(
                            kind, name, rel_path, fields
                        ),
                    )
                )
                defined.append(f"{name} ({kind})")
            else:
                # extend type X -> reference the type being extended.
                relationships.append(
                    RawRelationship(
                        source_name=name,
                        target_name=name,
                        kind="extends",
                        description=f"extends {kind} {name}",
                    )
                )
            for iface in self._implements(rest):
                relationships.append(
                    RawRelationship(
                        source_name=name,
                        target_name=iface,
                        kind="implements",
                        description=f"{name} implements {iface}",
                    )
                )
            self._emit_field_refs(name, fields, relationships)
            i = end
            continue

        module_name = path.stem
        total_loc = text.count("\n") + 1
        defined_section = ", ".join(defined) if defined else "(none)"
        module_desc = (
            f"GraphQL schema: {rel_path}\n"
            f"\n"
            f"  Defines:\n"
            f"    {defined_section}\n"
            f"\n"
            f"  Depth: {len(defined)} definitions, {total_loc} LOC"
        )
        entities.insert(
            0, RawEntity(name=module_name, kind="module", description=module_desc)
        )
        return entities, relationships

    # ------------------------------------------------------------------ #
    # helpers
    # ------------------------------------------------------------------ #
    def _strip_descriptions(self, lines: list[str]) -> list[str]:
        """Blank out triple-quoted description blocks and ``#`` comments.

        Preserves line count so indices stay aligned with the source.
        """
        out: list[str] = []
        in_block = False
        for line in lines:
            s = line.strip()
            if in_block:
                out.append("")
                if s.endswith('"""'):
                    in_block = False
                continue
            if s.startswith('"""'):
                # single-line """desc"""?
                if len(s) >= 6 and s.endswith('"""'):
                    out.append("")
                    continue
                in_block = True
                out.append("")
                continue
            if s.startswith("#"):
                out.append("")
                continue
            out.append(line)
        return out

    def _read_body(self, lines: list[str], start: int) -> tuple[list[str], int]:
        """Return (body_lines, index_after_closing_brace) for a brace block.

        Scans from ``start`` for the opening ``{``. If none is found on the
        definition line, returns ([], start+1) (e.g. a bare ``type X``).
        ``body_lines`` holds the raw lines strictly between the braces.
        """
        n = len(lines)
        # Locate the opening brace; it must be on the definition line.
        open_idx = start
        if "{" not in lines[start]:
            return [], start + 1

        body: list[str] = []
        depth = 0
        j = open_idx
        while j < n:
            line = lines[j]
            opens = line.count("{")
            closes = line.count("}")
            prev_depth = depth
            depth += opens - closes

            if j == open_idx:
                # Content after the first '{' on the opening line.
                after = line.split("{", 1)[1]
                if depth <= 0:
                    # Single-line block: '{ ... }'
                    inner = after.rsplit("}", 1)[0]
                    if inner.strip():
                        body.append(inner)
                    return body, j + 1
                if after.strip():
                    body.append(after)
            else:
                if depth <= 0:
                    # This line closes the block.
                    inner = line.rsplit("}", 1)[0]
                    if inner.strip():
                        body.append(inner)
                    return body, j + 1
                body.append(line)
            j += 1
            _ = prev_depth  # (kept for clarity; unused)
        return body, n

    def _fields(self, body: list[str]) -> list[tuple[str, str, str]]:
        """Parse field lines -> list of (name, type_expr, args)."""
        fields: list[tuple[str, str, str]] = []
        for line in body:
            if not line.strip():
                continue
            m = _FIELD_RE.match(line)
            if m:
                fields.append(
                    (
                        m.group("fname"),
                        m.group("ftype").strip(),
                        (m.group("args") or "").strip(),
                    )
                )
        return fields

    def _enum_values(self, body: list[str]) -> list[str]:
        values: list[str] = []
        for line in body:
            s = line.strip()
            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", s):
                values.append(s)
        return values

    def _object_desc(self, kind: str, name: str, rel_path: str, fields) -> str:
        rendered = (
            "\n    ".join(f"{fn}: {ft}" for fn, ft, _ in fields)
            if fields
            else "(none)"
        )
        return (
            f"GraphQL {kind}: {name}\n"
            f"  File: {rel_path}\n"
            f"\n"
            f"  Fields:\n"
            f"    {rendered}\n"
            f"\n"
            f"  Depth: {len(fields)} fields"
        )

    def _emit_field_refs(self, owner: str, fields, relationships) -> None:
        for _fn, ftype, _args in fields:
            base = _base_type(ftype)
            if base and base not in _BUILTIN_SCALARS:
                relationships.append(
                    RawRelationship(
                        source_name=owner,
                        target_name=base,
                        kind="references",
                        description=f"{owner} references {base}",
                    )
                )

    def _implements(self, rest: str) -> list[str]:
        m = re.search(r"implements\s+(.+?)(?:\{|$)", rest)
        if not m:
            return []
        return re.findall(r"[A-Za-z_][A-Za-z0-9_]*", m.group(1))

    def _union_members(self, rest: str, lines: list[str], idx: int) -> list[str]:
        text = rest
        if "=" not in text:
            for k in range(idx + 1, min(idx + 4, len(lines))):
                text += " " + lines[k]
                if "=" in lines[k]:
                    break
        if "=" not in text:
            return []
        rhs = text.split("=", 1)[1]
        return re.findall(r"[A-Za-z_][A-Za-z0-9_]*", rhs)

    def _skip_union(self, lines: list[str], idx: int) -> int:
        if "=" in lines[idx]:
            j = idx + 1
        else:
            j = idx + 1
            for k in range(idx + 1, min(idx + 6, len(lines))):
                if "=" in lines[k]:
                    j = k + 1
                    break
        while j < len(lines) and lines[j].lstrip().startswith("|"):
            j += 1
        return j
