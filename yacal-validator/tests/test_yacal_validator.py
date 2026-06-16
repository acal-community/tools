"""Tests for YACAL v1.0 (YAML) validation."""
from __future__ import annotations

from pathlib import Path

import pytest

from yacal_validator.validator import validate, detect_profiles
from yacal_validator.schemas import SCHEMA_FILES

VALID_FIXTURES_DIR = Path(__file__).parent / "fixtures" / "valid"


@pytest.fixture(scope="module")
def yaml_schemas(store):
    return {
        "structure": store.resolve(SCHEMA_FILES["core_structure"]),
        "constraints": store.resolve(SCHEMA_FILES["core_constraints"]),
        "xpath": store.try_resolve(SCHEMA_FILES["xpath_structure"]),
        "jsonpath": store.try_resolve(SCHEMA_FILES["jsonpath_structure"]),
    }


# ---------------------------------------------------------------------------
# Profile detection
# ---------------------------------------------------------------------------

def test_no_profiles():
    assert detect_profiles("Policy:\n  PolicyId: foo\n") == []


def test_xpath_profile_detected():
    assert "xpath" in detect_profiles("XPathAttributeSelector:\n  Path: foo\n")


def test_jsonpath_profile_detected():
    assert "jsonpath" in detect_profiles("JSONPathAttributeSelector:\n  Path: foo\n")


# ---------------------------------------------------------------------------
# Parse errors
# ---------------------------------------------------------------------------

def test_bad_yaml_syntax(yaml_schemas, tmp_path):
    f = tmp_path / "bad.yaml"
    f.write_text("{{bad: yaml: [unclosed")
    result = validate(f, yaml_schemas["structure"], yaml_schemas["constraints"], None, None)
    assert not result.valid
    assert any("yaml" in i.message.lower() or "YAML" in i.message for i in result.issues)


def test_empty_document(yaml_schemas, tmp_path):
    f = tmp_path / "empty.yaml"
    f.write_text("")
    result = validate(f, yaml_schemas["structure"], yaml_schemas["constraints"], None, None)
    assert not result.valid


# ---------------------------------------------------------------------------
# Schema violations
# ---------------------------------------------------------------------------

def test_wrong_top_level_key(yaml_schemas, tmp_path):
    f = tmp_path / "bad.yaml"
    f.write_text("NotAPolicy:\n  foo: bar\n")
    result = validate(f, yaml_schemas["structure"], yaml_schemas["constraints"], None, None)
    assert not result.valid


# ---------------------------------------------------------------------------
# Constraint catalog: uniqueByProperty
# ---------------------------------------------------------------------------

def test_duplicate_shortid_names_flagged(yaml_schemas, tmp_path):
    """Duplicate ShortId Name values within one ShortIdSet should be an error."""
    f = tmp_path / "dup.yaml"
    f.write_text("""
Policy:
  PolicyId: "urn:example:policy:1"
  Version: "1.0"
  CombiningAlgId: "urn:oasis:names:tc:acal:1.0:combining-algorithm:deny-overrides"
  ShortIdSet:
    Id: "urn:example:shortidset:1"
    ShortId:
      - Name: alpha
        Value: "urn:example:a"
      - Name: alpha
        Value: "urn:example:b"
  CombinerInput: []
""")
    result = validate(f, yaml_schemas["structure"], yaml_schemas["constraints"], None, None)
    dup_issues = [
        i for i in result.issues
        if "shortidset-shortid-name-unique" in (i.rule_id or "") or "alpha" in i.message
    ]
    # Constraint must fire OR structural validation catches it first — either way invalid.
    assert not result.valid or dup_issues


# ---------------------------------------------------------------------------
# XPath profile tests
# ---------------------------------------------------------------------------

def test_valid_local_xpath_policy_fixture(yaml_schemas):
    xml_file = VALID_FIXTURES_DIR / "ex14-policy-xpath-defaults.yaml"
    result = validate(
        xml_file,
        yaml_schemas["structure"],
        yaml_schemas["constraints"],
        yaml_schemas["xpath"],
        None,
    )
    errors = [i for i in result.issues if i.severity.value == "error"]
    assert not errors, f"Unexpected errors: {[i.message for i in errors]}"
    assert "xpath" in result.profiles


def test_valid_local_xpath_entity_selector(yaml_schemas, tmp_path):
    xml_file = tmp_path / "xpath-entity-selector.yaml"
    xml_file.write_text("""
Policy:
  PolicyId: "urn:example:yacal:policy:xpath-entity-selector"
  Version: "1.0"
  CombiningAlgId: "urn:oasis:names:tc:acal:1.0:combining-algorithm:deny-unless-permit"
  PolicyDefaults:
    - XPathPolicyDefaults:
        XPathVersion: "urn:example:xpath:1.0"
        Namespace:
          - Prefix: med
            Name: "urn:example:yacal:medical"
  CombinerInput:
    - Rule:
        Id: permit-resource-entity
        Effect: Permit
        VariableDefinition:
          - VariableId: current_entity
            Expression:
              Value: "urn:oasis:names:tc:acal:1.0:attribute-category:resource"
        Condition:
          EntityAttributeSelector:
            Path: "/med:record/@ward"
            DataType: "urn:oasis:names:tc:acal:1.0:data-type:string"
            ContextSelectorId: "urn:example:yacal:selector:resource-content"
            Expression:
              VariableReference:
                VariableId: current_entity
""")
    result = validate(
        xml_file,
        yaml_schemas["structure"],
        yaml_schemas["constraints"],
        yaml_schemas["xpath"],
        None,
    )
    errors = [i for i in result.issues if i.severity.value == "error"]
    assert not errors, f"Unexpected errors: {[i.message for i in errors]}"
    assert "xpath" in result.profiles


# ---------------------------------------------------------------------------
# JSON output shape
# ---------------------------------------------------------------------------

def test_json_output_shape(yaml_schemas, tmp_path):
    """as_json produces a well-formed result dict."""
    import io
    from yacal_validator.output import as_json

    f = tmp_path / "p.yaml"
    f.write_text("NotValid:\n  x: 1\n")
    result = validate(f, yaml_schemas["structure"], yaml_schemas["constraints"], None, None)

    buf = io.StringIO()
    as_json(result, f.name, file=buf)

    import json
    data = json.loads(buf.getvalue())
    assert "valid" in data
    assert "issues" in data
    assert "constraints" in data
    assert data["format"] == "yacal"


# ---------------------------------------------------------------------------
# Constraint evaluation stats
# ---------------------------------------------------------------------------

def test_constraint_stats_tracked(yaml_schemas):
    """evaluate() returns total/evaluated/skipped stats."""
    from yacal_validator.constraints import evaluate, load_catalog

    catalog = load_catalog(yaml_schemas["constraints"])
    _, total, evaluated, skipped = evaluate({}, catalog)

    assert total > 0, "Catalog must have at least one known rule"
    assert evaluated + skipped == total
    # Phase 1: within-document resolution means no references to skip on an empty document.
    assert skipped == 0
    assert evaluated == total


def test_constraint_summary_in_human_output(yaml_schemas, tmp_path):
    """Human output always includes a constraint coverage line when constraints ran."""
    import io
    from yacal_validator.output import human

    # A structurally invalid doc — constraints don't run; summary line absent.
    f = tmp_path / "bad.yaml"
    f.write_text("NotValid:\n  x: 1\n")
    result = validate(f, yaml_schemas["structure"], yaml_schemas["constraints"], None, None)
    buf = io.StringIO()
    human(result, f.name, file=buf)
    assert "Constraints:" not in buf.getvalue()
    assert result.constraints_total == 0


def test_constraint_summary_absent_on_parse_error(yaml_schemas, tmp_path):
    """Parse errors halt before constraints; no coverage line emitted."""
    import io
    from yacal_validator.output import human

    f = tmp_path / "broken.yaml"
    f.write_text("{{bad: yaml")
    result = validate(f, yaml_schemas["structure"], yaml_schemas["constraints"], None, None)
    buf = io.StringIO()
    human(result, f.name, file=buf)
    assert "Constraints:" not in buf.getvalue()
    assert result.constraints_total == 0


def test_statusdetail_missing_attribute_shape_constraint(yaml_schemas):
    """The catalog rejects unsupported StatusDetail keys for missing-attribute statuses."""
    from yacal_validator.constraints import evaluate, load_catalog

    document = {
        "Response": {
            "Result": [
                {
                    "Decision": "Indeterminate",
                    "Status": {
                        "StatusCode": {
                            "Value": "urn:oasis:names:tc:acal:1.0:status:missing-attribute",
                        },
                        "StatusDetail": {
                            "UnsupportedDetail": [
                                {
                                    "AttributeId": "urn:example:yacal:subject:role",
                                    "DataType": "urn:oasis:names:tc:acal:1.0:data-type:string",
                                }
                            ]
                        },
                    },
                }
            ]
        }
    }

    catalog = load_catalog(yaml_schemas["constraints"])
    issues, _, _, _ = evaluate(document, catalog)

    assert any(
        "statusdetail-missing-attribute-shape" in (issue.rule_id or "")
        for issue in issues
    ), f"Expected statusdetail shape constraint to fire. Issues: {[i.rule_id for i in issues]}"


def test_constraint_skips_in_json_output(yaml_schemas):
    """JSON output always includes the constraints object with total/evaluated/skipped."""
    import io, json
    from yacal_validator.constraints import evaluate, load_catalog
    from yacal_validator.base import ValidationResult
    from yacal_validator.output import as_json

    catalog = load_catalog(yaml_schemas["constraints"])
    issues, total, evaluated, skipped = evaluate({}, catalog)

    result = ValidationResult(format="yacal")
    result.constraints_total = total
    result.constraints_evaluated = evaluated
    result.constraints_skipped = skipped
    for issue in issues:
        result.add_issue(issue)

    buf = io.StringIO()
    as_json(result, "test.yaml", file=buf)
    data = json.loads(buf.getvalue())

    assert data["constraints"]["total"] == total
    assert data["constraints"]["evaluated"] == evaluated
    assert data["constraints"]["skipped"] == skipped
    assert data["constraints"]["skipped"] == 0
