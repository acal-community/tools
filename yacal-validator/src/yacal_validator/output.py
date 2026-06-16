"""Human-readable and JSON output formatters."""
from __future__ import annotations

import json
import sys
from typing import TextIO

from .base import Severity, ValidationResult


def human(result: ValidationResult, filename: str, file: TextIO = sys.stdout) -> None:
    label = "YACAL v1.0 (YAML)"
    if result.profiles:
        label += f" + {', '.join(p.upper() for p in result.profiles)} Profile"

    if result.valid and not result.issues:
        print(f"PASS  {label} — {filename}", file=file)
        _print_constraint_summary(result, file)
        return

    if result.valid:
        wc = result.warning_count
        print(
            f"PASS  {label} — {filename}  "
            f"({wc} advisory warning{'s' if wc != 1 else ''})",
            file=file,
        )
    else:
        ec = result.error_count
        wc = result.warning_count
        parts = [f"{ec} error{'s' if ec != 1 else ''}"]
        if wc:
            parts.append(f"{wc} warning{'s' if wc != 1 else ''}")
        print(f"FAIL  {label} — {filename}  ({', '.join(parts)})", file=file)

    _print_constraint_summary(result, file)
    print(file=file)

    for i, issue in enumerate(result.issues, 1):
        tag = "ERR" if issue.severity == Severity.ERROR else "WRN"
        print(f"  [{tag} {i:02d}]  {issue.message}", file=file)
        if issue.path:
            print(f"           Location : {issue.path}", file=file)
        if issue.spec_ref:
            print(f"           Spec     : {issue.spec_ref}", file=file)
        if issue.hint:
            print(f"           Fix      : {issue.hint}", file=file)
        if issue.rule_id:
            print(f"           Rule     : {issue.rule_id}", file=file)
        print(file=file)


def _print_constraint_summary(result: ValidationResult, file: TextIO) -> None:
    if not result.constraints_ran:
        return
    n = result.constraints_evaluated
    t = result.constraints_total
    s = result.constraints_skipped
    line = f"        Constraints: {n}/{t} evaluated"
    if s:
        line += (
            f"  ·  {s} skipped"
            f" (cross-document reference lookup — not supported in single-file mode)"
        )
    print(line, file=file)


def as_json(result: ValidationResult, filename: str, file: TextIO = sys.stdout) -> None:
    data = {
        "file": filename,
        "format": result.format,
        "profiles": result.profiles,
        "valid": result.valid,
        "error_count": result.error_count,
        "warning_count": result.warning_count,
        "constraints": {
            "total": result.constraints_total,
            "evaluated": result.constraints_evaluated,
            "skipped": result.constraints_skipped,
        },
        "issues": [
            {
                "severity": issue.severity.value,
                "message": issue.message,
                **({} if issue.path is None else {"path": issue.path}),
                **({} if issue.rule_id is None else {"rule_id": issue.rule_id}),
                **({} if issue.hint is None else {"hint": issue.hint}),
                **({} if issue.spec_ref is None else {"spec_ref": issue.spec_ref}),
            }
            for issue in result.issues
        ],
    }
    print(json.dumps(data, indent=2), file=file)
