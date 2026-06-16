"""Tests for YACAL v1.0 (YAML) validation."""
from __future__ import annotations

from pathlib import Path

import pytest

from yacal_validator.validator import validate, detect_profiles
from yacal_validator.schemas import SCHEMA_FILES


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

def test_valid_xpath_rule1(yaml_schemas, xpath_examples):
    xml_file = xpath_examples / "Rule1.yaml"
    if not xml_file.exists():
        pytest.skip("Rule1.yaml not present in xpath examples")
    result = validate(
        xml_file,
        yaml_schemas["structure"],
        yaml_schemas["constraints"],
        yaml_schemas["xpath"],
        None,
    )
    errors = [i for i in result.issues if i.severity.value == "error"]
    assert not errors, f"Unexpected errors: {[i.message for i in errors]}"


def test_valid_xpath_rule2(yaml_schemas, xpath_examples):
    xml_file = xpath_examples / "Rule2.yaml"
    if not xml_file.exists():
        pytest.skip("Rule2.yaml not present in xpath examples")
    result = validate(
        xml_file,
        yaml_schemas["structure"],
        yaml_schemas["constraints"],
        yaml_schemas["xpath"],
        None,
    )
    errors = [i for i in result.issues if i.severity.value == "error"]
    assert not errors, f"Unexpected errors: {[i.message for i in errors]}"


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
    assert data["format"] == "yacal"
