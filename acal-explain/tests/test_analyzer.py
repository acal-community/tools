"""Tests for the structural policy analyzer — no LLM calls required."""
import json
from pathlib import Path

import pytest

from acal_explain.analyzer import analyze, _default_effect, _is_default_deny

# Reuse acal-core fixtures
_CORE_FIXTURES = Path(__file__).parent.parent.parent / "acal-core" / "tests" / "fixtures"

_SIMPLE_PERMIT_YACAL = _CORE_FIXTURES / "ex01-simple-permit.yaml"
_CONDITION_YACAL = _CORE_FIXTURES / "ex02-condition.yaml"


def _load(path):
    from acal_core.readers import load, detect_format
    fmt = detect_format(str(path))
    return load(str(path), fmt), fmt


# ---------------------------------------------------------------------------
# Default-effect helpers
# ---------------------------------------------------------------------------

def test_default_effect_deny_overrides():
    alg = "urn:oasis:names:tc:acal:1.0:combining-algorithm:deny-overrides"
    assert _default_effect(alg) == "NotApplicable"


def test_default_effect_deny_unless_permit():
    alg = "urn:oasis:names:tc:acal:1.0:combining-algorithm:deny-unless-permit"
    assert _default_effect(alg) == "Deny"


def test_default_effect_permit_unless_deny():
    alg = "urn:oasis:names:tc:acal:1.0:combining-algorithm:permit-unless-deny"
    assert _default_effect(alg) == "Permit"


def test_is_default_deny_true():
    alg = "urn:oasis:names:tc:acal:1.0:combining-algorithm:deny-unless-permit"
    assert _is_default_deny(alg) is True


def test_is_default_deny_false():
    alg = "urn:oasis:names:tc:acal:1.0:combining-algorithm:deny-overrides"
    assert _is_default_deny(alg) is False


# ---------------------------------------------------------------------------
# analyze() — simple permit fixture
# ---------------------------------------------------------------------------

def test_analyze_simple_permit_has_policy_info():
    doc, fmt = _load(_SIMPLE_PERMIT_YACAL)
    result = analyze(doc, fmt)
    assert result.policy_info is not None
    assert result.policy_info.policy_id != ""


def test_analyze_simple_permit_rule_count():
    doc, fmt = _load(_SIMPLE_PERMIT_YACAL)
    result = analyze(doc, fmt)
    assert result.rule_count >= 1


def test_analyze_simple_permit_permit_count():
    doc, fmt = _load(_SIMPLE_PERMIT_YACAL)
    result = analyze(doc, fmt)
    assert result.permit_count >= 1


def test_analyze_no_shadowed_rules_single_rule():
    doc, fmt = _load(_SIMPLE_PERMIT_YACAL)
    result = analyze(doc, fmt)
    assert result.shadowed_rules == []


def test_analyze_format_propagated():
    doc, fmt = _load(_SIMPLE_PERMIT_YACAL)
    result = analyze(doc, fmt)
    assert result.format == fmt


# ---------------------------------------------------------------------------
# analyze() — inline dict (no file needed)
# ---------------------------------------------------------------------------

_DENY_UNLESS_PERMIT_ALG = "urn:oasis:names:tc:acal:1.0:combining-algorithm:deny-unless-permit"
_DENY_OVERRIDES_ALG = "urn:oasis:names:tc:acal:1.0:combining-algorithm:deny-overrides"
_FIRST_APPLICABLE_ALG = "urn:oasis:names:tc:acal:1.0:combining-algorithm:first-applicable"


def _make_policy(alg, rules):
    return {
        "Policy": {
            "PolicyId": "test.policy",
            "CombiningAlgId": alg,
            "CombinerInput": [
                {"Rule": {"Id": r["id"], "Effect": r["effect"], **r.get("extra", {})}}
                for r in rules
            ],
        }
    }


def test_default_deny_detected():
    doc = _make_policy(_DENY_UNLESS_PERMIT_ALG, [{"id": "r1", "effect": "Permit"}])
    result = analyze(doc, "yacal")
    assert result.is_default_deny is True
    assert result.default_effect == "Deny"


def test_not_default_deny_for_deny_overrides():
    doc = _make_policy(_DENY_OVERRIDES_ALG, [{"id": "r1", "effect": "Permit"}])
    result = analyze(doc, "yacal")
    assert result.is_default_deny is False


def test_shadowed_rule_detected_first_applicable():
    doc = _make_policy(
        _FIRST_APPLICABLE_ALG,
        [
            {"id": "r1", "effect": "Permit"},    # no target, no condition — catches everything
            {"id": "r2", "effect": "Deny"},      # shadowed
        ],
    )
    result = analyze(doc, "yacal")
    assert "r2" in result.shadowed_rules


def test_no_shadow_when_first_rule_has_condition():
    doc = _make_policy(
        _FIRST_APPLICABLE_ALG,
        [
            {"id": "r1", "effect": "Permit", "extra": {"Condition": {"Apply": {}}}},
            {"id": "r2", "effect": "Deny"},
        ],
    )
    result = analyze(doc, "yacal")
    assert result.shadowed_rules == []


def test_obligation_gap_no_permit_notice():
    doc = _make_policy(_DENY_OVERRIDES_ALG, [{"id": "r1", "effect": "Permit"}])
    result = analyze(doc, "yacal")
    assert "Permit" in result.obligation_gaps


def test_no_obligation_gap_when_rule_has_notice():
    doc = {
        "Policy": {
            "PolicyId": "test.policy",
            "CombiningAlgId": _DENY_OVERRIDES_ALG,
            "CombinerInput": [
                {
                    "Rule": {
                        "Id": "r1",
                        "Effect": "Permit",
                        "NoticeExpression": [{"Id": "urn:example:log", "IsObligation": True, "AppliesTo": "Permit"}],
                    }
                }
            ],
        }
    }
    result = analyze(doc, "yacal")
    assert "Permit" not in result.obligation_gaps


def test_unresolved_attr_collected():
    doc = {
        "Policy": {
            "PolicyId": "test.policy",
            "CombiningAlgId": _DENY_OVERRIDES_ALG,
            "CombinerInput": [
                {
                    "Rule": {
                        "Id": "r1",
                        "Effect": "Permit",
                        "Condition": {
                            "Apply": {
                                "FunctionId": "urn:fn:string-equal",
                                "Argument": [
                                    {"AttributeDesignator": {"AttributeId": "some.attr"}},
                                    {"Value": "x"},
                                ],
                            }
                        },
                    }
                }
            ],
        }
    }
    result = analyze(doc, "yacal")
    assert "some.attr" in result.unresolved_attrs


def test_no_unresolved_attr_when_category_present():
    doc = {
        "Policy": {
            "PolicyId": "test.policy",
            "CombiningAlgId": _DENY_OVERRIDES_ALG,
            "CombinerInput": [
                {
                    "Rule": {
                        "Id": "r1",
                        "Effect": "Permit",
                        "Condition": {
                            "Apply": {
                                "FunctionId": "urn:fn:string-equal",
                                "Argument": [
                                    {
                                        "AttributeDesignator": {
                                            "AttributeId": "some.attr",
                                            "Category": "urn:oasis:names:tc:acal:1.0:subject-category:access-subject",
                                        }
                                    },
                                    {"Value": "x"},
                                ],
                            }
                        },
                    }
                }
            ],
        }
    }
    result = analyze(doc, "yacal")
    assert result.unresolved_attrs == []


# ---------------------------------------------------------------------------
# Bundle document
# ---------------------------------------------------------------------------

def test_analyze_bundle():
    doc = {
        "Bundle": {
            "Policy": [
                {
                    "PolicyId": "test.bundle.child",
                    "CombiningAlgId": _DENY_OVERRIDES_ALG,
                    "CombinerInput": [{"Rule": {"Id": "r1", "Effect": "Permit"}}],
                }
            ]
        }
    }
    result = analyze(doc, "jacal")
    assert result.policy_info is None
    assert len(result.bundle_policies) == 1
    assert result.bundle_policies[0].policy_id == "test.bundle.child"
