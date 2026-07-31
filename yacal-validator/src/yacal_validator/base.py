from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Severity(str, Enum):
    ERROR = "error"
    WARNING = "warning"


@dataclass
class ValidationIssue:
    severity: Severity
    message: str
    path: str | None = None
    rule_id: str | None = None
    hint: str | None = None
    spec_ref: str | None = None


@dataclass
class ValidationResult:
    format: str  # "yacal"
    profiles: list[str] = field(default_factory=list)
    # Unadopted schema proposals applied for this run. Non-empty means the document was
    # checked against something the published schemas do not say, so the result is not a
    # conformance result and every reporter must say which proposals were in play.
    proposals: list[str] = field(default_factory=list)
    valid: bool = True
    issues: list[ValidationIssue] = field(default_factory=list)
    constraints_total: int = 0
    constraints_evaluated: int = 0
    constraints_skipped: int = 0

    def add_issue(self, issue: ValidationIssue) -> None:
        self.issues.append(issue)
        if issue.severity == Severity.ERROR:
            self.valid = False

    @property
    def error_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == Severity.ERROR)

    @property
    def warning_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == Severity.WARNING)

    @property
    def constraints_ran(self) -> bool:
        return self.constraints_total > 0

    @property
    def incomplete(self) -> bool:
        """True when constraints_skipped > 0 — validation could not fully evaluate all rules."""
        return self.constraints_skipped > 0
