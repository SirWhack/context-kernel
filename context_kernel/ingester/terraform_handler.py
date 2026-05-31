"""Terraform (HCL) source handler for the ingester.

A regex / line-based HCL block parser. We deliberately avoid tree-sitter-hcl
(it does not build in this environment), so this walks *top-level* blocks with a
brace-depth counter and reads each block's header + body as text.

Entities are named by HCL **reference syntax** so they line up with the join
keys used in interpolations elsewhere in the configuration:

    resource "T" "N"  -> "T.N"          kind "resource"
    data     "T" "N"  -> "data.T.N"     kind "data"
    variable "N"      -> "var.N"        kind "variable"
    output   "N"      -> "output.N"     kind "output"
    module   "N"      -> "module.N"     kind "module_call"  (distinct from the
                                        file anchor's "module" kind)
    provider "T"      -> "provider.T"   kind "provider"
    locals { a = .. } -> "local.a"      kind "local"

Relationships are emitted by scanning each block body for interpolation
references to those names; the trailing attribute access (`.arn`, `.id`,
`.outputs.x`) is stripped down to the base reference. Dangling targets are left
as-is — the resolver drops edges to unknown nodes.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

from context_kernel.ingester.handlers import RawEntity, RawRelationship

logger = logging.getLogger(__name__)


# Top-level block header, e.g.  resource "aws_s3_bucket" "assets" {
#                               variable "region" {
#                               provider "aws" {
#                               locals {
_HEADER_RE = re.compile(
    r'^\s*([A-Za-z_][A-Za-z0-9_]*)'          # block type (resource, variable, …)
    r'((?:\s+"[^"]*")*)'                       # zero or more quoted labels
    r'\s*\{'                                    # opening brace
)
_LABEL_RE = re.compile(r'"([^"]*)"')

# A reference to a named entity inside a body. We match the leading dotted path
# then strip attribute access down to the base name afterwards.
#   var.region                  -> var.region
#   aws_s3_bucket.assets.arn    -> aws_s3_bucket.assets
#   data.aws_ami.x.id           -> data.aws_ami.x
#   module.vpc.outputs.subnet   -> module.vpc
#   local.common_tags           -> local.common_tags
_REF_RE = re.compile(r'\b([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+)\b')


class _Block:
    """A parsed top-level HCL block."""

    __slots__ = ("type", "labels", "body")

    def __init__(self, btype: str, labels: list[str], body: str) -> None:
        self.type = btype
        self.labels = labels
        self.body = body


class TerraformHandler:
    """Extracts resource/data/variable/output/module/provider entities from a
    Terraform (.tf) file using a brace-counting HCL block parser."""

    def supports(self, path: Path) -> bool:
        return path.suffix.lower() == ".tf"

    def extract(
        self, path: Path
    ) -> tuple[list[RawEntity], list[RawRelationship]]:
        try:
            source = path.read_text(encoding="utf-8")
            blocks = _parse_blocks(source)
        except Exception as exc:  # noqa: BLE001 — handler must be total
            logger.warning("Failed to parse %s: %s", path, exc)
            return [], []

        entities: list[RawEntity] = []
        relationships: list[RawRelationship] = []
        module_name = path.stem

        # Map each block to its reference name + kind, then emit entities.
        named: list[tuple[str, str, _Block]] = []  # (ref_name, kind, block)
        for block in blocks:
            for ref_name, kind in _block_entities(block):
                named.append((ref_name, kind, block))

        # Counts for the anchor description, by kind.
        by_kind: dict[str, list[str]] = {}
        for ref_name, kind, _block in named:
            by_kind.setdefault(kind, []).append(ref_name)

        loc = len([ln for ln in source.splitlines() if ln.strip()])
        entities.append(
            RawEntity(
                name=module_name,
                kind="module",
                description=_anchor_description(module_name, by_kind, loc),
            )
        )

        for ref_name, kind, _block in named:
            entities.append(
                RawEntity(
                    name=ref_name,
                    kind=kind,
                    description=_entity_description(ref_name, kind, module_name),
                )
            )

        # Fix A — containment edges: the file `module` anchor "contains" each
        # declared block. There is no module->member edge convention to mirror
        # (PythonHandler emits none), so we introduce `contains`. The store graph
        # is undirected (ADR-0007), so the direction below is symmetric for
        # neighbor expansion (ADR-0023): an anchor similarity hit pulls in its
        # resources, and a resource hit pulls in its anchor. We point
        # anchor -> declared block as the natural containment direction.
        contains_seen: set[str] = set()
        for ref_name, _kind, _block in named:
            if ref_name == module_name or ref_name in contains_seen:
                continue
            contains_seen.add(ref_name)
            relationships.append(
                RawRelationship(
                    source_name=module_name,
                    target_name=ref_name,
                    kind="contains",
                    description=(
                        f"{module_name}.tf declares '{ref_name}'."
                    ),
                )
            )

        # Relationships: scan each block body for references to known names.
        # We only point edges *out of* declared blocks (a block can declare one
        # entity, except `locals` which declares many — we attribute its refs to
        # all of its locals, which is rare and harmless).
        own_names = {ref_name for ref_name, _kind, _block in named}
        seen: set[tuple[str, str]] = set()
        for ref_name, _kind, block in named:
            for target in _body_references(block.body):
                if target == ref_name:
                    continue  # self-reference noise
                key = (ref_name, target)
                if key in seen:
                    continue
                seen.add(key)
                relationships.append(
                    RawRelationship(
                        source_name=ref_name,
                        target_name=target,
                        kind="references",
                        description=(
                            f"'{ref_name}' references '{target}' in {module_name}.tf."
                        ),
                    )
                )

        return entities, relationships


# --------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------


def _parse_blocks(source: str) -> list[_Block]:
    """Walk top-level HCL blocks via brace counting.

    Only top-level blocks are returned; nested blocks (e.g. `origin {}` inside a
    resource) stay as text in the parent's body, where they are scanned for
    references but never emitted as entities.
    """
    blocks: list[_Block] = []
    lines = source.splitlines()
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        # Skip blank/comment lines at top level.
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("//"):
            i += 1
            continue
        m = _HEADER_RE.match(line)
        if not m:
            i += 1
            continue

        btype = m.group(1)
        labels = _LABEL_RE.findall(m.group(2) or "")

        # Collect the body by brace counting, starting from the opening brace.
        depth = _count_braces(line)
        body_lines: list[str] = []
        i += 1
        while i < n and depth > 0:
            body_lines.append(lines[i])
            depth += _count_braces(lines[i])
            i += 1
        # If the block was a single line ( `locals {}` ), depth already 0.
        body = "\n".join(body_lines)
        blocks.append(_Block(btype, labels, body))
    return blocks


def _count_braces(line: str) -> int:
    """Net brace delta for a line, ignoring braces inside strings/comments.

    A light approximation: strip `#`/`//` line comments and the contents of
    double-quoted strings before counting. Good enough for the structural depth
    of well-formed Terraform.
    """
    # Drop line comments.
    for marker in ("#", "//"):
        idx = line.find(marker)
        if idx != -1:
            line = line[:idx]
    # Drop double-quoted string contents (handles escaped quotes loosely).
    line = re.sub(r'"(?:[^"\\]|\\.)*"', '""', line)
    return line.count("{") - line.count("}")


# --------------------------------------------------------------------------
# Entity naming
# --------------------------------------------------------------------------


def _block_entities(block: _Block) -> list[tuple[str, str]]:
    """Map a top-level block to (reference_name, kind) pairs.

    Most blocks yield exactly one; `locals` yields one per declared local;
    unrecognized block types (terraform {}, moved {}, …) yield none.
    """
    t = block.type
    labels = block.labels

    if t == "resource" and len(labels) >= 2:
        return [(f"{labels[0]}.{labels[1]}", "resource")]
    if t == "data" and len(labels) >= 2:
        return [(f"data.{labels[0]}.{labels[1]}", "data")]
    if t == "variable" and len(labels) >= 1:
        return [(f"var.{labels[0]}", "variable")]
    if t == "output" and len(labels) >= 1:
        return [(f"output.{labels[0]}", "output")]
    if t == "module" and len(labels) >= 1:
        return [(f"module.{labels[0]}", "module_call")]
    if t == "provider" and len(labels) >= 1:
        return [(f"provider.{labels[0]}", "provider")]
    if t == "locals":
        return [(f"local.{name}", "local") for name in _local_names(block.body)]
    return []


def _local_names(body: str) -> list[str]:
    """Extract top-level assignment keys from a `locals` block body."""
    names: list[str] = []
    depth = 0
    for raw in body.splitlines():
        line = raw
        # track nesting so we only pick up top-level `key =` assignments
        if depth == 0:
            m = re.match(r'\s*([A-Za-z_][A-Za-z0-9_-]*)\s*=', line)
            if m:
                names.append(m.group(1))
        depth += _count_braces(line)
    return names


# --------------------------------------------------------------------------
# Reference scanning
# --------------------------------------------------------------------------

# Prefixes whose first *two* dotted segments form the base name.
_TWO_SEG_PREFIXES = ("data.", "module.")
# Prefixes whose first *two* dotted segments form the base name (var/output/local
# are single-segment-named: var.<name>, output.<name>, local.<name>).
_ONE_NAME_PREFIXES = ("var.", "output.", "local.")


def _body_references(body: str) -> list[str]:
    """Find base reference names interpolated in a block body, de-duplicated and
    order-preserving."""
    out: list[str] = []
    seen: set[str] = set()
    for match in _REF_RE.findall(body):
        base = _base_reference(match)
        if base is None or base in seen:
            continue
        seen.add(base)
        out.append(base)
    return out


def _base_reference(ref: str) -> str | None:
    """Reduce a dotted reference to its entity base name, or None if it is not a
    recognizable entity reference.

        var.region              -> var.region
        output.url              -> output.url
        local.tags              -> local.tags
        data.aws_ami.x.id       -> data.aws_ami.x
        module.vpc.outputs.sub  -> module.vpc
        aws_s3_bucket.assets.id -> aws_s3_bucket.assets
        each.key / count.index  -> None (meta-args, not entities)
    """
    parts = ref.split(".")
    # Filter out HCL meta-argument namespaces that look like references.
    if parts[0] in ("each", "count", "self", "terraform", "path"):
        return None

    if ref.startswith(_ONE_NAME_PREFIXES):
        # var / output / local: base is prefix + first name segment.
        if len(parts) >= 2:
            return f"{parts[0]}.{parts[1]}"
        return None
    if ref.startswith(_TWO_SEG_PREFIXES):
        # data.<type>.<name> / module.<name>.<...>
        if parts[0] == "module":
            return f"module.{parts[1]}" if len(parts) >= 2 else None
        # data needs type + name
        if len(parts) >= 3:
            return f"data.{parts[1]}.{parts[2]}"
        return None
    # Otherwise treat as a resource reference: <type>.<name>.
    if len(parts) >= 2:
        return f"{parts[0]}.{parts[1]}"
    return None


# --------------------------------------------------------------------------
# Descriptions (matching PythonHandler's voice)
# --------------------------------------------------------------------------


def _anchor_description(
    module_name: str, by_kind: dict[str, list[str]], loc: int
) -> str:
    order = [
        ("resource", "resources"),
        ("data", "data sources"),
        ("variable", "variables"),
        ("output", "outputs"),
        ("module_call", "module calls"),
        ("provider", "providers"),
        ("local", "locals"),
    ]
    decl_parts = []
    for kind, label in order:
        names = by_kind.get(kind)
        if names:
            decl_parts.append(f"{len(names)} {label} ({', '.join(names)})")
    decl = "; ".join(decl_parts) if decl_parts else "no declarations"

    n_res = len(by_kind.get("resource", []))
    n_var = len(by_kind.get("variable", []))
    n_out = len(by_kind.get("output", []))
    return (
        f"Terraform infrastructure/deployment configuration '{module_name}'. "
        f"Declares: {decl}. "
        f"Depth: {n_res} resources, {n_var} variables, {n_out} outputs · {loc} LOC"
    )


def _entity_description(ref_name: str, kind: str, module_name: str) -> str:
    """Describe a Terraform block, carrying infra/deploy vocabulary.

    Fix B — terse HCL identifiers embed poorly for infra/deploy queries, so each
    description carries an "infrastructure/deployment" framing clause plus the
    concrete resource/data type when available. Framing stays factual and
    templated; we never fabricate a purpose we cannot derive from the HCL.
    """
    if kind == "resource":
        rtype, _, rname = ref_name.partition(".")
        return (
            f"{rtype} resource '{rname}' declared in {module_name}.tf. "
            f"Infrastructure/deployment resource of type {rtype} "
            f"provisioned by Terraform."
        )
    if kind == "data":
        # data.<type>.<name>
        _, rtype, rname = ref_name.split(".", 2)
        return (
            f"{rtype} data source '{rname}' declared in {module_name}.tf. "
            f"Infrastructure/deployment data lookup of type {rtype}."
        )
    if kind == "variable":
        name = ref_name.split(".", 1)[1]
        return (
            f"Terraform variable '{name}' declared in {module_name}.tf. "
            f"Infrastructure/deployment configuration input."
        )
    if kind == "output":
        name = ref_name.split(".", 1)[1]
        return (
            f"Terraform output '{name}' declared in {module_name}.tf. "
            f"Infrastructure/deployment output exported by this configuration."
        )
    if kind == "module_call":
        name = ref_name.split(".", 1)[1]
        return (
            f"Terraform module call '{name}' declared in {module_name}.tf. "
            f"Infrastructure/deployment module invocation."
        )
    if kind == "provider":
        name = ref_name.split(".", 1)[1]
        return (
            f"Terraform provider '{name}' configured in {module_name}.tf. "
            f"Infrastructure/deployment provider configuration."
        )
    if kind == "local":
        name = ref_name.split(".", 1)[1]
        return (
            f"Terraform local value '{name}' declared in {module_name}.tf. "
            f"Infrastructure/deployment configuration value."
        )
    return (
        f"'{ref_name}' declared in {module_name}.tf. "
        f"Infrastructure/deployment configuration."
    )
