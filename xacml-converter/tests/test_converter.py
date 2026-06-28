"""
Tests for the XACML → YACAL converter.

Each fixture test converts an XML input and compares the result (as a Python
dict) against an expected YAML file parsed by ruamel.yaml.  Dict comparison
is used throughout to avoid sensitivity to YAML serialisation formatting.
"""

from __future__ import annotations

import pathlib
import pytest
from ruamel.yaml import YAML

from xacml_converter import convert_file
from xacml_converter._identifiers import remap_identifier, optional_datatype
from xacml_converter.converter import XACML3_NS, XACML4_NS

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
XACML3 = FIXTURES / "xacml3"
XACML4 = FIXTURES / "xacml4"
EXPECTED = FIXTURES / "expected"

_yaml = YAML()


def _load_yaml(path: pathlib.Path) -> dict:
    with open(path, encoding="utf-8") as fh:
        return _yaml.load(fh)


# ---------------------------------------------------------------------------
# Identifier remapping unit tests
# ---------------------------------------------------------------------------


class TestRemapIdentifier:
    def test_xsd_string(self):
        assert remap_identifier("http://www.w3.org/2001/XMLSchema#string") == \
            "urn:oasis:names:tc:acal:1.0:data-type:string"

    def test_xsd_integer(self):
        assert remap_identifier("http://www.w3.org/2001/XMLSchema#integer") == \
            "urn:oasis:names:tc:acal:1.0:data-type:integer"

    def test_xsd_boolean(self):
        assert remap_identifier("http://www.w3.org/2001/XMLSchema#boolean") == \
            "urn:oasis:names:tc:acal:1.0:data-type:boolean"

    def test_xacml_function_v1(self):
        assert remap_identifier("urn:oasis:names:tc:xacml:1.0:function:string-equal") == \
            "urn:oasis:names:tc:acal:1.0:function:string-equal"

    def test_xacml_function_v2(self):
        assert remap_identifier("urn:oasis:names:tc:xacml:2.0:function:anyURI-equal") == \
            "urn:oasis:names:tc:acal:1.0:function:anyURI-equal"

    def test_xacml_function_v3(self):
        assert remap_identifier("urn:oasis:names:tc:xacml:3.0:function:any-of") == \
            "urn:oasis:names:tc:acal:1.0:function:any-of"

    def test_rule_combining_algorithm_v3(self):
        assert remap_identifier(
            "urn:oasis:names:tc:xacml:3.0:rule-combining-algorithm:deny-unless-permit"
        ) == "urn:oasis:names:tc:acal:1.0:combining-algorithm:deny-unless-permit"

    def test_policy_combining_algorithm_v3(self):
        assert remap_identifier(
            "urn:oasis:names:tc:xacml:3.0:policy-combining-algorithm:deny-overrides"
        ) == "urn:oasis:names:tc:acal:1.0:combining-algorithm:deny-overrides"

    def test_rule_combining_algorithm_v1(self):
        assert remap_identifier(
            "urn:oasis:names:tc:xacml:1.0:rule-combining-algorithm:first-applicable"
        ) == "urn:oasis:names:tc:acal:1.0:combining-algorithm:first-applicable"

    def test_subject_category(self):
        assert remap_identifier(
            "urn:oasis:names:tc:xacml:1.0:subject-category:access-subject"
        ) == "urn:oasis:names:tc:acal:1.0:subject-category:access-subject"

    def test_attribute_category(self):
        assert remap_identifier(
            "urn:oasis:names:tc:xacml:3.0:attribute-category:action"
        ) == "urn:oasis:names:tc:acal:1.0:attribute-category:action"

    def test_acal_passthrough(self):
        uri = "urn:oasis:names:tc:acal:1.0:function:and"
        assert remap_identifier(uri) == uri

    def test_custom_urn_passthrough(self):
        uri = "urn:example:custom:attribute:role"
        assert remap_identifier(uri) == uri

    def test_none_passthrough(self):
        assert remap_identifier(None) is None


class TestOptionalDatatype:
    def test_string_returns_none(self):
        assert optional_datatype("http://www.w3.org/2001/XMLSchema#string") is None

    def test_integer_returns_remapped(self):
        assert optional_datatype("http://www.w3.org/2001/XMLSchema#integer") == \
            "urn:oasis:names:tc:acal:1.0:data-type:integer"

    def test_none_returns_none(self):
        assert optional_datatype(None) is None


# ---------------------------------------------------------------------------
# Namespace constants sanity check
# ---------------------------------------------------------------------------


def test_namespace_constants():
    assert "xacml:3.0" in XACML3_NS
    assert "xacml:4.0" in XACML4_NS


# ---------------------------------------------------------------------------
# Unknown namespace raises ValueError
# ---------------------------------------------------------------------------


def test_unknown_namespace(tmp_path):
    bad = tmp_path / "bad.xml"
    bad.write_text(
        '<?xml version="1.0"?>'
        '<Policy xmlns="urn:unknown:ns" PolicyId="x" Version="1.0" CombiningAlgId="y"/>'
    )
    with pytest.raises(ValueError, match="Unrecognised XACML namespace"):
        convert_file(str(bad))


# ---------------------------------------------------------------------------
# Fixture-driven conversion tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("xml_path,expected_path", [
    (XACML3 / "ex01-simple-policy.xml",     EXPECTED / "xacml3-ex01.yaml"),
    (XACML3 / "ex02-policy-with-notices.xml", EXPECTED / "xacml3-ex02.yaml"),
    (XACML3 / "ex03-policyset.xml",          EXPECTED / "xacml3-ex03.yaml"),
    (XACML4 / "ex04-simple-policy.xml",      EXPECTED / "xacml4-ex04.yaml"),
])
def test_fixture(xml_path, expected_path):
    result = convert_file(str(xml_path))
    expected = _load_yaml(expected_path)
    assert result == expected


# ---------------------------------------------------------------------------
# Spot-check specific converter behaviours
# ---------------------------------------------------------------------------


class TestXACML3SimplePolicy:
    """Detailed checks on ex01 conversion output."""

    @pytest.fixture(autouse=True)
    def _convert(self):
        self.result = convert_file(str(XACML3 / "ex01-simple-policy.xml"))
        self.policy = self.result["Policy"]

    def test_root_key(self):
        assert "Policy" in self.result

    def test_policy_id(self):
        assert self.policy["PolicyId"] == "urn:example:policy:simple-permit"

    def test_combining_alg_remapped(self):
        assert self.policy["CombiningAlgId"] == \
            "urn:oasis:names:tc:acal:1.0:combining-algorithm:deny-unless-permit"

    def test_target_is_apply(self):
        assert "Apply" in self.policy["Target"]

    def test_target_function_remapped(self):
        fn = self.policy["Target"]["Apply"]["FunctionId"]
        assert fn == "urn:oasis:names:tc:acal:1.0:function:string-equal"

    def test_target_value_arg(self):
        arg0 = self.policy["Target"]["Apply"]["Argument"][0]
        assert arg0 == {"Value": "read"}

    def test_target_attr_desig_category_remapped(self):
        ad = self.policy["Target"]["Apply"]["Argument"][1]["AttributeDesignator"]
        assert ad["Category"] == "urn:oasis:names:tc:acal:1.0:attribute-category:action"

    def test_target_datatype_omitted_for_string(self):
        ad = self.policy["Target"]["Apply"]["Argument"][1]["AttributeDesignator"]
        assert "DataType" not in ad

    def test_target_must_be_present_false_omitted(self):
        ad = self.policy["Target"]["Apply"]["Argument"][1]["AttributeDesignator"]
        assert "MustBePresent" not in ad

    def test_rule_id_renamed(self):
        rule = self.policy["CombinerInput"][0]["Rule"]
        assert rule["Id"] == "rule-doctor-permit"
        assert "RuleId" not in rule

    def test_rule_effect(self):
        rule = self.policy["CombinerInput"][0]["Rule"]
        assert rule["Effect"] == "Permit"

    def test_rule_condition_remapped(self):
        cond = self.policy["CombinerInput"][0]["Rule"]["Condition"]
        fn = cond["Apply"]["FunctionId"]
        assert fn == "urn:oasis:names:tc:acal:1.0:function:string-is-in"

    def test_rule_condition_must_be_present_true(self):
        ad = self.policy["CombinerInput"][0]["Rule"]["Condition"]["Apply"]["Argument"][1]
        assert ad["AttributeDesignator"]["MustBePresent"] is True


class TestXACML3PolicyWithNotices:
    """Verify Obligation/Advice → NoticeExpression conversion."""

    @pytest.fixture(autouse=True)
    def _convert(self):
        self.result = convert_file(str(XACML3 / "ex02-policy-with-notices.xml"))
        self.policy = self.result["Policy"]

    def test_no_target_when_empty(self):
        assert "Target" not in self.policy

    def test_obligation_becomes_notice_with_is_obligation(self):
        notices = self.policy["NoticeExpression"]
        obl = next(n for n in notices if n["Id"] == "urn:example:obligation:log-access")
        assert obl["IsObligation"] is True

    def test_obligation_applies_to_from_fulfill_on(self):
        notices = self.policy["NoticeExpression"]
        obl = next(n for n in notices if n["Id"] == "urn:example:obligation:log-access")
        assert obl["AppliesTo"] == "Permit"

    def test_obligation_aae_expression(self):
        notices = self.policy["NoticeExpression"]
        obl = next(n for n in notices if n["Id"] == "urn:example:obligation:log-access")
        aae = obl["AttributeAssignmentExpression"][0]
        assert aae["Expression"] == {"Value": "Access granted"}

    def test_advice_becomes_notice_without_is_obligation(self):
        notices = self.policy["NoticeExpression"]
        adv = next(n for n in notices if n["Id"] == "urn:example:advice:audit")
        assert "IsObligation" not in adv

    def test_advice_applies_to(self):
        notices = self.policy["NoticeExpression"]
        adv = next(n for n in notices if n["Id"] == "urn:example:advice:audit")
        assert adv["AppliesTo"] == "Permit"


class TestXACML3PolicySet:
    """Verify PolicySet → Policy with nested CombinerInput."""

    @pytest.fixture(autouse=True)
    def _convert(self):
        self.result = convert_file(str(XACML3 / "ex03-policyset.xml"))
        self.policy = self.result["Policy"]

    def test_policyset_becomes_policy(self):
        assert self.result.get("Policy") is not None
        assert "PolicySet" not in self.result

    def test_policyset_id_remapped(self):
        assert self.policy["PolicyId"] == "urn:example:policyset:medical"

    def test_policy_combining_alg_remapped(self):
        assert self.policy["CombiningAlgId"] == \
            "urn:oasis:names:tc:acal:1.0:combining-algorithm:deny-unless-permit"

    def test_empty_target_omitted(self):
        assert "Target" not in self.policy

    def test_two_nested_policies(self):
        assert len(self.policy["CombinerInput"]) == 2
        assert all("Policy" in item for item in self.policy["CombinerInput"])

    def test_nested_policy_read_has_target(self):
        read_policy = self.policy["CombinerInput"][0]["Policy"]
        assert "Target" in read_policy

    def test_nested_policy_write_has_nested_and(self):
        write_policy = self.policy["CombinerInput"][1]["Policy"]
        rule = write_policy["CombinerInput"][0]["Rule"]
        fn = rule["Condition"]["Apply"]["FunctionId"]
        assert fn == "urn:oasis:names:tc:acal:1.0:function:and"


class TestXACML4SimplePolicy:
    """Verify XACML 4.0 pass-through and NoticeExpression handling."""

    @pytest.fixture(autouse=True)
    def _convert(self):
        self.result = convert_file(str(XACML4 / "ex04-simple-policy.xml"))
        self.policy = self.result["Policy"]

    def test_root_key(self):
        assert "Policy" in self.result

    def test_identifiers_unchanged(self):
        fn = self.policy["CombinerInput"][0]["Rule"]["Condition"]["Apply"]["FunctionId"]
        assert fn == "urn:oasis:names:tc:acal:1.0:function:string-is-in"

    def test_target_direct_apply(self):
        assert "Apply" in self.policy["Target"]

    def test_notice_expression_preserved(self):
        notice = self.policy["NoticeExpression"][0]
        assert notice["Id"] == "urn:example:obligation:log"
        assert notice["IsObligation"] is True
        assert notice["AppliesTo"] == "Permit"

    def test_notice_aae_expression(self):
        aae = self.policy["NoticeExpression"][0]["AttributeAssignmentExpression"][0]
        assert aae["Expression"] == {"Value": "Access granted"}
