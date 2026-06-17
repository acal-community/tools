"""Parametrized fixture tests for jacal-validator.

Three categories:
  VALID   — expect PASS   (exit 0: valid=True, incomplete=False)
  INVALID — expect FAIL   (exit 1: valid=False)
  INCOMPLETE — expect INCOMPLETE (exit 2: valid=True, incomplete=True)

Invalid fixtures are sub-divided by where the error is caught:
  STRUCTURAL: rejected by the JSON Schema (rule_id starts with 'jsonschema:')
  CONSTRAINT: rejected by the constraint catalog (rule_id starts with 'jacal:')
  JSON:       rejected by the JSON conformance linter (rule_id starts with 'json:')

DataType agreement constraints that are structurally prevented in JACAL
(never fire for valid documents due to schema dependentSchemas):
  - attribute-valuetype-datatype-agreement
  - requestattribute-valuetype-datatype-agreement
  - attributeassignment-valuetype-datatype-agreement
  - parameter-valuetype-datatype-agreement
  - sharedvariablereference-argument-datatype-agreement
  - policyreference-argument-datatype-agreement (produces skip warning for external refs)
"""
from __future__ import annotations

from pathlib import Path

import pytest

from jacal_validator.base import Severity
from jacal_validator.schemas import SCHEMA_FILES
from jacal_validator.validator import validate

FIXTURE_DIR = Path(__file__).parent / "fixtures"

# ---------------------------------------------------------------------------
# Valid fixtures — must PASS with 41 constraints evaluated, 0 skipped
# ---------------------------------------------------------------------------
VALID_FIXTURES: dict[str, str] = {
    "ex01-rule-simple-permit.json": "simple Rule with Permit effect",
    "ex02-rule-short-identifiers.json": "Rule using short identifiers",
    "ex03-bundle-shared-variable.json": "Bundle with SharedVariableDefinition",
    "ex04-bundle-parameterized-sharedvar.json": "Bundle with parameterised shared variable",
    "ex05-request-multirequests.json": "Request with MultiRequests",
    "ex06-response-missing-attribute.json": "Response with missing-attribute status",
    "ex07-policy-notice-expression.json": "Policy with NoticeExpression",
    "ex08-policy-nested-policies.json": "Policy with nested Policy in CombinerInput",
    "ex09-policy-xpath-defaults.json": "Policy with XPath profile",
    "ex10-policy-jsonpath-selector.json": "Policy with JSONPath profile",
}

# ---------------------------------------------------------------------------
# Invalid fixtures — must FAIL (at least one ERROR issue)
#
# Structural: JSON Schema rejects the document before constraint evaluation
# ---------------------------------------------------------------------------
STRUCTURAL_INVALID_FIXTURES: dict[str, str] = {
    "err01-unknown-toplevel-key.json": "unknown top-level key (PolicySet not a valid form)",
    "err02-missing-required-fields.json": "missing required fields in Policy",
    "err03-rule-with-target.json": "Rule.Target is forbidden (additionalProperties)",
    "err17-bundle-policyreference-without-policy.json": "dependentRequired: Policy required when PolicyReference present",
    "err25-shortidset-reference-repeated-node.json": "uniqueItems: ShortIdSetReference must not repeat entries",
    "err33-parameter-expression-valuetype-datatype-forbidden.json": "dependentSchemas: Parameter.Expression.Value.DataType is forbidden",
}

# Constraint: semantic rule from the catalog or supplementary checker
CONSTRAINT_INVALID_FIXTURES: dict[str, str] = {
    "err04-duplicate-notice-ids.json": "jacal:rule-noticeexpression-id-unique",
    "err05-bundle-duplicate-policy-ids.json": "jacal:bundle-policy-policyid-unique",
    "err06-duplicate-rule-ids.json": "jacal:rule-id-unique-within-policy",
    "err07-duplicate-shortid-names.json": "jacal:shortidset-shortid-name-unique",
    "err08-request-duplicate-entity-ids.json": "jacal:request-entity-id-unique",
    "err09-request-duplicate-attribute-ids.json": "jacal:request-attribute-id-unique-within-entity",
    "err10-duplicate-requestentityreference-ids.json": "jacal:requestreference-requestentityreference-id-unique",
    "err11-requestentityreference-unresolved.json": "jacal:requestreference-requestentityreference-resolves",
    "err12-requestreference-duplicate-entity-id-set.json": "jacal:multirequests-requestreference-unique-by-entity-id-set",
    "err13-statusdetail-forbidden-for-ok.json": "jacal:statusdetail-forbidden-for-ok",
    "err14-statusdetail-forbidden-for-syntax-error.json": "jacal:statusdetail-forbidden-for-syntax-error",
    "err15-statusdetail-forbidden-for-processing-error.json": "jacal:statusdetail-forbidden-for-processing-error",
    "err16-statusdetail-invalid-key-for-missing-attribute.json": "jacal:statusdetail-missing-attribute-shape",
    "err18-bundle-duplicate-shortidset-ids.json": "jacal:bundle-shortidset-id-unique",
    "err19-bundle-duplicate-sharedvariable-ids.json": "jacal:bundle-sharedvariabledefinition-id-unique",
    "err20-policy-duplicate-parameter-names.json": "jacal:policy-parameter-name-unique",
    "err21-sharedvariable-duplicate-parameter-names.json": "jacal:shared-variable-parameter-name-unique",
    "err22-policy-duplicate-variable-ids.json": "jacal:policy-variable-id-scoped-unique",
    "err23-rule-duplicate-variable-ids.json": "jacal:rule-variable-id-scoped-unique",
    "err24-shortidset-reference-cycle.json": "jacal:shortidset-reference-acyclic",
    "err26-sharedvariable-reference-cycle.json": "jacal:shared-variable-reference-acyclic",
    "err27-sharedvariable-contains-variablereference.json": "jacal:shared-variable-definition-no-variable-reference",
    "err28-policy-duplicate-noticeexpression-ids.json": "jacal:policy-noticeexpression-id-unique",
    "err29-result-duplicate-notice-ids.json": "jacal:result-notice-id-unique",
    "err30-result-duplicate-resultentity-categories.json": "jacal:result-resultentity-category-unique",
    "err31-result-duplicate-applicablepolicyreference-ids.json": "jacal:result-applicablepolicyreference-id-unique",
    "err32-resultentity-duplicate-attribute-ids.json": "jacal:resultentity-attribute-attributeid-unique",
}

# JSON conformance: caught before schema or constraint evaluation
JSON_INVALID_FIXTURES: dict[str, str] = {
    "err34-json-duplicate-key.json": "json:duplicate-key",
    "err35-json-comment.json": "json:comment",
    "err36-json-trailing-comma.json": "json:trailing-comma",
}

# ---------------------------------------------------------------------------
# Incomplete fixtures — must return valid=True but incomplete=True (rc=2)
# ---------------------------------------------------------------------------
INCOMPLETE_FIXTURES: dict[str, str] = {
    "inc01-policyreference-external-policy.json": "jacal-skip:policyreference-argument-datatype-agreement",
    "inc02-sharedvariablereference-external.json": "jacal-skip:sharedvariablereference-argument-datatype-agreement",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(fixture_dir: str, filename: str, store) -> "ValidationResult":  # noqa: F821
    path = FIXTURE_DIR / fixture_dir / filename
    return validate(
        json_path=path,
        core_structure_path=store.resolve(SCHEMA_FILES["core_structure"]),
        core_constraints_path=store.resolve(SCHEMA_FILES["core_constraints"]),
        xpath_structure_path=store.try_resolve(SCHEMA_FILES["xpath_structure"]),
        jsonpath_structure_path=store.try_resolve(SCHEMA_FILES["jsonpath_structure"]),
    )


def _error_rule_ids(result) -> list[str]:
    return [i.rule_id for i in result.issues if i.severity == Severity.ERROR]


def _skip_rule_ids(result) -> list[str]:
    return [
        i.rule_id for i in result.issues
        if (i.rule_id or "").startswith("jacal-skip:")
    ]


# ---------------------------------------------------------------------------
# Test: valid fixtures
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("filename,description", VALID_FIXTURES.items(), ids=list(VALID_FIXTURES))
def test_valid_fixture_passes(filename: str, description: str, store) -> None:
    result = _run("valid", filename, store)
    assert result.valid, (
        f"{filename} ({description}) should be valid but got errors:\n"
        + "\n".join(f"  {i.rule_id}: {i.message}" for i in result.issues if i.severity == Severity.ERROR)
    )
    assert not result.incomplete, f"{filename} should be complete (no cross-document refs)"
    assert result.constraints_evaluated >= 38, (
        f"{filename}: expected ≥38 constraints evaluated, got {result.constraints_evaluated}"
    )
    assert result.constraints_skipped == 0, f"{filename}: expected 0 skipped, got {result.constraints_skipped}"


# ---------------------------------------------------------------------------
# Test: structural invalid fixtures
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("filename,description", STRUCTURAL_INVALID_FIXTURES.items(), ids=list(STRUCTURAL_INVALID_FIXTURES))
def test_structural_invalid_fixture_fails(filename: str, description: str, store) -> None:
    result = _run("invalid", filename, store)
    assert not result.valid, f"{filename} ({description}) should be INVALID but passed"
    error_rules = _error_rule_ids(result)
    assert any(r and r.startswith("jsonschema:") for r in error_rules), (
        f"{filename}: expected a jsonschema: rule_id but got {error_rules}"
    )


# ---------------------------------------------------------------------------
# Test: constraint invalid fixtures
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("filename,expected_rule", CONSTRAINT_INVALID_FIXTURES.items(), ids=list(CONSTRAINT_INVALID_FIXTURES))
def test_constraint_invalid_fixture_fails(filename: str, expected_rule: str, store) -> None:
    result = _run("invalid", filename, store)
    assert not result.valid, f"{filename} should be INVALID but passed"
    error_rules = _error_rule_ids(result)
    assert expected_rule in error_rules, (
        f"{filename}: expected rule_id {expected_rule!r} but got {error_rules}"
    )


# ---------------------------------------------------------------------------
# Test: JSON conformance invalid fixtures
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("filename,expected_rule", JSON_INVALID_FIXTURES.items(), ids=list(JSON_INVALID_FIXTURES))
def test_json_invalid_fixture_fails(filename: str, expected_rule: str, store) -> None:
    result = _run("invalid", filename, store)
    assert not result.valid, f"{filename} should be INVALID but passed"
    error_rules = _error_rule_ids(result)
    assert expected_rule in error_rules, (
        f"{filename}: expected rule_id {expected_rule!r} but got {error_rules}"
    )
    # JSON conformance errors prevent schema/constraint evaluation
    assert result.constraints_total == 0, (
        f"{filename}: constraints should not run after JSON conformance failure"
    )


# ---------------------------------------------------------------------------
# Test: incomplete fixtures
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("filename,expected_skip_rule", INCOMPLETE_FIXTURES.items(), ids=list(INCOMPLETE_FIXTURES))
def test_incomplete_fixture_is_incomplete(filename: str, expected_skip_rule: str, store) -> None:
    result = _run("incomplete", filename, store)
    assert result.valid, (
        f"{filename} should be structurally valid but got errors:\n"
        + "\n".join(f"  {i.rule_id}: {i.message}" for i in result.issues if i.severity == Severity.ERROR)
    )
    assert result.incomplete, f"{filename}: expected incomplete=True (cross-document refs not checked)"
    skip_rules = _skip_rule_ids(result)
    assert expected_skip_rule in skip_rules, (
        f"{filename}: expected skip rule_id {expected_skip_rule!r} but got {skip_rules}"
    )
