"""Unit-level tests for jacal-validator core logic.

Tests cover:
  - JSON conformance linting (comments, trailing commas, duplicate keys)
  - Profile detection from raw JSON content
  - The 3-way exit code (0/1/2) contract
  - Constraint evaluator path functions
  - Schema registry composition
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from jacal_validator.base import Severity, ValidationIssue, ValidationResult
from jacal_validator.constraints import eval_path
from jacal_validator.schemas import SCHEMA_FILES
from jacal_validator.validator import (
    _lint_json_features,
    _load_json_strict,
    detect_profiles,
    validate,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "valid"


# ---------------------------------------------------------------------------
# JSON conformance linting
# ---------------------------------------------------------------------------

class TestLintJsonFeatures:
    def _lint(self, text: str) -> list[str]:
        return [i.rule_id for i in _lint_json_features(text)]

    def test_clean_json_no_issues(self) -> None:
        assert self._lint('{"Policy": {"PolicyId": "x"}}') == []

    def test_detects_line_comment(self) -> None:
        assert "json:comment" in self._lint('// comment\n{"Policy": {}}')

    def test_detects_block_comment(self) -> None:
        assert "json:comment" in self._lint('/* block */{"Policy": {}}')

    def test_detects_trailing_comma_in_object(self) -> None:
        assert "json:trailing-comma" in self._lint('{"a": 1,}')

    def test_detects_trailing_comma_in_array(self) -> None:
        assert "json:trailing-comma" in self._lint('{"a": [1, 2,]}')

    def test_detects_duplicate_key(self) -> None:
        assert "json:duplicate-key" in self._lint('{"a": 1, "a": 2}')

    def test_multiple_issues_all_reported(self) -> None:
        # Comment and trailing comma are both detected via regex (independent of parse).
        ids = self._lint('// comment\n{"a": [1,]}')
        assert "json:comment" in ids
        assert "json:trailing-comma" in ids

        # Duplicate key detection requires valid JSON (json.loads must succeed).
        # Trailing comma makes JSON unparseable, so duplicate keys can only be
        # detected in the absence of other syntax errors.
        ids_dup = self._lint('{"a": 1, "a": 2}')
        assert "json:duplicate-key" in ids_dup


# ---------------------------------------------------------------------------
# Strict JSON loader
# ---------------------------------------------------------------------------

class TestLoadJsonStrict:
    def test_parses_valid_json(self) -> None:
        result = _load_json_strict('{"a": 1}')
        assert result == {"a": 1}

    def test_raises_on_duplicate_key(self) -> None:
        from jacal_validator.validator import _DuplicateKeyError
        with pytest.raises(_DuplicateKeyError) as exc:
            _load_json_strict('{"x": 1, "x": 2}')
        assert "x" in exc.value.keys

    def test_raises_on_invalid_json(self) -> None:
        with pytest.raises(json.JSONDecodeError):
            _load_json_strict('{bad json}')


# ---------------------------------------------------------------------------
# Profile detection
# ---------------------------------------------------------------------------

class TestDetectProfiles:
    def test_no_profiles_for_plain_policy(self) -> None:
        doc = '{"Policy": {"PolicyId": "x", "CombiningAlgId": "deny"}}'
        assert detect_profiles(doc) == []

    def test_detects_xpath_from_xpath_policy_defaults(self) -> None:
        doc = '{"Policy": {"PolicyDefaults": {"XPathPolicyDefaults": {}}}}'
        assert "xpath" in detect_profiles(doc)

    def test_detects_xpath_from_xpath_attribute_selector(self) -> None:
        doc = '{"XPathAttributeSelector": {"Path": "//x"}}'
        assert "xpath" in detect_profiles(doc)

    def test_detects_jsonpath_from_jsonpath_attribute_selector(self) -> None:
        doc = '{"JSONPathAttributeSelector": {"Path": "$.x"}}'
        assert "jsonpath" in detect_profiles(doc)

    def test_detects_both_profiles(self) -> None:
        doc = '"XPathAttributeSelector", "JSONPathAttributeSelector"'
        profiles = detect_profiles(doc)
        assert "xpath" in profiles
        assert "jsonpath" in profiles

    def test_xpath_prefix_required_to_match(self) -> None:
        doc = '{"SomeXPathPolicyDefaults": "no"}'
        assert "xpath" not in detect_profiles(doc)


# ---------------------------------------------------------------------------
# Constraint path evaluator
# ---------------------------------------------------------------------------

class TestEvalPath:
    def test_simple_property(self) -> None:
        doc = {"Policy": {"PolicyId": "p1"}}
        results = eval_path(doc, "$.Policy.PolicyId")
        assert results == [("$.Policy.PolicyId", "p1")]

    def test_array_iteration(self) -> None:
        doc = {"Result": [{"Decision": "Permit"}, {"Decision": "Deny"}]}
        results = eval_path(doc, "$.Result[].Decision")
        values = [v for _, v in results]
        assert values == ["Permit", "Deny"]

    def test_missing_path_returns_empty(self) -> None:
        doc = {"Policy": {}}
        assert eval_path(doc, "$.Bundle.Policy") == []

    def test_recursive_descent(self) -> None:
        doc = {"A": {"B": {"C": 42}}}
        results = eval_path(doc, "$..C")
        assert any(v == 42 for _, v in results)

    def test_nested_array_iteration(self) -> None:
        doc = {"Request": {"MultiRequests": {"RequestReference": [
            {"RequestEntityReference": [{"Id": "a"}, {"Id": "b"}]},
            {"RequestEntityReference": [{"Id": "c"}]},
        ]}}}
        results = eval_path(doc, "$.Request.MultiRequests.RequestReference[].RequestEntityReference[].Id")
        assert [v for _, v in results] == ["a", "b", "c"]


# ---------------------------------------------------------------------------
# ValidationResult contract
# ---------------------------------------------------------------------------

class TestValidationResult:
    def test_valid_by_default(self) -> None:
        r = ValidationResult(format="jacal")
        assert r.valid
        assert not r.incomplete
        assert r.error_count == 0

    def test_becomes_invalid_on_error(self) -> None:
        r = ValidationResult(format="jacal")
        r.add_issue(ValidationIssue(severity=Severity.ERROR, message="bad", rule_id="x"))
        assert not r.valid
        assert r.error_count == 1

    def test_warning_does_not_invalidate(self) -> None:
        r = ValidationResult(format="jacal")
        r.add_issue(ValidationIssue(severity=Severity.WARNING, message="warn", rule_id="y"))
        assert r.valid
        assert r.warning_count == 1

    def test_incomplete_when_skipped(self) -> None:
        r = ValidationResult(format="jacal")
        r.constraints_skipped = 1
        assert r.incomplete


# ---------------------------------------------------------------------------
# End-to-end: 3-way exit code contract
# ---------------------------------------------------------------------------

class TestExitCodeContract:
    """Verify the 3-way exit code semantics against known fixtures."""

    def _validate(self, fixture: str, store) -> ValidationResult:
        path = FIXTURE_DIR / fixture
        return validate(
            json_path=path,
            core_structure_path=store.resolve(SCHEMA_FILES["core_structure"]),
            core_constraints_path=store.resolve(SCHEMA_FILES["core_constraints"]),
            xpath_structure_path=store.try_resolve(SCHEMA_FILES["xpath_structure"]),
            jsonpath_structure_path=store.try_resolve(SCHEMA_FILES["jsonpath_structure"]),
        )

    def test_valid_doc_is_valid_and_complete(self, store) -> None:
        result = self._validate("ex01-rule-simple-permit.json", store)
        assert result.valid
        assert not result.incomplete

    def test_valid_doc_evaluates_all_constraints(self, store) -> None:
        result = self._validate("ex01-rule-simple-permit.json", store)
        assert result.constraints_skipped == 0
        assert result.constraints_evaluated > 0
        assert result.constraints_evaluated == result.constraints_total

    def test_valid_doc_with_xpath_profile_runs_constraints(self, store) -> None:
        path = Path(__file__).parent / "fixtures" / "valid" / "ex09-policy-xpath-defaults.json"
        result = validate(
            json_path=path,
            core_structure_path=store.resolve(SCHEMA_FILES["core_structure"]),
            core_constraints_path=store.resolve(SCHEMA_FILES["core_constraints"]),
            xpath_structure_path=store.try_resolve(SCHEMA_FILES["xpath_structure"]),
            jsonpath_structure_path=store.try_resolve(SCHEMA_FILES["jsonpath_structure"]),
        )
        assert result.valid
        assert "xpath" in result.profiles

    def test_yaml_file_rejected_by_cli(self) -> None:
        from click.testing import CliRunner
        from jacal_validator.cli import main
        runner = CliRunner()
        with tempfile.NamedTemporaryFile(suffix=".yaml", mode="w") as f:
            f.write("Policy:\n  PolicyId: x\n")
            f.flush()
            result = runner.invoke(main, [f.name])
        assert result.exit_code == 2


# ---------------------------------------------------------------------------
# DataType constraints: verify they evaluate but never produce errors
# ---------------------------------------------------------------------------

class TestDataTypeConstraintsNeverFire:
    """These constraints evaluate on every document but never produce errors
    for structurally valid JACAL documents because the schema structurally
    forbids the DataType-in-Value patterns they check.

    Covered rules (evaluate on any valid doc, never error for valid input):
      - attribute-valuetype-datatype-agreement
      - requestattribute-valuetype-datatype-agreement
      - attributeassignment-valuetype-datatype-agreement
      - parameter-valuetype-datatype-agreement
      - sharedvariablereference-argument-datatype-agreement

    Note: request-defaults-unique-concrete-subtype and
    policy-defaults-unique-concrete-subtype are also structurally prevented
    from firing at constraint level, but are only exercised when the document
    contains RequestDefaults or PolicyDefaults respectively (see ex11/ex09).
    """

    def _validate_valid(self, filename: str, store) -> ValidationResult:
        path = FIXTURE_DIR / filename
        return validate(
            json_path=path,
            core_structure_path=store.resolve(SCHEMA_FILES["core_structure"]),
            core_constraints_path=store.resolve(SCHEMA_FILES["core_constraints"]),
            xpath_structure_path=store.try_resolve(SCHEMA_FILES["xpath_structure"]),
            jsonpath_structure_path=store.try_resolve(SCHEMA_FILES["jsonpath_structure"]),
        )

    def test_no_spurious_datatype_errors_on_valid_docs(self, store) -> None:
        for filename in ["ex03-bundle-shared-variable.json", "ex04-bundle-parameterized-sharedvar.json"]:
            result = self._validate_valid(filename, store)
            datatype_errors = [
                i for i in result.issues
                if i.severity == Severity.ERROR
                and "datatype" in (i.rule_id or "").lower()
            ]
            assert not datatype_errors, (
                f"{filename}: unexpected DataType errors: {datatype_errors}"
            )


# ---------------------------------------------------------------------------
# Cross-document reference resolution via --include
# ---------------------------------------------------------------------------

INCLUDE_DIR = Path(__file__).parent / "fixtures" / "include"
INCOMPLETE_DIR = Path(__file__).parent / "fixtures" / "incomplete"


class TestIncludePathResolution:
    """Verify that supplying external definitions via include_paths resolves
    cross-document skip warnings and produces a complete (exit 0) result."""

    def _validate_with_include(self, incomplete_filename: str, include_filename: str, store) -> ValidationResult:
        return validate(
            json_path=INCOMPLETE_DIR / incomplete_filename,
            core_structure_path=store.resolve(SCHEMA_FILES["core_structure"]),
            core_constraints_path=store.resolve(SCHEMA_FILES["core_constraints"]),
            xpath_structure_path=store.try_resolve(SCHEMA_FILES["xpath_structure"]),
            jsonpath_structure_path=store.try_resolve(SCHEMA_FILES["jsonpath_structure"]),
            include_paths=[INCLUDE_DIR / include_filename],
        )

    def test_policyreference_resolved_via_include(self, store) -> None:
        result = self._validate_with_include(
            "inc01-policyreference-external-policy.json",
            "ext-policy.json",
            store,
        )
        assert result.valid, (
            "inc01 + ext-policy.json should be valid but got errors: "
            + ", ".join(i.rule_id or "?" for i in result.issues if i.severity.name == "ERROR")
        )
        assert not result.incomplete, (
            "inc01 + ext-policy.json should be complete (no unresolved refs) but "
            f"got {result.constraints_skipped} skipped constraint(s): "
            + ", ".join(i.rule_id or "?" for i in result.issues if (i.rule_id or "").startswith("jacal-skip:"))
        )

    def test_sharedvariablereference_resolved_via_include(self, store) -> None:
        result = self._validate_with_include(
            "inc02-sharedvariablereference-external.json",
            "ext-sharedvar.json",
            store,
        )
        assert result.valid, (
            "inc02 + ext-sharedvar.json should be valid but got errors: "
            + ", ".join(i.rule_id or "?" for i in result.issues if i.severity.name == "ERROR")
        )
        assert not result.incomplete, (
            "inc02 + ext-sharedvar.json should be complete (no unresolved refs) but "
            f"got {result.constraints_skipped} skipped constraint(s): "
            + ", ".join(i.rule_id or "?" for i in result.issues if (i.rule_id or "").startswith("jacal-skip:"))
        )

    def test_without_include_policyreference_is_incomplete(self, store) -> None:
        result = validate(
            json_path=INCOMPLETE_DIR / "inc01-policyreference-external-policy.json",
            core_structure_path=store.resolve(SCHEMA_FILES["core_structure"]),
            core_constraints_path=store.resolve(SCHEMA_FILES["core_constraints"]),
            xpath_structure_path=store.try_resolve(SCHEMA_FILES["xpath_structure"]),
            jsonpath_structure_path=store.try_resolve(SCHEMA_FILES["jsonpath_structure"]),
        )
        assert result.valid
        assert result.incomplete

    def test_without_include_sharedvariablereference_is_incomplete(self, store) -> None:
        result = validate(
            json_path=INCOMPLETE_DIR / "inc02-sharedvariablereference-external.json",
            core_structure_path=store.resolve(SCHEMA_FILES["core_structure"]),
            core_constraints_path=store.resolve(SCHEMA_FILES["core_constraints"]),
            xpath_structure_path=store.try_resolve(SCHEMA_FILES["xpath_structure"]),
            jsonpath_structure_path=store.try_resolve(SCHEMA_FILES["jsonpath_structure"]),
        )
        assert result.valid
        assert result.incomplete
