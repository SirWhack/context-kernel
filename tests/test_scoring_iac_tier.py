"""Tests for Infrastructure-as-Code authority classification (Fix C).

``.tf``/``.hcl``/``.bicep``/``.tf.json``/``.tfvars`` sources are parsed
structurally but carry terse, boilerplate descriptions. They ARE the
deploy/run/configure signal, so they reuse the existing OPS tier (0.6, ADR-0022)
rather than falling through to the prose catch-all (0.30). This keeps infra/deploy
queries from being unduly demoted by find_score's confidence factor.
"""

from __future__ import annotations

from context_kernel.scoring import (
    AUTHORITY_TIERS,
    DEFAULTS,
    IAC_EXT,
    ScoringConfig,
    authority,
    classify_source,
)


def test_terraform_classifies_as_ops():
    assert classify_source("infra/main.tf") == "OPS"


def test_all_iac_exts_classify_as_ops():
    for ext in IAC_EXT:
        assert classify_source(f"infra/file{ext}") == "OPS", ext


def test_tf_json_is_ops_not_prose():
    # `.tf.json` must hit OPS, not fall through to the prose catch-all.
    assert classify_source("infra/main.tf.json") == "OPS"


def test_tfvars_is_ops():
    assert classify_source("infra/prod.tfvars") == "OPS"


def test_iac_authority_value():
    assert authority(["infra/main.tf"]) == AUTHORITY_TIERS["OPS"]
    assert AUTHORITY_TIERS["OPS"] == 0.6


def test_iac_tier_sits_between_code_and_prose():
    code = authority(["app/handler.py"])
    iac = authority(["infra/main.tf"])
    prose = authority(["random_doc.txt"])  # unmatched prose -> AUTHORITY_DEFAULT
    assert code > iac > prose
    assert code == AUTHORITY_TIERS["CODE"]
    assert prose == DEFAULTS.authority_default


def test_code_extension_still_wins_over_iac():
    # A genuine code file is unaffected by the IaC branch.
    assert classify_source("app/handler.py") == "CODE"
    assert classify_source("app/handler.ts") == "CODE"


def test_iac_tier_is_tunable_via_config():
    # The OPS tier value is overridable through the existing authority_tiers knob,
    # so the IaC mapping is tunable/reversible without code changes.
    cfg = ScoringConfig.resolve(section={"authority_tiers": {"ops": 0.45}})
    assert authority(["infra/main.tf"], cfg) == 0.45
    # Default (no override) is unchanged.
    assert authority(["infra/main.tf"]) == 0.6
