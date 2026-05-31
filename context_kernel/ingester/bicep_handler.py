"""Bicep (Azure IaC) source handler.

Bicep top-level declarations are line-oriented and regular, so this is a
regex/line-based StructuredHandler (there is no tree-sitter Bicep grammar).
It mirrors the PythonHandler/TypeScriptHandler contract: one anchor `module`
entity per file plus child entities named by Bicep *symbolic-reference syntax*
(the symbolic name is the join key other declarations use to reference a thing):

    resource stg 'Microsoft.Storage/storageAccounts@2023-01-01' = { ... }
        -> name "stg"   kind "resource"  (Azure type captured in description)
    resource kv  'Microsoft.KeyVault/vaults@2023-07-01' existing = ...
        -> name "kv"    kind "resource"  (noted as existing in description)
    param location string = resourceGroup().location
        -> name "location"  kind "param"
    var prefix = 'app-${env}'
        -> name "prefix"    kind "var"
    output endpoint string = stg.properties.primaryEndpoints.blob
        -> name "endpoint"  kind "output"
    module vpc 'modules/vpc.bicep' = { ... }
        -> name "vpc"   kind "module_call"  (referenced path captured in desc)

Relationships are emitted by scanning each declaration body for bare references
to other symbolic names; the trailing attribute access (`.id`, `.properties.x`,
`.outputs.x`) is stripped to the base symbolic name. Bicep references are bare
identifiers, so to bound false positives we only emit a `references` edge when
the target matches a symbolic name actually declared in THIS file.

See ADR-0011 for the two-protocol handler design.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from context_kernel.ingester.handlers import RawEntity, RawRelationship

log = logging.getLogger(__name__)


# ── Top-level declaration patterns ──────────────────────────────────────
#
# Bicep declarations are line-anchored. We capture the symbolic name (the
# identifier immediately after the keyword) because that is how other
# declarations reference the thing.

#   resource stg 'Microsoft.Storage/storageAccounts@2023-01-01' = { ... }
#   resource kv  'Microsoft.KeyVault/vaults@2023-07-01' existing = ...
_RESOURCE_RE = re.compile(
    r"^\s*resource\s+([A-Za-z_][A-Za-z0-9_]*)\s+"
    r"'([^'@]+)(?:@[^']*)?'\s*"
    r"(existing\b)?",
)

#   module vpc 'modules/vpc.bicep' = { ... }
#   module net '../shared/net.bicep' = ...
_MODULE_RE = re.compile(
    r"^\s*module\s+([A-Za-z_][A-Za-z0-9_]*)\s+'([^']+)'\s*",
)

#   param location string
#   param location string = resourceGroup().location
_PARAM_RE = re.compile(
    r"^\s*param\s+([A-Za-z_][A-Za-z0-9_]*)\s+([A-Za-z_][A-Za-z0-9_\[\]?]*)",
)

#   output endpoint string = stg.properties.primaryEndpoints.blob
_OUTPUT_RE = re.compile(
    r"^\s*output\s+([A-Za-z_][A-Za-z0-9_]*)\s+([A-Za-z_][A-Za-z0-9_\[\]?]*)",
)

#   var prefix = 'app-${location}'
_VAR_RE = re.compile(
    r"^\s*var\s+([A-Za-z_][A-Za-z0-9_]*)\s*=",
)

# A bare identifier (used to scan a declaration body for references to other
# symbolic names). We strip attribute tails (`.id`, `.outputs.x`) to the base.
_IDENT_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\b")

# Identifiers that are Bicep/ARM built-ins or keywords, never symbolic names.
_BUILTINS = frozenset({
    "resource", "module", "param", "output", "var", "targetScope", "metadata",
    "type", "func", "import", "existing", "if", "for", "in", "true", "false",
    "null", "string", "int", "bool", "object", "array",
})


def _strip_body_comments(line: str) -> str:
    """Drop a trailing // line comment (best-effort, ignores strings)."""
    idx = line.find("//")
    return line[:idx] if idx != -1 else line


class _Decl:
    """A captured top-level declaration plus its body lines (for ref scan)."""

    __slots__ = ("name", "kind", "header", "body_lines")

    def __init__(self, name: str, kind: str, header: str) -> None:
        self.name = name
        self.kind = kind
        self.header = header
        self.body_lines: list[str] = []


class BicepHandler:
    """Extract module/resource/param/var/output/module_call entities from .bicep.

    Regex/line-based: Bicep top-level declarations are regular. Never raises —
    on any failure it logs a warning and returns ([], []). Child entities are
    named by their Bicep symbolic name so they join with references elsewhere.
    """

    def supports(self, path: Path) -> bool:
        return path.suffix.lower() == ".bicep"

    def extract(self, path: Path) -> tuple[list[RawEntity], list[RawRelationship]]:
        try:
            return self._extract(path)
        except Exception:  # never raise — a bad file must not abort ingest
            log.warning("Failed to parse Bicep file %s, skipping", path, exc_info=True)
            return [], []

    def _extract(self, path: Path) -> tuple[list[RawEntity], list[RawRelationship]]:
        source = path.read_text(encoding="utf-8", errors="replace")
        if not source.strip():
            return [], []

        rel_path = str(path)
        module_name = path.stem
        lines = source.splitlines()
        total_loc = len(lines)

        decls: list[_Decl] = []
        resource_descr: list[str] = []   # for the module anchor summary
        param_names: list[str] = []
        output_names: list[str] = []

        current: _Decl | None = None

        for raw in lines:
            line = _strip_body_comments(raw)

            # A top-level declaration starts with a keyword; everything until the
            # next top-level declaration is treated as the current decl's body.
            m = _RESOURCE_RE.match(line)
            if m:
                name, rtype, existing = m.group(1), m.group(2), m.group(3)
                suffix = " (existing)" if existing else ""
                current = _Decl(name, "resource", f"{name}: {rtype}{suffix}")
                decls.append(current)
                resource_descr.append(f"{name} [{rtype}{suffix}]")
                continue

            m = _MODULE_RE.match(line)
            if m:
                name, ref = m.group(1), m.group(2)
                current = _Decl(name, "module_call", f"{name} -> {ref}")
                current.body_lines.append(f"path:{ref}")  # carry ref for description
                decls.append(current)
                continue

            m = _PARAM_RE.match(line)
            if m:
                name, ptype = m.group(1), m.group(2)
                current = _Decl(name, "param", f"{name}: {ptype}")
                decls.append(current)
                param_names.append(name)
                continue

            m = _OUTPUT_RE.match(line)
            if m:
                name, otype = m.group(1), m.group(2)
                current = _Decl(name, "output", f"{name}: {otype}")
                decls.append(current)
                output_names.append(name)
                # outputs reference symbolic names on the same line
                current.body_lines.append(line)
                continue

            m = _VAR_RE.match(line)
            if m:
                name = m.group(1)
                current = _Decl(name, "var", name)
                decls.append(current)
                current.body_lines.append(line)
                continue

            # Non-declaration line → body of the current declaration (if any).
            if current is not None:
                current.body_lines.append(line)

        # ── Build entities ───────────────────────────────────────────
        entities: list[RawEntity] = []
        relationships: list[RawRelationship] = []

        declared_names = {d.name for d in decls}

        # Anchor module entity (PythonHandler module style).
        resources_section = ", ".join(resource_descr) if resource_descr else "(none)"
        params_section = ", ".join(param_names) if param_names else "(none)"
        outputs_section = ", ".join(output_names) if output_names else "(none)"
        n_res = len(resource_descr)
        n_mod = sum(1 for d in decls if d.kind == "module_call")
        n_var = sum(1 for d in decls if d.kind == "var")

        module_desc = (
            f"Bicep template: {rel_path}\n"
            f"\n"
            f"  Resources:\n"
            f"    {resources_section}\n"
            f"\n"
            f"  Params:\n"
            f"    {params_section}\n"
            f"\n"
            f"  Outputs:\n"
            f"    {outputs_section}\n"
            f"\n"
            f"  Depth: {n_res} resources, {n_mod} module calls, "
            f"{len(param_names)} params, {n_var} vars, "
            f"{len(output_names)} outputs, {total_loc} LOC"
        )
        entities.append(RawEntity(name=module_name, kind="module", description=module_desc))

        # Child entities + reference relationships.
        for decl in decls:
            kind_label = {
                "resource": "Resource",
                "module_call": "Module call",
                "param": "Param",
                "var": "Var",
                "output": "Output",
            }.get(decl.kind, decl.kind)

            child_desc = f"{kind_label}: {decl.header}\n  File: {rel_path}"
            entities.append(RawEntity(name=decl.name, kind=decl.kind, description=child_desc))

            # Scan the body for references to other declared symbolic names.
            seen_targets: set[str] = set()
            for body_line in decl.body_lines:
                for ident in _IDENT_RE.findall(body_line):
                    if ident == decl.name:
                        continue
                    if ident in _BUILTINS:
                        continue
                    # Only emit when target is a symbolic name declared in THIS
                    # file — bounds false positives from bare identifiers.
                    if ident not in declared_names:
                        continue
                    if ident in seen_targets:
                        continue
                    seen_targets.add(ident)
                    relationships.append(RawRelationship(
                        source_name=decl.name,
                        target_name=ident,
                        kind="references",
                        description=f"{decl.name} references {ident}",
                    ))

        return entities, relationships
