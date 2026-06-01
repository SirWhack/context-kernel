"""Tests for context_kernel.scoring — pure confidence/relevance/drift formulas (Slice 2)."""

from collections import namedtuple

import pytest

from context_kernel import scoring
from context_kernel.scoring import ScoringConfig

Rel = namedtuple("Rel", "source_id target_id kind")


# ── Authority (Axis 1) ──────────────────────────────────────────────────────


class TestClassifySource:
    @pytest.mark.parametrize("path,tier", [
        ("THEORY.md", "THEORY"),
        ("ARCHITECTURE.md", "ARCHITECTURE"),
        ("docs/adr/0015-entity-confidence-scoring.md", "ADR"),
        ("context_kernel/scoring.py", "CODE"),
        ("src/bot/agent.ts", "CODE"),
        ("widget.tsx", "CODE"),
        ("frontend/Button.jsx", "CODE"),
        ("frontend/server.mjs", "CODE"),
        ("frontend/worker.cjs", "CODE"),
        ("crates/kernel/src/lib.rs", "CODE"),
        ("schema/api.graphql", "CODE"),
        ("schema/api.gql", "CODE"),
        ("web/index.html", "CODE"),
        (".github/workflows/deploy.yml", "OPS"),
        ("CONTEXT.md", "CONTEXT"),
        ("ontology.toml", "CONTEXT"),
        ("DESIGN-REFERENCE.md", "REFERENCE"),
        ("PLAN.md", "SPEC"),
        ("docs/features/FEAT01.md", "SPEC"),
        ("HANDOFF.md", "EPHEMERAL"),
        ("README.md", "EPHEMERAL"),
        ("docs/notes/scratch.md", "EPHEMERAL"),
        ("some/random/prose.md", ""),
    ])
    def test_classification(self, path, tier):
        assert scoring.classify_source(path) == tier

    def test_case_insensitive(self):
        assert scoring.classify_source("theory.md") == "THEORY"


class TestAuthority:
    def test_max_over_sources(self):
        # a node merged from code + ADR takes the higher tier
        assert scoring.authority(("context_kernel/x.py", "docs/adr/0001-x.md")) == 0.9

    def test_empty_sources_is_default(self):
        assert scoring.authority(()) == scoring.AUTHORITY_DEFAULT == 0.3

    def test_unmatched_prose_is_default_not_zero(self):
        assert scoring.authority(("random/prose.md",)) == 0.3

    def test_theory_tops_out(self):
        assert scoring.authority(("THEORY.md",)) == 1.0

    def test_ephemeral_floor(self):
        assert scoring.authority(("HANDOFF.md",)) == 0.2


# ── Repo-local role assignment (ADR-0022) ───────────────────────────────────


class TestRepoRoles:
    """Per-repo glob→role declarations override the built-in filename heuristics.

    The assignment is local (what is this file in THIS repo); the tier it names is
    valued globally (one ruler across a shared portfolio graph).
    """

    def _cfg(self, roles):
        return ScoringConfig.resolve({"roles": roles})

    def test_role_overrides_heuristic(self):
        # README defaults to EPHEMERAL (0.2); declaring it OVERVIEW lifts it to the trunk.
        cfg = self._cfg({"README.md": "OVERVIEW"})
        assert scoring.classify_source("README.md") == "EPHEMERAL"          # heuristic
        assert scoring.classify_source("README.md", cfg) == "OVERVIEW"      # declared
        assert scoring.authority(("README.md",), cfg) == 0.85

    def test_most_specific_glob_wins(self):
        # a catch-all *.md and a literal README.md both match; the literal is more specific
        cfg = self._cfg({"*.md": "EPHEMERAL", "README.md": "OVERVIEW"})
        assert scoring.classify_source("README.md", cfg) == "OVERVIEW"
        assert scoring.classify_source("CHANGELOG.md", cfg) == "EPHEMERAL"

    def test_path_glob_matches_nested_doc(self):
        cfg = self._cfg({"backend/README.md": "REFERENCE"})
        assert scoring.classify_source("backend/README.md", cfg) == "REFERENCE"
        # the bare top-level README is unaffected → falls back to the heuristic
        assert scoring.classify_source("README.md", cfg) == "EPHEMERAL"

    def test_unmatched_path_falls_back_to_heuristic(self):
        cfg = self._cfg({"deployment.md": "OPS"})
        assert scoring.classify_source("deployment.md", cfg) == "OPS"
        assert scoring.classify_source("THEORY.md", cfg) == "THEORY"        # heuristic intact

    def test_code_unaffected_by_md_role(self):
        # a *.md role must never reclassify code — code matches by extension, not the glob
        cfg = self._cfg({"*.md": "OVERVIEW"})
        assert scoring.classify_source("backend/app/crud.py", cfg) == "CODE"

    def test_role_to_unknown_tier_is_loud(self):
        with pytest.raises(ValueError, match="unknown tier"):
            ScoringConfig.resolve({"roles": {"README.md": "TRUNK"}})

    def test_role_to_config_defined_tier(self):
        # a role may name a tier the repo defines itself under authority_tiers
        cfg = ScoringConfig.resolve(
            {"authority_tiers": {"RUNBOOK": 0.55}, "roles": {"ops/*.md": "RUNBOOK"}}
        )
        assert scoring.classify_source("ops/deploy.md", cfg) == "RUNBOOK"
        assert scoring.authority(("ops/deploy.md",), cfg) == 0.55

    def test_no_roles_is_pure_heuristic(self):
        assert dict(ScoringConfig.resolve().roles) == {}
        assert scoring.classify_source("README.md", ScoringConfig.resolve()) == "EPHEMERAL"


# ── Edge weight (Axis 4, shared with drift) ─────────────────────────────────


class TestEdgeWeight:
    @pytest.mark.parametrize("kind,weight", [
        ("governed-by", 0.95),
        ("realizes", 0.9),
        ("implements", 0.9),
        ("inherits", 0.9),
        ("implemented-by", 0.9),
        ("supersedes", 0.85),
        ("addresses", 0.7),
        ("motivates", 0.5),
        ("imports", 0.3),
    ])
    def test_known_kinds(self, kind, weight):
        assert scoring.edge_weight(kind) == weight

    def test_unknown_kind_is_mid(self):
        assert scoring.edge_weight("frobnicates") == 0.5


# ── Centrality (Axis 3) ─────────────────────────────────────────────────────


class TestCentrality:
    def test_distinct_source_indegree_normalized(self):
        # T gets in-edges from two distinct documents → peak; U from one → half
        node_sources = {
            "T": ("t.py",), "U": ("u.py",),
            "a": ("docA.md",), "b": ("docB.md",), "c": ("docC.md",),
        }
        rels = [
            Rel("a", "T", "realizes"),
            Rel("b", "T", "realizes"),
            Rel("c", "U", "realizes"),
        ]
        cen = scoring.centrality(node_sources, rels)
        assert cen["T"] == 1.0
        assert cen["U"] == 0.5
        assert cen["a"] == 0.0

    def test_lexicon_inflation_capped_at_one_document(self):
        # one chatty doc mints three distinct concepts all → T; a second doc → U once.
        # T's in-degree must NOT beat U just by repetition within a single document.
        node_sources = {
            "T": ("t.py",), "U": ("u.py",),
            "c1": ("chatty.md",), "c2": ("chatty.md",), "c3": ("chatty.md",),
            "d1": ("other.md",),
        }
        rels = [
            Rel("c1", "T", "realizes"),
            Rel("c2", "T", "realizes"),
            Rel("c3", "T", "realizes"),
            Rel("d1", "U", "realizes"),
        ]
        cen = scoring.centrality(node_sources, rels)
        # both reached by exactly one distinct document → tie at the top
        assert cen["T"] == cen["U"] == 1.0

    def test_only_centrality_kinds_count(self):
        node_sources = {"T": ("t.py",), "a": ("a.md",), "b": ("b.md",)}
        rels = [Rel("a", "T", "imports"), Rel("b", "T", "motivates")]
        cen = scoring.centrality(node_sources, rels)
        assert cen["T"] == 0.0

    def test_self_loop_ignored(self):
        node_sources = {"T": ("t.py",)}
        rels = [Rel("T", "T", "realizes")]
        assert scoring.centrality(node_sources, rels)["T"] == 0.0

    def test_no_edges_all_zero(self):
        node_sources = {"a": ("a.md",), "b": ("b.md",)}
        assert scoring.centrality(node_sources, []) == {"a": 0.0, "b": 0.0}

    def test_sourceless_source_node_contributes_nothing(self):
        node_sources = {"T": ("t.py",), "ghost": ()}
        rels = [Rel("ghost", "T", "realizes")]
        assert scoring.centrality(node_sources, rels)["T"] == 0.0


# ── Drift (ADR-0020) ────────────────────────────────────────────────────────


class TestEdgeDrift:
    def test_size_relative(self):
        assert scoring.edge_drift(200, 400) == 0.5

    def test_rewrite_saturates_at_one(self):
        assert scoring.edge_drift(500, 400) == 1.0

    def test_zero_size_is_zero(self):
        assert scoring.edge_drift(100, 0) == 0.0

    def test_zero_change_is_zero(self):
        assert scoring.edge_drift(0, 400) == 0.0


class TestNodeDrift:
    def test_edge_weighted_mean(self):
        # heavily-weighted current edge dominates a light stale one
        assert scoring.node_drift([(0.0, 0.9), (1.0, 0.3)]) == pytest.approx(0.3 / 1.2)

    def test_no_edges_is_zero(self):
        assert scoring.node_drift([]) == 0.0

    def test_zero_weight_is_zero(self):
        assert scoring.node_drift([(1.0, 0.0)]) == 0.0

    def test_small_focused_doc_collapses(self):
        # a single drifted edge → node fully stale
        assert scoring.node_drift([(1.0, 0.9)]) == 1.0


class TestConfidence:
    def test_formula(self):
        assert scoring.confidence(0.9, 0.0) == 0.9
        assert scoring.confidence(0.9, 1.0) == pytest.approx(0.0)
        assert scoring.confidence(0.8, 0.5) == pytest.approx(0.4)

    def test_handoff_class_near_zero(self):
        # low authority × high drift = near-zero confidence (the HANDOFF lesson)
        assert scoring.confidence(0.2, 0.9) == pytest.approx(0.02)


# ── Composition (query / ranking time) ──────────────────────────────────────


class TestProximity:
    def test_boost_from_seed_neighbour(self):
        adj = {"s1": [("c", "realizes")]}
        assert scoring.proximity("c", ["s1"], adj) == pytest.approx(1.9)

    def test_max_over_multiple_seeds(self):
        adj = {"s1": [("c", "motivates")], "s2": [("c", "governed-by")]}
        assert scoring.proximity("c", ["s1", "s2"], adj) == pytest.approx(1.95)

    def test_unconnected_is_one_not_zero(self):
        # boost-not-gate: an unconnected candidate keeps proximity 1, never zeroed
        assert scoring.proximity("c", ["s1"], {"s1": [("other", "realizes")]}) == 1.0

    def test_no_seeds_is_one(self):
        assert scoring.proximity("c", [], {}) == 1.0


class TestFindScore:
    def test_multiplicative(self):
        assert scoring.find_score(0.8, 0.5, 1.5) == pytest.approx(0.6)

    def test_unconnected_survives_on_similarity_confidence(self):
        # proximity 1 (unconnected) does not zero a strong hit
        assert scoring.find_score(0.9, 0.85, 1.0) == pytest.approx(0.765)


class TestRankingWeight:
    def test_centrality_boosts_confidence(self):
        assert scoring.ranking_weight(0.8, 0.5) == pytest.approx(1.2)

    def test_zero_centrality_does_not_zero_confidence(self):
        # boost-not-gate: a peripheral entity still orders by its confidence
        assert scoring.ranking_weight(0.8, 0.0) == pytest.approx(0.8)
        assert scoring.ranking_weight(0.85, 0.0) > scoring.ranking_weight(0.3, 0.0)


# ── Knob resolution (default → config → env) ────────────────────────────────


class TestScoringConfigResolve:
    def test_defaults(self):
        cfg = ScoringConfig.resolve()
        assert cfg.authority_default == 0.3
        assert cfg.edge_weights["realizes"] == 0.9
        assert cfg.centrality_in_find is False
        # global role vocabulary (ADR-0022): OVERVIEW capped at code, OPS mid
        assert cfg.authority_tiers["OVERVIEW"] == 0.85
        assert cfg.authority_tiers["OPS"] == 0.6
        assert dict(cfg.roles) == {}

    def test_roles_loaded_and_uppercased(self):
        cfg = ScoringConfig.resolve({"roles": {"README.md": "overview", "docs/*.md": "Reference"}})
        assert cfg.roles == {"readme.md": "OVERVIEW", "docs/*.md": "REFERENCE"}

    def test_config_overrides_default(self):
        cfg = ScoringConfig.resolve(
            {"authority_default": 0.5, "edge_weights": {"realizes": 0.7}},
            {},
        )
        assert cfg.authority_default == 0.5
        assert cfg.edge_weights["realizes"] == 0.7
        assert scoring.authority(("x/prose.md",), cfg) == 0.5
        assert scoring.edge_weight("realizes", cfg) == 0.7

    def test_env_overrides_config(self):
        cfg = ScoringConfig.resolve(
            {"authority_default": 0.5},
            {"CK_SCORING_AUTHORITY_DEFAULT": "0.7"},
        )
        assert cfg.authority_default == 0.7

    def test_env_overrides_authority_tier(self):
        cfg = ScoringConfig.resolve({}, {"CK_SCORING_AUTHORITY_THEORY": "0.42"})
        assert cfg.authority_tiers["THEORY"] == 0.42
        assert scoring.authority(("THEORY.md",), cfg) == 0.42

    def test_env_overrides_edge_weight(self):
        cfg = ScoringConfig.resolve({}, {"CK_SCORING_EDGE_WEIGHT_REALIZES": "0.99"})
        assert scoring.edge_weight("realizes", cfg) == 0.99

    def test_env_centrality_in_find_bool(self):
        cfg = ScoringConfig.resolve({}, {"CK_SCORING_CENTRALITY_IN_FIND": "1"})
        assert cfg.centrality_in_find is True

    def test_env_hops(self):
        cfg = ScoringConfig.resolve({}, {"CK_SCORING_PROXIMITY_HOPS": "2", "CK_SCORING_DRIFT_HOPS": "3"})
        assert cfg.proximity_hops == 2
        assert cfg.drift_hops == 3

    def test_unrelated_env_ignored(self):
        cfg = ScoringConfig.resolve({}, {"PATH": "/usr/bin", "CK_OTHER": "x"})
        assert cfg.authority_default == 0.3
