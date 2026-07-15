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

VALID_FIXTURES = [
    "ex01-rule-simple-permit.yaml",
    "ex02-rule-short-identifiers.yaml",
    "ex03-policy-website-content-access.yaml",
    "ex04-rule-notice-expression.yaml",
    "ex06-policy-nested-policies.yaml",
    "ex08-rule-quantified-expression.yaml",
    "ex09-bundle-shared-variable.yaml",
    "ex10-bundle-parameterized-sharedvar.yaml",
    "ex11-request-multirequests.yaml",
    "ex12-response-missing-attribute.yaml",
    "ex13-shortidset-standalone.yaml",
    "ex14-policy-xpath-defaults.yaml",
    "ex15-policy-jsonpath-selector.yaml",
    "ex16-response-full-result.yaml",
    "ex17-request-multirequests-expanded.yaml",
    # Duplicate notice Ids are permitted per spec issue #94 (PR #100) — see fixtures.
    "ex18-notice-duplicate-ids-rule.yaml",
    "ex19-notice-duplicate-ids-policy.yaml",
    "ex20-notice-duplicate-ids-result.yaml",
]

PROFILE_EXPECTATIONS = {
    "ex14-policy-xpath-defaults.yaml": ["xpath"],
    "ex15-policy-jsonpath-selector.yaml": ["jsonpath"],
}

STRUCTURAL_INVALID_FIXTURES = [
    "err01-policyset-removed.yaml",
    "err02-anyof-allof-target-syntax.yaml",
    "err03-obligation-advice-expressions.yaml",
    "err05-missing-required-fields.yaml",
    "err07-rule-with-target.yaml",
    "err49-condition-literal-value.yaml",
]

CONSTRAINT_INVALID_RULES = {
    # NOTE: notice-Id uniqueness constraints were removed by spec issue #94 (PR #100). The
    # former err04 / err36 / err37 fixtures are now valid (see VALID_FIXTURES, ex18–ex20).
    "err06-bundle-duplicate-policy-ids.yaml": "bundle-policy-policyid-unique",
    "err08-duplicate-rule-ids.yaml": "rule-id-unique-within-policy",
    "err09-duplicate-shortid-names.yaml": "shortidset-shortid-name-unique",
    "err10-sharedvar-datatype-mismatch.yaml": "sharedvariablereference-argument-datatype-agreement",
    "err11-request-duplicate-entity-ids.yaml": "request-entity-id-unique",
    "err12-request-duplicate-attribute-ids.yaml": "request-attribute-id-unique-within-entity",
    "err13-requestreference-duplicate-entity-ids.yaml": "requestreference-requestentityreference-id-unique",
    "err14-requestreference-unresolved-entity-id.yaml": "requestreference-requestentityreference-resolves",
    "err15-multirequests-duplicate-reference-set.yaml": "multirequests-requestreference-unique-by-entity-id-set",
    "err16-response-statusdetail-forbidden-ok.yaml": "statusdetail-forbidden-for-ok",
    "err17-response-statusdetail-forbidden-syntax-error.yaml": "statusdetail-forbidden-for-syntax-error",
    "err18-response-statusdetail-forbidden-processing-error.yaml": "statusdetail-forbidden-for-processing-error",
    "err19-bundle-policyreference-without-policy.yaml": "bundle-policyreference-requires-policy",
    "err20-bundle-duplicate-shortidset-ids.yaml": "bundle-shortidset-id-unique",
    "err21-bundle-duplicate-sharedvar-ids.yaml": "bundle-sharedvariabledefinition-id-unique",
    "err22-sharedvar-variable-reference-disallowed.yaml": "shared-variable-definition-no-variable-reference",
    "err23-sharedvar-reference-cycle.yaml": "shared-variable-reference-acyclic",
    "err24-policy-duplicate-parameter-names.yaml": "policy-parameter-name-unique",
    "err25-sharedvar-duplicate-parameter-names.yaml": "shared-variable-parameter-name-unique",
    "err26-policy-duplicate-variable-ids.yaml": "policy-variable-id-scoped-unique",
    "err27-rule-duplicate-variable-ids.yaml": "rule-variable-id-scoped-unique",
    "err28-standalone-shortidset-self-cycle.yaml": "shortidset-reference-acyclic",
    "err29-bundle-shortidset-repeat-reference.yaml": "shortidset-reference-no-repeat",
    "err30-policy-defaults-duplicate-subtype.yaml": "policy-defaults-unique-concrete-subtype",
    "err31-request-defaults-duplicate-subtype.yaml": "request-defaults-unique-concrete-subtype",
    "err32-attribute-valuetype-datatype-mismatch.yaml": "attribute-valuetype-datatype-agreement",
    "err33-requestattribute-valuetype-datatype-mismatch.yaml": "requestattribute-valuetype-datatype-agreement",
    "err34-attributeassignment-valuetype-datatype-mismatch.yaml": "attributeassignment-valuetype-datatype-agreement",
    "err35-parameter-valuetype-datatype-mismatch.yaml": "parameter-valuetype-datatype-agreement",
    "err38-resultentity-duplicate-category.yaml": "result-resultentity-category-unique",
    "err45-resultentity-duplicate-attribute-ids.yaml": "resultentity-attribute-attributeid-unique",
    "err46-applicablepolicyreference-duplicate-ids.yaml": "result-applicablepolicyreference-id-unique",
    "err47-graph-indirect-repeat.yaml": "shortidset-reference-no-repeat",
    "err48-sharedvar-nested-variable-reference.yaml": "shared-variable-definition-no-variable-reference",
}

YAML_INVALID_RULES = {
    "err39-yaml-tag.yaml": "yaml:disallowed-tag",
    "err40-yaml-anchor-alias.yaml": "yaml:disallowed-anchor",
    "err41-yaml-merge-key.yaml": "yaml:disallowed-merge-key",
    "err42-yaml-null.yaml": "yaml:null-value",
    "err43-yaml-octal-integer.yaml": "yaml:octal-integer",
    "err44-yaml-multi-document.yaml": "yaml:multi-document-stream",
}


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

@pytest.mark.parametrize("filename", VALID_FIXTURES)
def test_valid_fixture_passes(filename, schema_paths):
    """Curated valid YACAL fixtures must pass with no errors and no warnings."""
    result = _validate(VALID_DIR / filename, schema_paths)
    errors = [i for i in result.issues if i.severity.value == "error"]
    assert result.valid, f"Expected PASS for {filename}, got errors: {[e.message for e in errors]}"
    assert not errors
    assert not result.issues, (
            f"Unexpected warnings in {filename}: {[i.message for i in result.issues]}"
        )


@pytest.mark.parametrize("filename, expected_profiles", PROFILE_EXPECTATIONS.items())
def test_profile_fixture_detects_expected_profiles(filename, expected_profiles, schema_paths):
    result = _validate(VALID_DIR / filename, schema_paths)
    assert result.valid
    for profile in expected_profiles:
        assert profile in result.profiles, (
            f"Expected profile {profile!r} for {filename}, got {result.profiles}"
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

@pytest.mark.parametrize("filename", STRUCTURAL_INVALID_FIXTURES)
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

@pytest.mark.parametrize("filename, expected_rule", CONSTRAINT_INVALID_RULES.items())
def test_constraint_error_fixture_fails_for_expected_rule(filename, expected_rule, schema_paths):
    result = _validate(INVALID_DIR / filename, schema_paths)
    assert not result.valid
    constraint_errors = [
        i for i in result.issues
        if (i.rule_id or "").startswith("yacal:") and i.severity.value == "error"
    ]
    assert any(
        expected_rule in (i.rule_id or "")
        for i in constraint_errors
    ), f"Expected rule {expected_rule!r} for {filename}. Issues: {[i.rule_id for i in result.issues]}"


def test_err10_sharedvar_datatype_mismatch_has_no_skip_warnings(schema_paths):
    """Within-document SharedVariableReference resolution should not produce skip warnings."""
    result = _validate(INVALID_DIR / "err10-sharedvar-datatype-mismatch.yaml", schema_paths)
    skip_issues = [i for i in result.issues if (i.rule_id or "").startswith("yacal-skip:")]
    assert not skip_issues, (
        f"Expected no skip issues when definition is in-Bundle, got: {[i.message for i in skip_issues]}"
    )


@pytest.mark.parametrize("filename, expected_rule", YAML_INVALID_RULES.items())
def test_yaml_conformance_fixture_fails_for_expected_rule(filename, expected_rule, schema_paths):
    result = _validate(INVALID_DIR / filename, schema_paths)
    assert not result.valid
    error_rule_ids = [i.rule_id for i in result.issues if i.severity.value == "error"]
    assert expected_rule in error_rule_ids, (
        f"Expected YAML rule {expected_rule!r} for {filename}. Issues: {error_rule_ids}"
    )


# ---------------------------------------------------------------------------
# Phase 2: --include for cross-file reference resolution
# ---------------------------------------------------------------------------

_INC01 = INCOMPLETE_DIR / "inc01-policy-external-policy-ref.yaml"
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
