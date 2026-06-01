"""EntityResolver — code-anchored, within-project identity merging. See ADR-0017.

Runs after all raw entities/relationships are collected (structured + chunk phases),
before embedding/upsert. Collapses the same logical concept (code def + docs + ADRs)
into one canonical node so the graph is traversable across altitudes, and re-resolves
every relationship endpoint to a canonical id (dropping, never phantom-minting, the
unresolvable ones). Pure function of its inputs — no I/O, no network.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Sequence

from context_kernel.source_kinds import CODE_EXT, is_code_path

# Names too generic to ever carry concept identity — never merged across files.
STOPLIST = frozenset({"__init__", "__call__", "__main__", "main", "run", "setup", "conftest", "handler"})
_ARTICLES = frozenset({"the", "a", "an"})


@dataclass
class ExtractedEntity:
    name: str
    kind: str
    source_file: str
    description: str = ""
    embedding: Sequence[float] | None = None


@dataclass
class ExtractedRelationship:
    source_name: str
    target_name: str
    kind: str
    source_file: str
    description: str = ""


@dataclass
class CanonicalEntity:
    id: str
    name: str
    kind: str
    description: str
    is_code: bool
    aliases: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    kinds: list[str] = field(default_factory=list)
    embedding: Sequence[float] | None = None


@dataclass
class ResolvedRelationship:
    source_id: str
    target_id: str
    kind: str
    description: str = ""


def normalize(name: str) -> str:
    """Conservative: casefold, collapse non-alphanumerics, drop articles. No suffix stripping (ADR-0017)."""
    toks = [t for t in re.sub(r"[^a-z0-9]+", " ", name.strip().lower()).split() if t and t not in _ARTICLES]
    return "".join(toks)


def _is_code(source_file: str) -> bool:
    return is_code_path(source_file)


def _cosine(a: Sequence[float] | None, b: Sequence[float] | None) -> float:
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def _code_id(project: str | None, name: str, source_file: str) -> str:
    return hashlib.sha256(f"{project or ''}|code|{name}|{source_file}".encode()).hexdigest()


def _concept_id(project: str | None, base: str) -> str:
    return hashlib.sha256(f"{project or ''}|concept|{base}".encode()).hexdigest()


def _cluster_key(e: ExtractedEntity) -> str:
    base = normalize(e.name)
    if e.name in STOPLIST or base in STOPLIST or not base:
        return f"\x00local\x00{e.source_file}\x00{base or e.name}"
    return base


def resolve(
    entities: list[ExtractedEntity],
    relationships: list[ExtractedRelationship],
    *,
    project: str | None = None,
    similarity_threshold: float = 0.82,
) -> tuple[list[CanonicalEntity], list[ResolvedRelationship], dict]:
    """Merge entities into canonical nodes and resolve relationship endpoints to canonical ids."""
    groups: dict[str, list[ExtractedEntity]] = defaultdict(list)
    for e in entities:
        groups[_cluster_key(e)].append(e)

    canonical: dict[str, CanonicalEntity] = {}
    exact_index: dict[tuple[str, str], str] = {}   # (name, source_file) -> canonical id
    name_index: dict[str, str] = {}                # unambiguous base/surface -> canonical id
    ambiguous_bases: set[str] = set()

    def _new_node(cid, name, kind, desc, is_code, embedding=None):
        canonical[cid] = CanonicalEntity(id=cid, name=name, kind=kind, description=desc,
                                         is_code=is_code, aliases=[], sources=[], kinds=[],
                                         embedding=embedding)
        return canonical[cid]

    def _absorb(node: CanonicalEntity, e: ExtractedEntity):
        if e.name not in node.aliases:
            node.aliases.append(e.name)
        if e.source_file not in node.sources:
            node.sources.append(e.source_file)
        if e.kind and e.kind not in node.kinds:
            node.kinds.append(e.kind)
        exact_index[(e.name, e.source_file)] = node.id

    for key, members in groups.items():
        base = normalize(members[0].name)
        code_members = [m for m in members if _is_code(m.source_file)]
        noncode = [m for m in members if not _is_code(m.source_file)]
        # A distinct code definition is a unique (name, file) — so a module `root` and a
        # class `Root` in the same file stay distinct, never collapsed by normalization.
        code_defs: dict[tuple[str, str], ExtractedEntity] = {}
        for m in code_members:
            code_defs.setdefault((m.name, m.source_file), m)

        if len(code_defs) <= 1:
            # ── unambiguous: one canonical node for the whole cluster ──
            anchor = next(iter(code_defs.values())) if code_defs else max(members, key=lambda m: len(m.description))
            is_code = bool(code_defs)
            cid = _code_id(project, anchor.name, anchor.source_file) if is_code else _concept_id(project, base or key)
            node = _new_node(cid, anchor.name, anchor.kind, anchor.description, is_code, anchor.embedding)
            for m in members:
                _absorb(node, m)
            if not key.startswith("\x00local\x00"):
                name_index[base] = cid
                for m in members:
                    name_index.setdefault(m.name, cid)
        else:
            # ── ambiguous: keep each code def distinct; attach docs only on 2nd signal ──
            ambiguous_bases.add(base)
            def_nodes = []
            for m in code_defs.values():
                cid = _code_id(project, m.name, m.source_file)
                node = _new_node(cid, m.name, m.kind, m.description, True, m.embedding)
                node._emb = m.embedding  # type: ignore[attr-defined]  # transient, for attach scoring
                _absorb(node, m)
                def_nodes.append(node)
            leftover = []
            for m in noncode:
                best, best_sim = None, 0.0
                for node in def_nodes:
                    sim = _cosine(m.embedding, getattr(node, "_emb", None))
                    if sim > best_sim:
                        best, best_sim = node, sim
                if best is not None and best_sim >= similarity_threshold:
                    _absorb(best, m)            # second signal agrees → attach to that definition
                else:
                    leftover.append(m)           # no signal → stays a concept node
            if leftover:
                cid = _concept_id(project, base or key)
                cnode = _new_node(cid, leftover[0].name, leftover[0].kind, leftover[0].description, False, leftover[0].embedding)
                for m in leftover:
                    _absorb(cnode, m)
            # ambiguous base is intentionally NOT added to name_index (forces same-file or drop)

    for node in canonical.values():
        if hasattr(node, "_emb"):
            delattr(node, "_emb")
        node.aliases.sort()
        node.sources.sort()
        node.kinds.sort()

    # File-path index: a target like "src/bot/agent.py" deterministically resolves to that
    # file's module node (and unique basenames too). Catches the LLM citing code locations
    # verbatim — high precision, no embeddings, no LLM (ADR-0017 Stage-2 addition).
    file_module_id: dict[str, str] = {}
    basename_module_id: dict[str, str | None] = {}
    for node in canonical.values():
        if "module" not in node.kinds:
            continue
        for s in node.sources:
            if not _is_code(s):
                continue
            file_module_id[s] = node.id
            b = s.rsplit("/", 1)[-1]
            basename_module_id[b] = node.id if basename_module_id.get(b, node.id) == node.id else None

    def _looks_like_path(name: str) -> bool:
        return "/" in name or name.endswith(CODE_EXT)

    def _resolve_endpoint(name: str, source_file: str) -> str | None:
        if _looks_like_path(name):
            p = name.strip().lstrip("./").rstrip("/")
            if p in file_module_id:
                return file_module_id[p]
            base = p.rsplit("/", 1)[-1]
            if basename_module_id.get(base):
                return basename_module_id[base]
            # a bare directory ("src/pipeline/") has no single module → fall through
        cid = exact_index.get((name, source_file))
        if cid:
            return cid
        b = normalize(name)
        if b in ambiguous_bases:
            return None                          # ambiguous and not same-file → drop, never guess
        hit = name_index.get(b) or name_index.get(name)
        if hit:
            return hit
        # Dotted import/inherits target — e.g. "open_webui.retrieval.vector.main.VectorDBBase"
        # or "fastapi.APIRouter". The full dotted path never matches a bare entity name, so
        # internal dependency edges were dropped wholesale and the graph went ~95% edgeless
        # (contradicting ADR-0021, which treats `imports`/`inherits` as first-class facts).
        # Resolve to the imported SYMBOL (last segment), then the MODULE (penultimate),
        # honoring the same "never guess an ambiguous base" rule. External libs stay unresolved.
        if "." in name:
            # A relative-import target can be all dots ("." for `from . import x`, ".." for a
            # parent package), leaving no non-empty segment — guard before indexing or the
            # whole ingest crashes with IndexError (and, with rm-state-first, wipes the graph).
            segs = [s for s in name.split(".") if s]
            cand = ([segs[-1]] + ([segs[-2]] if len(segs) >= 2 else [])) if segs else []
            for seg in cand:
                nb = normalize(seg)
                if nb and nb not in ambiguous_bases:
                    hit = name_index.get(nb) or name_index.get(seg)
                    if hit:
                        return hit
        return None

    seen: set[tuple[str, str, str]] = set()
    resolved: list[ResolvedRelationship] = []
    dropped = 0
    for r in relationships:
        sid = _resolve_endpoint(r.source_name, r.source_file)
        tid = _resolve_endpoint(r.target_name, r.source_file)
        if not sid or not tid or sid == tid:
            dropped += 1
            continue
        k = (sid, tid, r.kind)
        if k in seen:
            continue
        seen.add(k)
        resolved.append(ResolvedRelationship(source_id=sid, target_id=tid, kind=r.kind, description=r.description))

    nodes = list(canonical.values())
    def _has_doc(n): return any(s.endswith(".md") for s in n.sources)
    by_id = {n.id: n for n in nodes}
    cross = sum(1 for e in resolved
                if (by_id[e.source_id].is_code and _has_doc(by_id[e.target_id]))
                or (by_id[e.target_id].is_code and _has_doc(by_id[e.source_id])))
    stats = {
        "raw_entities": len(entities),
        "canonical_nodes": len(nodes),
        "multi_source_nodes": sum(1 for n in nodes if len(n.sources) >= 2),
        "code_and_doc_nodes": sum(1 for n in nodes if n.is_code and _has_doc(n)),
        "raw_relationships": len(relationships),
        "resolved_edges": len(resolved),
        "dropped_edges": dropped,
        "cross_altitude_edges": cross,
        "ambiguous_names": len(ambiguous_bases),
    }
    return nodes, resolved, stats
