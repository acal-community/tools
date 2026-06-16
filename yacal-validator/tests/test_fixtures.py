"""Fixture-based tests: valid documents from the ACAL Adoption Guide + invalid/error examples.

Valid fixtures come directly from ACAL Adoption Guide examples and must pass structural and
constraint validation (only the 2 permanently-skipped cross-document rules may warn).

Invalid fixtures demonstrate errors the tool detects — both structural violations
(unknown top-level keys, wrong field types, removed XACML 3.0 constructs) and constraint
violations (duplicate IDs, duplicate names).

Supplementary constraint checks (rule-id-unique-within-policy and shortidset-shortid-name-unique)
fill gaps in the upstream catalog and are included in the constraints_total counter.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from yacal_validator.schemas import SCHEMA_FILES
from yacal_validator.validator import validate

FIXTURES_DIR = Path(__file__).parent / "fixtures"
VALID_DIR = FIXTURES_DIR / "valid"
INVALID_DIR = FIXTURES_DIR / "invalid"
INCOMPLETE_DIR = FIXTURES_DIR / "incomplete"


@pytest.fixture(scope="module")
def schema_paths(store):
    return {
        "structure": store.resolve(SCHEMA_FILES["core_structure"]),
        "constraints": store.resolve(SCHEMA_FILES["core_constraints"]),
        "xpath": store.try_resolve(SCHEMA_FILES["xpath_structure"]),
        "jsonpath": store.try_resolve(SCHEMA_FILES["jsonpath_structure"]),
    }


def _validate(path: Path, schema_paths: dict, include_paths: list[Path] | None = None):
    return validate(
        path,
        core_structure_path=schema_paths["structure"],
        core_constraints_path=schema_paths["constraints"],
        xpath_structure_path=schema_paths["xpath"],
        jsonpath_structure_path=schema_paths["jsonpath"],
        include_paths=include_paths,
    )


# ---------------------------------------------------------------------------
# Valid fixtures (adoption guide examples — must pass with no errors)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("filename", [
    "ex01-rule-simple-permit.yaml",
    "ex02-rule-short-identifiers.yaml",
    "ex03-policy-website-content-access.yaml",
    "ex04-rule-notice-expression.yaml",
    "ex06-policy-nested-policies.yaml",
    "ex08-rule-quantified-expression.yaml",
    "ex09-bundle-shared-variable.yaml",
    "ex10-bundle-parameterized-sharedvar.yaml",
])
def test_valid_fixture_passes(filename, schema_paths):
    """Adoption guide examples must pass with no errors and no warnings."""
    result = _validate(VALID_DIR / filename, schema_paths)
    errors = [i for i in result.issues if i.severity.value == "error"]
    assert result.valid, f"Expected PASS for {filename}, got errors: {[e.message for e in errors]}"
    assert not errors
    assert not result.issues, (
        f"Unexpected warnings in {filename}: {[i.message for i in result.issues]}"
    )


def test_valid_fixtures_run_full_constraint_catalog(schema_paths):
    """All constraints must be evaluated (0 skipped) for all valid fixtures.

    Phase 1 within-document resolution eliminates the two formerly-skipped
    cross-document constraints for documents whose references resolve within
    the same Bundle.
    """
    for fixture in sorted(VALID_DIR.glob("*.yaml")):
        result = _validate(fixture, schema_paths)
        if result.valid:
            assert result.constraints_total > 0, (
                f"No constraints ran for {fixture.name}"
            )
            assert result.constraints_skipped == 0, (
                f"Expected 0 skipped, got {result.constraints_skipped} for {fixture.name}. "
                f"Unexpected skip issues: {[i.message for i in result.issues if (i.rule_id or '').startswith('yacal-skip:')]}"
            )
            assert result.constraints_evaluated == result.constraints_total, (
                f"Expected all {result.constraints_total} evaluated for {fixture.name}"
            )


# ---------------------------------------------------------------------------
# Invalid fixtures — structural errors (XACML 3.0 constructs removed in ACAL 1.0)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("filename", [
    "err01-policyset-removed.yaml",
    "err02-anyof-allof-target-syntax.yaml",
    "err03-obligation-advice-expressions.yaml",
    "err05-missing-required-fields.yaml",
    "err07-rule-with-target.yaml",
])
def test_structural_error_fixture_fails(filename, schema_paths):
    """Documents with removed XACML 3.0 constructs or missing required fields must fail."""
    result = _validate(INVALID_DIR / filename, schema_paths)
    assert not result.valid, f"Expected FAIL for {filename} but it passed"
    errors = [i for i in result.issues if i.severity.value == "error"]
    assert errors, f"No errors reported for {filename}"


def test_err01_policyset_fails_at_root(schema_paths):
    """PolicySet (removed in ACAL 1.0) must fail at the document root."""
    result = _validate(INVALID_DIR / "err01-policyset-removed.yaml", schema_paths)
    assert not result.valid
    root_errors = [i for i in result.issues if i.path == "$" and i.severity.value == "error"]
    assert root_errors


def test_err07_rule_with_target_fails(schema_paths):
    """Rules with a Target property (removed in ACAL 1.0) must fail structural validation."""
    result = _validate(INVALID_DIR / "err07-rule-with-target.yaml", schema_paths)
    assert not result.valid


# ---------------------------------------------------------------------------
# Invalid fixtures — constraint violations (catalog + supplementary checks)
# ---------------------------------------------------------------------------

def test_err04_duplicate_notice_ids_caught_by_constraint(schema_paths):
    """Duplicate NoticeExpression IDs within a Rule must be caught by the constraint catalog."""
    result = _validate(INVALID_DIR / "err04-duplicate-notice-ids.yaml", schema_paths)
    assert not result.valid
    constraint_errors = [
        i for i in result.issues
        if (i.rule_id or "").startswith("yacal:") and i.severity.value == "error"
    ]
    assert any("rule-noticeexpression-id-unique" in (i.rule_id or "") for i in constraint_errors)


def test_err06_duplicate_bundle_policy_ids_caught_by_constraint(schema_paths):
    """Duplicate PolicyId values in a Bundle must be caught by the constraint catalog."""
    result = _validate(INVALID_DIR / "err06-bundle-duplicate-policy-ids.yaml", schema_paths)
    assert not result.valid
    constraint_errors = [
        i for i in result.issues
        if (i.rule_id or "").startswith("yacal:") and i.severity.value == "error"
    ]
    assert any("bundle-policy-policyid-unique" in (i.rule_id or "") for i in constraint_errors)


def test_err08_duplicate_rule_ids_caught_by_supplementary_check(schema_paths):
    """Duplicate Rule IDs within a Policy CombinerInput are caught by supplementary check.
    The upstream catalog is missing this constraint — it is implemented locally.
    """
    result = _validate(INVALID_DIR / "err08-duplicate-rule-ids.yaml", schema_paths)
    assert not result.valid
    constraint_errors = [
        i for i in result.issues
        if (i.rule_id or "").startswith("yacal:") and i.severity.value == "error"
    ]
    assert any(
        "rule-id-unique-within-policy" in (i.rule_id or "") for i in constraint_errors
    ), f"Supplementary rule-id check did not fire. Issues: {[i.rule_id for i in result.issues]}"


def test_err09_duplicate_shortid_names_caught_by_supplementary_check(schema_paths):
    """Duplicate ShortId Names are caught by supplementary check.
    The upstream catalog path is wrong for all real document forms — implemented locally.
    """
    result = _validate(INVALID_DIR / "err09-duplicate-shortid-names.yaml", schema_paths)
    assert not result.valid
    constraint_errors = [
        i for i in result.issues
        if (i.rule_id or "").startswith("yacal:") and i.severity.value == "error"
    ]
    assert any(
        "shortidset-shortid-name-unique" in (i.rule_id or "") for i in constraint_errors
    ), f"Supplementary shortid check did not fire. Issues: {[i.rule_id for i in result.issues]}"


def test_err10_sharedvar_datatype_mismatch_caught_by_phase1(schema_paths):
    """Phase 1: SharedVariableReference DataType mismatch caught via within-Bundle resolution.

    The parameter declares DataType={string}; the reference passes DataType={integer}.
    The within-document index resolves the definition and the catalog constraint fires.
    No skip warnings should be emitted — this is a fully evaluated constraint.
    """
    result = _validate(INVALID_DIR / "err10-sharedvar-datatype-mismatch.yaml", schema_paths)
    assert not result.valid
    constraint_errors = [
        i for i in result.issues
        if (i.rule_id or "").startswith("yacal:") and i.severity.value == "error"
    ]
    assert any(
        "sharedvariablereference-argument-datatype-agreement" in (i.rule_id or "")
        for i in constraint_errors
    ), f"Phase 1 DataType check did not fire. Issues: {[i.rule_id for i in result.issues]}"
    skip_issues = [i for i in result.issues if (i.rule_id or "").startswith("yacal-skip:")]
    assert not skip_issues, (
        f"Expected no skip issues when definition is in-Bundle, got: {[i.message for i in skip_issues]}"
    )


# ---------------------------------------------------------------------------
# Phase 2: --include for cross-file reference resolution
# ---------------------------------------------------------------------------

_INC01 = INCOMPLETE_DIR / "inc01-bundle-external-policy-ref.yaml"
_INC01_MATCH = INCOMPLETE_DIR / "inc01-external-policy-matching.yaml"
_INC01_MISMATCH = INCOMPLETE_DIR / "inc01-external-policy-mismatched.yaml"


def test_phase2_without_include_is_incomplete(schema_paths):
    """Without --include, a cross-file PolicyReference produces incomplete validation (exit 2).

    The document is structurally valid and the referenced policy exists — but since
    the policy definition is not provided, the DataType constraint cannot be evaluated.
    result.valid must be True (document has no errors) and result.incomplete must be True.
    """
    result = _validate(_INC01, schema_paths)
    assert result.valid, "Document is structurally valid; errors indicate a regression"
    assert result.incomplete, "Expected incomplete=True when --include is absent"
    assert result.constraints_skipped > 0
    skip_issues = [i for i in result.issues if (i.rule_id or "").startswith("yacal-skip:")]
    assert skip_issues, "Expected at least one skip issue for the cross-file PolicyReference"


def test_phase2_with_matching_include_is_complete_pass(schema_paths):
    """With --include providing the matching Policy, validation is fully evaluated and passes."""
    result = _validate(_INC01, schema_paths, include_paths=[_INC01_MATCH])
    assert result.valid
    assert not result.incomplete, "Expected incomplete=False when --include resolves all references"
    assert result.constraints_skipped == 0
    errors = [i for i in result.issues if i.severity.value == "error"]
    assert not errors


def test_phase2_with_mismatched_include_catches_datatype_error(schema_paths):
    """With --include providing a Policy whose parameter DataType mismatches the argument, validation fails."""
    result = _validate(_INC01, schema_paths, include_paths=[_INC01_MISMATCH])
    assert not result.valid
    assert not result.incomplete, "Result is FAIL (error found), not incomplete"
    constraint_errors = [
        i for i in result.issues
        if (i.rule_id or "").startswith("yacal:") and i.severity.value == "error"
    ]
    assert any(
        "policyreference-argument-datatype-agreement" in (i.rule_id or "")
        for i in constraint_errors
    ), f"Phase 2 DataType check did not fire. Issues: {[i.rule_id for i in result.issues]}"
