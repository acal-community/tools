"""Format the explanation output in the requested format."""
from __future__ import annotations

import json
import sys
from typing import IO

from .analyzer import AnalysisResult


def render(
    summary: str,
    observations: str,
    analysis: AnalysisResult,
    fmt: str,
    stream: IO[str] = sys.stdout,
) -> None:
    if fmt == "json":
        _render_json(summary, observations, analysis, stream)
    elif fmt == "markdown":
        _render_markdown(summary, observations, analysis, stream)
    else:
        _render_text(summary, observations, stream)


def _render_text(summary: str, observations: str, stream: IO[str]) -> None:
    stream.write(summary)
    stream.write("\n\n")
    stream.write(observations)
    stream.write("\n")


def _render_markdown(summary: str, observations: str, analysis: AnalysisResult, stream: IO[str]) -> None:
    policy_id = (
        analysis.policy_info.policy_id
        if analysis.policy_info
        else (analysis.bundle_policies[0].policy_id if analysis.bundle_policies else "unknown")
    )
    stream.write(f"# Policy Explanation: `{policy_id}`\n\n")
    stream.write("## Summary\n\n")
    stream.write(summary)
    stream.write("\n\n")
    stream.write("## Observations\n\n")
    stream.write(observations)
    stream.write("\n")


def _render_json(summary: str, observations: str, analysis: AnalysisResult, stream: IO[str]) -> None:
    policy_id = (
        analysis.policy_info.policy_id
        if analysis.policy_info
        else (analysis.bundle_policies[0].policy_id if analysis.bundle_policies else "unknown")
    )
    out = {
        "policy_id": policy_id,
        "format": analysis.format,
        "rule_count": analysis.rule_count,
        "permit_count": analysis.permit_count,
        "deny_count": analysis.deny_count,
        "is_default_deny": analysis.is_default_deny,
        "default_effect": analysis.default_effect,
        "shadowed_rules": analysis.shadowed_rules,
        "obligation_gaps": analysis.obligation_gaps,
        "unresolved_attrs": analysis.unresolved_attrs,
        "summary": summary,
        "observations": observations,
    }
    json.dump(out, stream, indent=2)
    stream.write("\n")
