"""Structural analysis of a loaded ACAL neutral dict.

Produces a plain-Python AnalysisResult used as grounding context for LLM prompts.
All analysis is deterministic and requires no LLM call.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class RuleInfo:
    id: str
    effect: str
    has_target: bool
    has_condition: bool
    has_notices: bool
    combining_position: int


@dataclass
class PolicyInfo:
    policy_id: str
    combining_alg: str | None
    rules: list[RuleInfo]
    has_target: bool
    variable_count: int
    notice_count: int


@dataclass
class AnalysisResult:
    """Structured facts about a policy document, used to ground LLM prompts."""
    format: str
    policy_info: PolicyInfo | None
    bundle_policies: list[PolicyInfo]

    # Observations
    default_effect: str | None         # 'Permit', 'Deny', or None if indeterminate
    shadowed_rules: list[str]          # rule IDs that can never be reached
    unreachable_effects: list[str]     # effects that can never fire given combining alg
    obligation_gaps: list[str]         # effects that carry no obligation/advice
    unresolved_attrs: list[str]        # attribute designators without a resolvable category
    is_default_deny: bool              # True when no match → Deny
    rule_count: int
    permit_count: int
    deny_count: int


# ---------------------------------------------------------------------------
# ACAL combining algorithm semantics
# ---------------------------------------------------------------------------

_DENY_OVERRIDES = "urn:oasis:names:tc:acal:1.0:combining-algorithm:deny-overrides"
_PERMIT_OVERRIDES = "urn:oasis:names:tc:acal:1.0:combining-algorithm:permit-overrides"
_FIRST_APPLICABLE = "urn:oasis:names:tc:acal:1.0:combining-algorithm:first-applicable"
_ONLY_ONE_APPLICABLE = "urn:oasis:names:tc:acal:1.0:combining-algorithm:only-one-applicable"
_DENY_UNLESS_PERMIT = "urn:oasis:names:tc:acal:1.0:combining-algorithm:deny-unless-permit"
_PERMIT_UNLESS_DENY = "urn:oasis:names:tc:acal:1.0:combining-algorithm:permit-unless-deny"


def _default_effect(alg: str | None) -> str | None:
    """Return the default effect (when no rule matches) for a given combining algorithm."""
    if alg in (_DENY_OVERRIDES, _FIRST_APPLICABLE, _ONLY_ONE_APPLICABLE):
        return "NotApplicable"
    if alg == _DENY_UNLESS_PERMIT:
        return "Deny"
    if alg == _PERMIT_UNLESS_DENY:
        return "Permit"
    return None


def _is_default_deny(alg: str | None) -> bool:
    return alg == _DENY_UNLESS_PERMIT


def _shadowed_rules_for(rules: list[RuleInfo], alg: str | None) -> list[str]:
    """Identify rule IDs that can never be reached.

    For firstApplicable: a Permit rule after an unconditional Permit (no target,
    no condition) can never fire. Same logic for Deny.
    For denyOverrides/permitOverrides: rules after an unconditional rule of the
    dominant effect can never change the outcome.
    """
    shadowed: list[str] = []
    if alg not in (_FIRST_APPLICABLE, _DENY_OVERRIDES, _PERMIT_OVERRIDES):
        return shadowed

    dominant = "Deny" if alg == _DENY_OVERRIDES else "Permit"

    for i, rule in enumerate(rules):
        if i == 0:
            continue
        prev = rules[i - 1]
        if (
            alg == _FIRST_APPLICABLE
            and not prev.has_target
            and not prev.has_condition
        ):
            shadowed.append(rule.id)
        elif (
            alg in (_DENY_OVERRIDES, _PERMIT_OVERRIDES)
            and prev.effect == dominant
            and not prev.has_target
            and not prev.has_condition
        ):
            shadowed.append(rule.id)
    return shadowed


# ---------------------------------------------------------------------------
# Navigation helpers
# ---------------------------------------------------------------------------

def _rules_from(policy: dict) -> list[RuleInfo]:
    rules: list[RuleInfo] = []
    for i, entry in enumerate(policy.get("CombinerInput", [])):
        rule = entry.get("Rule")
        if not rule:
            continue
        notices = rule.get("NoticeExpression", [])
        rules.append(RuleInfo(
            id=rule.get("Id", f"<rule-{i}>"),
            effect=rule.get("Effect", "Unknown"),
            has_target="Target" in rule,
            has_condition="Condition" in rule,
            has_notices=bool(notices),
            combining_position=i,
        ))
    return rules


def _policy_info(policy: dict) -> PolicyInfo:
    alg = policy.get("CombiningAlgId")
    rules = _rules_from(policy)
    notices = policy.get("NoticeExpression", [])
    variables = policy.get("VariableDefinition", []) + policy.get("SharedVariableDefinition", [])
    return PolicyInfo(
        policy_id=policy.get("PolicyId", "<unknown>"),
        combining_alg=alg,
        rules=rules,
        has_target="Target" in policy,
        variable_count=len(variables),
        notice_count=len(notices),
    )


def _collect_unresolved_attrs(doc: dict) -> list[str]:
    """Walk the neutral dict and find AttributeDesignators with no Category."""
    unresolved: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if "AttributeDesignator" in node:
                desig = node["AttributeDesignator"]
                if not desig.get("Category"):
                    unresolved.append(desig.get("AttributeId", "<unknown>"))
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(doc)
    return unresolved


def _obligation_gaps(policy: PolicyInfo) -> list[str]:
    """Return effects that have rules but no policy-level obligation/advice."""
    effects_with_rules = {r.effect for r in policy.rules}
    if policy.notice_count > 0:
        return []  # policy-level notices present; gap detection not applicable
    gaps = []
    for effect in ("Permit", "Deny"):
        if effect in effects_with_rules:
            rule_level_notices = any(r.has_notices and r.effect == effect for r in policy.rules)
            if not rule_level_notices:
                gaps.append(effect)
    return gaps


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def analyze(doc: dict, fmt: str) -> AnalysisResult:
    """Analyze a loaded ACAL neutral dict and return structured observations."""
    top_policy: PolicyInfo | None = None
    bundle_policies: list[PolicyInfo] = []

    if "Policy" in doc:
        top_policy = _policy_info(doc["Policy"])
    elif "Bundle" in doc:
        for entry in doc["Bundle"].get("Policy", []):
            bundle_policies.append(_policy_info(entry))

    primary = top_policy or (bundle_policies[0] if bundle_policies else None)

    default_eff = _default_effect(primary.combining_alg) if primary else None
    is_dd = _is_default_deny(primary.combining_alg) if primary else False

    all_rules = primary.rules if primary else []
    shadowed = _shadowed_rules_for(all_rules, primary.combining_alg if primary else None)
    ob_gaps = _obligation_gaps(primary) if primary else []
    unresolved = _collect_unresolved_attrs(doc)

    permit_count = sum(1 for r in all_rules if r.effect == "Permit")
    deny_count = sum(1 for r in all_rules if r.effect == "Deny")

    return AnalysisResult(
        format=fmt,
        policy_info=top_policy,
        bundle_policies=bundle_policies,
        default_effect=default_eff,
        shadowed_rules=shadowed,
        unreachable_effects=[],
        obligation_gaps=ob_gaps,
        unresolved_attrs=list(dict.fromkeys(unresolved)),
        is_default_deny=is_dd,
        rule_count=len(all_rules),
        permit_count=permit_count,
        deny_count=deny_count,
    )
