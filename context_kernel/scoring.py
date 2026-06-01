"""Scoring — the single home for every confidence/relevance table and formula.

Pure, total, no I/O. Implements ADR-0015 (axes), ADR-0019 (materialize-at-ingest /
compose-at-query), ADR-0020 (drift), ADR-0021 (edge families). `ingest` and `find`
*call* this module; they never inline a tier number or a formula, and this module never
touches the filesystem, git, or the clock.

Knob resolution (per ADR-0015): hardcoded default → `[ingester.scoring]` config →
`CK_SCORING_*` env var (highest wins). Resolution is a pure function of
`(config_section, env_mapping)` — `ScoringConfig.resolve(...)`. The caller supplies
`os.environ`; this module reads nothing on its own.

Errors-out-of-existence (ADR-0019 §10 lens): the scoring functions never raise. Missing
data yields a defined neutral result — no sources → default authority; size 0 → drift 0;
no edges → node_drift 0; unknown kind → mid weight.
"""

from __future__ import annotations

import fnmatch
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol

from context_kernel.source_kinds import IAC_EXT, is_code_path, is_ops_path

# ── Default tables (ADR-0015) ───────────────────────────────────────────────
# Tier name → authority weight. Source paths are classified to a tier by `classify_source`.
AUTHORITY_TIERS: dict[str, float] = {
    "THEORY": 1.0,        # trunk — constrains everything
    "ARCHITECTURE": 0.95,  # module ownership contract
    "ADR": 0.9,           # settled decision
    "CODE": 0.85,         # always current for what IS
    "OVERVIEW": 0.85,     # repo trunk / top-level orientation doc — capped AT code (ADR-0022)
    "CONTEXT": 0.8,       # canonical vocabulary
    "REFERENCE": 0.8,     # authored understanding
    "OPS": 0.6,           # operational reference (deploy / run / configure) — ADR-0022.
                          # Also carries Infrastructure-as-Code (.tf/.hcl/.bicep/.tf.json/.tfvars):
                          # parsed structurally (authoritative for what IS) but terse/boilerplate,
                          # so it sits between code and prose docs rather than in the prose catch-all.
    "SPEC": 0.5,          # weeks shelf-life
    "EPHEMERAL": 0.2,     # disposable context
}
AUTHORITY_DEFAULT = 0.3   # unmatched prose — lean low (the HANDOFF lesson)

# Edge-kind → weight (ADR-0015 Axis 4 / ADR-0021 families). Serves both proximity
# propagation and drift aggregation — one decision, reused.
EDGE_WEIGHTS: dict[str, float] = {
    "governed-by": 0.95,  # semantic
    "implements": 0.9,    # structural (parser)
    "inherits": 0.9,      # structural (parser)
    "realizes": 0.9,      # semantic
    "implemented-by": 0.9,  # concept hub → code grounding (deterministic ontology alias)
    "manifested-by": 0.7,   # aspect-concept hub → code (recall-then-judge, ADR-0025 §4)
    "supersedes": 0.85,   # semantic
    "addresses": 0.7,     # semantic
    "calls": 0.6,         # structural — orchestration depth (ADR-0021)
    "motivates": 0.5,     # semantic
    "imports": 0.3,       # structural — ubiquitous, starved so it doesn't flood
}
EDGE_WEIGHT_DEFAULT = 0.5  # unknown kind — mid

# Dependency-bearing kinds that count toward centrality (ADR-0015 Axis 3 / ADR-0021).
# Structural `implements`/`inherits` + semantic `realizes`/`governed-by`. `imports`
# (pure noise) and the weak/historical kinds are excluded.
CENTRALITY_KINDS = frozenset({"implements", "inherits", "realizes", "governed-by", "implemented-by"})

DRIFT_HOPS = 1            # propagation hops for drift (ADR-0020 — one hop, no cascade)
PROXIMITY_HOPS = 1        # propagation hops for find proximity (ADR-0015 Axis 4)
CENTRALITY_IN_FIND = False  # whether centrality enters the find score (off — relevance ≠ centrality)

# ADR-0023: query-time neighbor expansion. Relevance flows from a seed along an edge as
# seed_score × edge_weight(kind) × hop_decay × neighbor_confidence. No kind allowlist — the
# edge_weight table is the gate (imports@0.3 self-starves; governed-by@0.95 surfaces).
EXPANSION_ENABLED = True
EXPANSION_HOP_DECAY = 0.6   # per-hop attenuation (1 hop today; bounds expansion below its seed)
EXPANSION_MAX = 5           # cap on neighbors admitted (guardrail, not policy)
EXPANSION_MIN_RATIO = 0.5   # admit a neighbor only if its score ≥ ratio × weakest direct hit

_ENV_PREFIX = "CK_SCORING_"


@dataclass(frozen=True)
class ScoringConfig:
    """Resolved knobs. Construct via `resolve`; `DEFAULTS` is the no-override instance."""

    authority_tiers: Mapping[str, float] = field(default_factory=lambda: dict(AUTHORITY_TIERS))
    authority_default: float = AUTHORITY_DEFAULT
    # Per-repo role declarations: glob (relative source path) → tier name. The LOCAL
    # assignment layer (PROTOTYPE: repo roles) — what each prose file *is* in this repo.
    # The tier *number* it maps to stays GLOBAL (authority_tiers), so a role means the
    # same thing across every project in a shared portfolio graph. Empty = pure heuristic.
    roles: Mapping[str, str] = field(default_factory=dict)
    edge_weights: Mapping[str, float] = field(default_factory=lambda: dict(EDGE_WEIGHTS))
    edge_weight_default: float = EDGE_WEIGHT_DEFAULT
    centrality_kinds: frozenset[str] = CENTRALITY_KINDS
    drift_hops: int = DRIFT_HOPS
    proximity_hops: int = PROXIMITY_HOPS
    centrality_in_find: bool = CENTRALITY_IN_FIND
    expansion_enabled: bool = EXPANSION_ENABLED
    expansion_hop_decay: float = EXPANSION_HOP_DECAY
    expansion_max: int = EXPANSION_MAX
    expansion_min_ratio: float = EXPANSION_MIN_RATIO

    @classmethod
    def resolve(
        cls,
        section: Mapping[str, object] | None = None,
        env: Mapping[str, str] | None = None,
    ) -> "ScoringConfig":
        """Build a config from defaults, overlaying config section then env (highest).

        Pure: `env` is passed in (e.g. `os.environ`), never read here. A malformed knob
        value raises (a misconfigured sweep should be loud) — this is config-time, distinct
        from the never-raise contract on the scoring functions themselves.
        """
        section = section or {}
        env = env or {}

        tiers = dict(AUTHORITY_TIERS)
        tiers.update({str(k).upper(): float(v) for k, v in _sub(section, "authority_tiers").items()})
        authority_default = float(section.get("authority_default", AUTHORITY_DEFAULT))

        weights = dict(EDGE_WEIGHTS)
        weights.update({str(k).lower(): float(v) for k, v in _sub(section, "edge_weights").items()})
        edge_weight_default = float(section.get("edge_weight_default", EDGE_WEIGHT_DEFAULT))

        # Local role assignment: glob → tier name (value uppercased to match the global ruler).
        # A role names a GLOBAL tier; the assignment is repo-local but the valuation is not
        # (ADR-0022). An unknown tier name is a config error — fail loud, don't silently
        # fall through to the prose catch-all.
        roles = {str(k).lower(): str(v).upper() for k, v in _sub(section, "roles").items()}
        unknown = sorted(set(roles.values()) - set(tiers))
        if unknown:
            raise ValueError(
                f"scoring.roles references unknown tier(s) {unknown}; "
                f"known tiers: {sorted(tiers)} (define one under [ingester.scoring.authority_tiers])"
            )

        drift_hops = int(section.get("drift_hops", DRIFT_HOPS))
        proximity_hops = int(section.get("proximity_hops", PROXIMITY_HOPS))
        centrality_in_find = _as_bool(section.get("centrality_in_find", CENTRALITY_IN_FIND))
        expansion_enabled = _as_bool(section.get("expansion", EXPANSION_ENABLED))
        expansion_hop_decay = float(section.get("expansion_hop_decay", EXPANSION_HOP_DECAY))
        expansion_max = int(section.get("expansion_max", EXPANSION_MAX))
        expansion_min_ratio = float(section.get("expansion_min_ratio", EXPANSION_MIN_RATIO))

        for key, raw in env.items():
            if not key.startswith(_ENV_PREFIX):
                continue
            rest = key[len(_ENV_PREFIX):]
            if rest == "AUTHORITY_DEFAULT":
                authority_default = float(raw)
            elif rest.startswith("AUTHORITY_"):
                tiers[rest[len("AUTHORITY_"):].upper()] = float(raw)
            elif rest == "EDGE_WEIGHT_DEFAULT":
                edge_weight_default = float(raw)
            elif rest.startswith("EDGE_WEIGHT_"):
                # Hyphenated kinds (e.g. governed-by) are config-only; env uses lowercase.
                weights[rest[len("EDGE_WEIGHT_"):].lower()] = float(raw)
            elif rest == "DRIFT_HOPS":
                drift_hops = int(raw)
            elif rest == "PROXIMITY_HOPS":
                proximity_hops = int(raw)
            elif rest == "CENTRALITY_IN_FIND":
                centrality_in_find = _as_bool(raw)
            elif rest == "EXPANSION":
                expansion_enabled = _as_bool(raw)
            elif rest == "EXPANSION_HOP_DECAY":
                expansion_hop_decay = float(raw)
            elif rest == "EXPANSION_MAX":
                expansion_max = int(raw)
            elif rest == "EXPANSION_MIN_RATIO":
                expansion_min_ratio = float(raw)

        return cls(
            authority_tiers=tiers,
            authority_default=authority_default,
            roles=roles,
            edge_weights=weights,
            edge_weight_default=edge_weight_default,
            centrality_kinds=CENTRALITY_KINDS,
            drift_hops=drift_hops,
            proximity_hops=proximity_hops,
            centrality_in_find=centrality_in_find,
            expansion_enabled=expansion_enabled,
            expansion_hop_decay=expansion_hop_decay,
            expansion_max=expansion_max,
            expansion_min_ratio=expansion_min_ratio,
        )


DEFAULTS = ScoringConfig()


def _sub(section: Mapping[str, object], key: str) -> Mapping[str, object]:
    val = section.get(key, {})
    return val if isinstance(val, Mapping) else {}


def _as_bool(v: object) -> bool:
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in {"1", "true", "yes", "on"}


# ── Axis 1: Authority ───────────────────────────────────────────────────────

_ADR_NAME = re.compile(r"^\d{3,4}[-_].*\.md$")


def classify_source(path: str, cfg: ScoringConfig = DEFAULTS) -> str:
    """Map a source path to an authority tier name, or "" for the catch-all (prose).

    Resolution order: per-repo role declarations (`cfg.roles`, most-specific glob wins)
    override the built-in filename heuristics. Roles are the LOCAL assignment ("what is
    this file in *this* repo?"); the tier they name is valued GLOBALLY (authority_tiers),
    so the same role is comparable across a shared portfolio graph. Code is matched by
    extension, so the catch-all only ever applies to prose — an unrecognized doc is far
    likelier to be scratch than a missed THEORY.md.
    """
    p = path.replace("\\", "/").lower()
    base = p.rsplit("/", 1)[-1]

    if cfg.roles:
        hits = [
            pat for pat in cfg.roles
            if fnmatch.fnmatch(p, pat) or fnmatch.fnmatch(base, pat)
        ]
        if hits:
            # Most-specific glob wins: fewest wildcards, then longest literal.
            best = max(hits, key=lambda pat: (-pat.count("*"), len(pat)))
            return cfg.roles[best]

    if base == "theory.md":
        return "THEORY"
    if base == "architecture.md":
        return "ARCHITECTURE"
    if "docs/adr/" in p or "/adr/" in p or _ADR_NAME.match(base):
        return "ADR"
    if is_code_path(p):
        return "CODE"
    # Infrastructure-as-Code / structured config: parsed structurally but terse,
    # and it IS the deploy/run/configure signal — so it earns the OPS middle tier
    # (0.6, ADR-0022), not the prose catch-all. Matched by suffix before the prose
    # heuristics below. Checked after CODE so a `.py` etc. still wins; checked
    # before the prose tiers so a `.tf` is never demoted to the default.
    # The kernel's own declarative files are CONTEXT, checked before is_ops_path so the
    # `.yaml` ontology overlays are not demoted to the OPS tier (ADR-0024/0025).
    if base in ("ontology.toml", "ontology.yaml", "ontology.yml", "ontology.base.yaml"):
        return "CONTEXT"
    if is_ops_path(p):
        return "OPS"
    if base == "context.md":
        return "CONTEXT"
    if "reference" in base or "reference/" in p:
        return "REFERENCE"
    if base == "plan.md" or "docs/features/" in p or "specs/" in p:
        return "SPEC"
    if any(tok in base for tok in ("readme", "handoff", "notes", "scratch", "todo")):
        return "EPHEMERAL"
    return ""


def authority(sources: Iterable[str], cfg: ScoringConfig = DEFAULTS) -> float:
    """Max authority over a node's source paths. No sources / all-unmatched → default."""
    best = cfg.authority_default
    seen = False
    for src in sources:
        tier = classify_source(src, cfg)
        weight = cfg.authority_tiers.get(tier, cfg.authority_default)
        if not seen or weight > best:
            best = weight
            seen = True
    return best


# ── Axis 4 weight (shared with drift aggregation) ───────────────────────────


def edge_weight(kind: str, cfg: ScoringConfig = DEFAULTS) -> float:
    """Static f(kind). Unknown kind → mid default."""
    return cfg.edge_weights.get(kind, cfg.edge_weight_default)


# ── Axis 3: Centrality ──────────────────────────────────────────────────────


class _Edge(Protocol):
    source_id: str
    target_id: str
    kind: str


def centrality(
    node_sources: Mapping[str, Sequence[str]],
    relationships: Iterable[_Edge],
    cfg: ScoringConfig = DEFAULTS,
) -> dict[str, float]:
    """Distinct-source in-degree over centrality kinds, normalized to [0,1] by graph max.

    For each target, count the number of *distinct source documents* contributing an
    in-edge — not raw edge multiplicity. Capping any one document's contribution at 1 is
    the defense against lexicon inflation: ten concepts minted by one chatty doc count
    once; ten *different* documents are genuine centrality. Self-loops are ignored.

    `node_sources` maps entity id → its source paths. A node absent from the map (or with
    no sources) contributes nothing.
    """
    docs_by_target: dict[str, set[str]] = {}
    for rel in relationships:
        if rel.kind not in cfg.centrality_kinds:
            continue
        if rel.source_id == rel.target_id:
            continue
        srcs = node_sources.get(rel.source_id) or ()
        if not srcs:
            continue
        docs_by_target.setdefault(rel.target_id, set()).update(srcs)

    if not docs_by_target:
        return {nid: 0.0 for nid in node_sources}

    counts = {tid: len(docs) for tid, docs in docs_by_target.items()}
    peak = max(counts.values())
    if peak <= 0:
        return {nid: 0.0 for nid in node_sources}

    return {nid: counts.get(nid, 0) / peak for nid in node_sources}


# ── Axis 2 (replaced): Drift (ADR-0020) ─────────────────────────────────────


def edge_drift(lines_changed: int, referent_size: int) -> float:
    """Normalized churn to the referent: min(1, lines/size). Size 0 → 0 (nothing to drift)."""
    if referent_size <= 0 or lines_changed <= 0:
        return 0.0
    return min(1.0, lines_changed / referent_size)


def node_drift(edges: Iterable[tuple[float, float]]) -> float:
    """Edge-weighted mean of a node's claimant-side (drift, weight) pairs. No edges → 0.

    Proportional, not max: a large mostly-current doc isn't buried by one churned
    reference, while a small focused doc still collapses to "stale" because the drifted
    edge dominates its mean. (Health flagging uses a sensitive `max` instead — that lives
    in the #8 rollup, not here.)
    """
    num = 0.0
    den = 0.0
    for drift, weight in edges:
        num += weight * drift
        den += weight
    if den <= 0:
        return 0.0
    return num / den


def confidence(authority_: float, node_drift_: float) -> float:
    """authority × (1 − node_drift). Centrality is kept separate (never folded in)."""
    return authority_ * (1.0 - node_drift_)


# ── Composition (ADR-0019: at query / ranking time) ─────────────────────────


def proximity(
    candidate_id: str,
    seed_ids: Sequence[str],
    adjacency: Mapping[str, Sequence[tuple[str, str]]],
    cfg: ScoringConfig = DEFAULTS,
) -> float:
    """1 + max edge_weight to a 1-hop seed neighbour, else 1.

    A boost (≥ 1), never a gate: an unconnected but highly-similar result keeps
    proximity = 1 and survives on similarity × confidence alone. `adjacency` maps a seed
    id → its neighbours as (neighbour_id, edge_kind).
    """
    best = 0.0
    for seed in seed_ids:
        for neighbour_id, kind in adjacency.get(seed, ()):  # noqa: E741
            if neighbour_id == candidate_id:
                w = edge_weight(kind, cfg)
                if w > best:
                    best = w
    return 1.0 + best


def find_score(similarity: float, confidence_: float, proximity_: float) -> float:
    """similarity × confidence × proximity (ADR-0015 find composite)."""
    return similarity * confidence_ * proximity_


def expansion_score(
    seed_score: float,
    edge_kind: str,
    neighbor_confidence: float,
    cfg: ScoringConfig = DEFAULTS,
) -> float:
    """Relevance flowing from a seed to a 1-hop neighbor (ADR-0023, spreading activation).

    `seed_score × edge_weight(kind) × hop_decay × neighbor_confidence`. Every factor is ≤ 1,
    so an expanded candidate is always bounded below its seed's relevance — expansion augments
    retrieval, never hijacks it. No kind allowlist: `edge_weight` is the gate (imports@0.3
    self-starves; governed-by@0.95 surfaces).
    """
    return seed_score * edge_weight(edge_kind, cfg) * cfg.expansion_hop_decay * neighbor_confidence


def ranking_weight(confidence_: float, centrality_: float) -> float:
    """confidence × (1 + centrality) — summarize_scope ordering (entity_weight, ADR-0015).

    Centrality is a **boost, not a gate** (same principle as proximity): real-data ingest
    showed pure-code scopes give almost every entity centrality 0 (only `inherits` bears
    centrality among code; `realizes`/`governed-by` need the doc pass), so the original
    `confidence × centrality` collapsed nearly all code entities to a 0 tie and erased the
    confidence signal. The `1 +` keeps confidence as the ordering backbone while central
    entities still rise.
    """
    return confidence_ * (1.0 + centrality_)
