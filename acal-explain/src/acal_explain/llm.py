"""LLM abstraction for acal-explain.

Two-call strategy:
  Call 1 — structural summary: given the raw neutral dict, explain what the policy does.
  Call 2 — observations: given the structural analysis, highlight nuances, gaps, and risks.

Both calls use litellm so any configured provider works transparently.
"""
from __future__ import annotations

import json

try:
    import litellm
except ImportError:
    litellm = None  # type: ignore[assignment]

from .analyzer import AnalysisResult
from .config import Config


def _alg_short(alg: str | None) -> str:
    if not alg:
        return "unknown"
    return alg.rsplit(":", 1)[-1]


def _build_summary_prompt(doc: dict, analysis: AnalysisResult) -> str:
    policy_id = (
        analysis.policy_info.policy_id
        if analysis.policy_info
        else (analysis.bundle_policies[0].policy_id if analysis.bundle_policies else "unknown")
    )
    rule_count = analysis.rule_count
    alg = _alg_short(
        analysis.policy_info.combining_alg if analysis.policy_info
        else (analysis.bundle_policies[0].combining_alg if analysis.bundle_policies else None)
    )
    is_bundle = bool(analysis.bundle_policies)

    return f"""You are an access-control policy analyst. Explain the following ACAL policy document in plain English.

Policy ID: {policy_id}
Document type: {"Bundle of policies" if is_bundle else "Single policy"}
Number of rules: {rule_count} ({analysis.permit_count} Permit, {analysis.deny_count} Deny)
Combining algorithm: {alg}
Format: {analysis.format}

Full policy document (ACAL neutral dict, JSON):
{json.dumps(doc, indent=2)}

Write 2–4 paragraphs explaining:
- What access this policy governs (subject, resource, action if discernible)
- How the rules interact given the combining algorithm
- What happens when no rule matches (the default outcome)
- Any conditions or attributes that determine the outcome

Use plain English. Do not use JSON or technical notation unless quoting a specific identifier. Do not repeat information verbatim from the JSON."""


def _build_observations_prompt(analysis: AnalysisResult) -> str:
    lines: list[str] = []

    alg = _alg_short(
        analysis.policy_info.combining_alg if analysis.policy_info
        else (analysis.bundle_policies[0].combining_alg if analysis.bundle_policies else None)
    )
    lines.append(f"Combining algorithm: {alg}")
    lines.append(f"Default outcome (no rule matches): {analysis.default_effect or 'indeterminate'}")
    lines.append(f"Is default-deny: {analysis.is_default_deny}")

    if analysis.shadowed_rules:
        lines.append(f"Shadowed rules (can never be reached): {', '.join(analysis.shadowed_rules)}")
    else:
        lines.append("Shadowed rules: none detected")

    if analysis.obligation_gaps:
        lines.append(f"Effects with no obligation/advice: {', '.join(analysis.obligation_gaps)}")
    else:
        lines.append("Obligation/advice coverage: all effects have associated notices")

    if analysis.unresolved_attrs:
        lines.append(
            f"Unresolved attribute references (no category declared): "
            f"{', '.join(analysis.unresolved_attrs[:10])}"
            + (" …and more" if len(analysis.unresolved_attrs) > 10 else "")
        )
    else:
        lines.append("Attribute resolution: all attributes have declared categories")

    analysis_block = "\n".join(f"  {l}" for l in lines)

    return f"""You are an access-control policy analyst reviewing a policy for correctness and completeness.

Structural analysis findings:
{analysis_block}

Based on these findings, write 2–4 bullet points highlighting:
- Any completeness gaps (e.g. missing obligations for Deny outcomes, default-permit risks)
- Any shadowed or unreachable rules the policy author should review
- Any unresolved attribute references that could cause runtime evaluation errors
- Any other nuances in the combining algorithm or rule order that a reviewer should understand

Be specific: name the rule IDs or attribute names involved. If there are no concerns for a category, omit that bullet. If everything looks complete, say so briefly."""


def explain(doc: dict, analysis: AnalysisResult, cfg: Config) -> tuple[str, str]:
    """Run the two LLM calls and return (summary, observations).

    Raises:
        ImportError: if litellm is not installed
        litellm.exceptions.AuthenticationError: if the API key is missing/invalid
        litellm.exceptions.APIConnectionError: for network/endpoint errors
    """
    if litellm is None:
        raise ImportError(
            "litellm is required for LLM calls. Install it with: pip install litellm"
        )

    kwargs = cfg.llm_kwargs()

    summary_resp = litellm.completion(
        model=cfg.model,
        messages=[{"role": "user", "content": _build_summary_prompt(doc, analysis)}],
        **kwargs,
    )
    summary = summary_resp.choices[0].message.content.strip()

    obs_resp = litellm.completion(
        model=cfg.model,
        messages=[{"role": "user", "content": _build_observations_prompt(analysis)}],
        **kwargs,
    )
    observations = obs_resp.choices[0].message.content.strip()

    return summary, observations
