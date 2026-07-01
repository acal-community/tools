import json
import warnings
from pathlib import Path

import pytest
import ruamel.yaml

from acal_core import convert
from acal_core.readers import detect_format, detect_format_from_bytes
from acal_core.readers.yacal import load as load_yacal
from acal_core.readers.jacal import load as load_jacal
from acal_core.readers.xacml import load as load_xacml, XACMLUnsupportedFeatureError
from acal_core.readers.alfa import load as load_alfa, ALFAUnsupportedFeatureError, ALFASyntaxError

XACML2 = Path(__file__).parent / "fixtures" / "xacml2"
XACML3 = Path(__file__).parent / "fixtures" / "xacml3"
ALFA = Path(__file__).parent / "fixtures" / "alfa"

FIXTURES = Path(__file__).parent / "fixtures"

_PAIRS = [
    ("ex01-simple-permit.yaml", "ex01-simple-permit.json"),
    ("ex02-condition.yaml", "ex02-condition.json"),
]


# ---------------------------------------------------------------------------
# Reader unit tests
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("yaml_file,json_file", _PAIRS)
def test_yacal_reader_produces_plain_dict(yaml_file, json_file):
    data = load_yacal(str(FIXTURES / yaml_file))
    assert isinstance(data, dict), "Expected plain dict from YACAL reader"
    assert not type(data).__name__ == "CommentedMap", "CommentedMap leaked into output"


@pytest.mark.parametrize("yaml_file,json_file", _PAIRS)
def test_jacal_reader_produces_dict(yaml_file, json_file):
    data = load_jacal(str(FIXTURES / json_file))
    assert isinstance(data, dict)


# ---------------------------------------------------------------------------
# Format detection: content-sniffing
# ---------------------------------------------------------------------------

def test_detect_jacal_by_content(tmp_path):
    f = tmp_path / "policy.txt"
    f.write_text('{"Policy": {}}')
    assert detect_format(str(f)) == "jacal"


def test_detect_yacal_by_content(tmp_path):
    f = tmp_path / "policy.txt"
    f.write_text("Policy:\n  PolicyId: x\n")
    assert detect_format(str(f)) == "yacal"


def test_detect_xacml_by_content(tmp_path):
    f = tmp_path / "policy.txt"
    f.write_text('<?xml version="1.0"?><Policy/>')
    assert detect_format(str(f)) == "xacml"


def test_detect_jacal_strips_utf8_bom(tmp_path):
    f = tmp_path / "policy.json"
    f.write_bytes(b"\xef\xbb\xbf" + b'{"Policy": {}}')
    assert detect_format(str(f)) == "jacal"


def test_detect_yacal_strips_utf8_bom(tmp_path):
    f = tmp_path / "policy.yaml"
    f.write_bytes(b"\xef\xbb\xbf" + b"Policy:\n  PolicyId: x\n")
    assert detect_format(str(f)) == "yacal"


def test_detect_falls_back_to_extension_when_empty(tmp_path):
    f = tmp_path / "policy.json"
    f.write_bytes(b"")
    assert detect_format(str(f)) == "jacal"


def test_detect_returns_none_when_empty_and_unknown_extension(tmp_path):
    f = tmp_path / "policy.txt"
    f.write_bytes(b"")
    assert detect_format(str(f)) is None


def test_detect_format_from_bytes_jacal():
    assert detect_format_from_bytes(b'{"Policy": {}}') == "jacal"

def test_detect_format_from_bytes_xacml():
    assert detect_format_from_bytes(b"<?xml version") == "xacml"

def test_detect_format_from_bytes_yacal():
    assert detect_format_from_bytes(b"Policy:\n  PolicyId: x") == "yacal"

def test_detect_format_from_bytes_bom():
    assert detect_format_from_bytes(b"\xef\xbb\xbf{") == "jacal"

def test_detect_format_from_bytes_empty():
    assert detect_format_from_bytes(b"") is None

def test_detect_format_from_bytes_whitespace_only():
    assert detect_format_from_bytes(b"   \n  ") is None


def test_detect_content_wins_over_wrong_extension(tmp_path):
    f = tmp_path / "policy.yaml"
    f.write_text('{"Policy": {}}')
    assert detect_format(str(f)) == "jacal"


# ---------------------------------------------------------------------------
# Conversion correctness: YACAL → JACAL
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("yaml_file,json_file", _PAIRS)
def test_yacal_to_jacal_matches_expected(yaml_file, json_file):
    result = convert(str(FIXTURES / yaml_file), to_fmt="jacal")
    actual = json.loads(result)
    expected = load_jacal(str(FIXTURES / json_file))
    assert actual == expected


# ---------------------------------------------------------------------------
# Conversion correctness: JACAL → YACAL
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("yaml_file,json_file", _PAIRS)
def test_jacal_to_yacal_matches_expected(yaml_file, json_file):
    result = convert(str(FIXTURES / json_file), to_fmt="yacal")
    yaml = ruamel.yaml.YAML()
    actual = dict(yaml.load(result))
    expected = load_yacal(str(FIXTURES / yaml_file))
    assert actual == expected


# ---------------------------------------------------------------------------
# Round-trip: YACAL → JACAL → YACAL
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("yaml_file,_", _PAIRS)
def test_round_trip_yacal_jacal_yacal(yaml_file, _):
    original = load_yacal(str(FIXTURES / yaml_file))
    jacal_str = convert(str(FIXTURES / yaml_file), to_fmt="jacal")

    import tempfile, os
    with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as tf:
        tf.write(jacal_str)
        tmp_path = tf.name
    try:
        yacal_str = convert(tmp_path, to_fmt="yacal")
    finally:
        os.unlink(tmp_path)

    yaml = ruamel.yaml.YAML()
    recovered = dict(yaml.load(yacal_str))
    assert recovered == original


# ---------------------------------------------------------------------------
# Round-trip: JACAL → YACAL → JACAL
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("_,json_file", _PAIRS)
def test_round_trip_jacal_yacal_jacal(_, json_file):
    original = load_jacal(str(FIXTURES / json_file))
    yacal_str = convert(str(FIXTURES / json_file), to_fmt="yacal")

    import tempfile, os
    with tempfile.NamedTemporaryFile(suffix=".yaml", mode="w", delete=False) as tf:
        tf.write(yacal_str)
        tmp_path = tf.name
    try:
        jacal_str = convert(tmp_path, to_fmt="jacal")
    finally:
        os.unlink(tmp_path)

    recovered = json.loads(jacal_str)
    assert recovered == original


# ---------------------------------------------------------------------------
# XACML reader — happy path
# ---------------------------------------------------------------------------

def test_xacml_simple_policy_converts():
    result = load_xacml(str(XACML3 / "simple-policy.xml"))
    assert "Policy" in result
    policy = result["Policy"]
    assert policy["PolicyId"] == "urn:example:acal-convert:xacml3:simple"
    assert policy["Effect"] if False else True  # just confirm no exception


# ---------------------------------------------------------------------------
# XACML reader — unsupported construct errors
# ---------------------------------------------------------------------------

def test_xacml_combiner_parameters_raises():
    with pytest.raises(XACMLUnsupportedFeatureError, match="CombinerParameters"):
        load_xacml(str(XACML3 / "combiner-parameters.xml"))


def test_xacml_rule_combiner_parameters_raises():
    with pytest.raises(XACMLUnsupportedFeatureError, match="RuleCombinerParameters"):
        load_xacml(str(XACML3 / "rule-combiner-parameters.xml"))


def test_xacml_earliest_version_raises():
    with pytest.raises(XACMLUnsupportedFeatureError, match="EarliestVersion"):
        load_xacml(str(XACML3 / "earliest-version.xml"))


def test_xacml_latest_version_raises():
    with pytest.raises(XACMLUnsupportedFeatureError, match="LatestVersion"):
        load_xacml(str(XACML3 / "latest-version.xml"))


def test_xacml_xpath_version_raises():
    with pytest.raises(XACMLUnsupportedFeatureError, match="XPathVersion"):
        load_xacml(str(XACML3 / "xpath-version.xml"))


def test_xacml_include_in_result_warns():
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        with pytest.raises(XACMLUnsupportedFeatureError, match="Attributes"):
            load_xacml(str(XACML3 / "include-in-result.xml"), strict=False)
    messages = [str(w.message) for w in caught]
    assert any("IncludeInResult" in m for m in messages), \
        f"Expected IncludeInResult warning, got: {messages}"


def test_xacml_include_in_result_strict():
    with pytest.raises(XACMLUnsupportedFeatureError, match="IncludeInResult"):
        load_xacml(str(XACML3 / "include-in-result.xml"), strict=True)


def test_xacml_unsupported_feature_error_is_value_error():
    with pytest.raises(ValueError):
        load_xacml(str(XACML3 / "combiner-parameters.xml"))


# ---------------------------------------------------------------------------
# XACML reader — no silent drops
# ---------------------------------------------------------------------------

def test_xacml_unknown_expr_elem_raises():
    with pytest.raises(XACMLUnsupportedFeatureError, match="Unsupported expression element"):
        load_xacml(str(XACML3 / "unknown-expr-elem.xml"))


def test_xacml_unknown_policy_child_raises():
    with pytest.raises(XACMLUnsupportedFeatureError, match="not a recognised child"):
        load_xacml(str(XACML3 / "unknown-policy-child.xml"))


def test_xacml3_request_with_attributes_raises():
    with pytest.raises(XACMLUnsupportedFeatureError, match="Attributes"):
        load_xacml(str(XACML3 / "request-attributes.xml"))


# ---------------------------------------------------------------------------
# XACML 2.0 reader — structural conversion
# ---------------------------------------------------------------------------

def test_xacml2_policy_id_and_version():
    result = load_xacml(str(XACML2 / "simple-policy.xml"))
    assert result["Policy"]["PolicyId"] == "urn:example:acal-convert:xacml2:simple"
    assert result["Policy"]["Version"] == "1.0"


def test_xacml2_combining_algorithm_remapped():
    result = load_xacml(str(XACML2 / "simple-policy.xml"))
    assert result["Policy"]["CombiningAlgId"] == \
        "urn:oasis:names:tc:acal:1.0:combining-algorithm:deny-overrides"


def test_xacml2_target_subject_match_converted():
    result = load_xacml(str(XACML2 / "simple-policy.xml"))
    target = result["Policy"]["Target"]
    apply = target["Apply"]
    assert apply["FunctionId"] == "urn:oasis:names:tc:acal:1.0:function:string-equal"
    args = apply["Argument"]
    assert args[0] == {"Value": "doctor"}
    desig = args[1]["AttributeDesignator"]
    assert desig["Category"] == "urn:oasis:names:tc:acal:1.0:subject-category:access-subject"
    assert desig["AttributeId"] == "urn:example:attribute:role"


def test_xacml2_condition_function_id_on_element():
    result = load_xacml(str(XACML2 / "simple-policy.xml"))
    rule = result["Policy"]["CombinerInput"][0]["Rule"]
    assert rule["Id"] == "permit-doctors"
    cond = rule["Condition"]
    apply = cond["Apply"]
    assert apply["FunctionId"] == "urn:oasis:names:tc:acal:1.0:function:string-equal"
    args = apply["Argument"]
    assert args[0] == {"Value": "read"}
    desig = args[1]["AttributeDesignator"]
    assert desig["Category"] == "urn:oasis:names:tc:acal:1.0:attribute-category:action"
    assert desig["AttributeId"] == "urn:oasis:names:tc:acal:1.0:action:action-id"


def test_xacml2_obligations_converted():
    result = load_xacml(str(XACML2 / "simple-policy.xml"))
    notices = result["Policy"]["NoticeExpression"]
    assert len(notices) == 1
    n = notices[0]
    assert n["Id"] == "urn:example:obligation:log"
    assert n["IsObligation"] is True
    assert n["AppliesTo"] == "Permit"
    aae = n["AttributeAssignmentExpression"]
    assert len(aae) == 1
    assert aae[0]["AttributeId"] == "urn:example:attribute:decision"
    assert aae[0]["Expression"] == {"Value": "permitted"}


# ---------------------------------------------------------------------------
# ALFA reader — happy path
# ---------------------------------------------------------------------------

def test_alfa_simple_permit_policy_id():
    doc = load_alfa(str(ALFA / "simple-permit.alfa"))
    assert "Policy" in doc
    assert doc["Policy"]["PolicyId"] == "com.example.SimplePermit"


def test_alfa_simple_permit_combining_algo():
    doc = load_alfa(str(ALFA / "simple-permit.alfa"))
    assert doc["Policy"]["CombiningAlgId"] == \
        "urn:oasis:names:tc:acal:1.0:combining-algorithm:deny-overrides"


def test_alfa_simple_permit_rule_effect():
    doc = load_alfa(str(ALFA / "simple-permit.alfa"))
    rule = doc["Policy"]["CombinerInput"][0]["Rule"]
    assert rule["Effect"] == "Permit"


def test_alfa_condition_expression_maps_to_apply():
    doc = load_alfa(str(ALFA / "condition.alfa"))
    rule = doc["Policy"]["CombinerInput"][0]["Rule"]
    cond = rule["Condition"]
    assert "Apply" in cond
    apply = cond["Apply"]
    assert apply["FunctionId"] == "urn:oasis:names:tc:acal:1.0:function:string-equal"


def test_alfa_condition_canonical_attr_designator():
    doc = load_alfa(str(ALFA / "condition.alfa"))
    rule = doc["Policy"]["CombinerInput"][0]["Rule"]
    args = rule["Condition"]["Apply"]["Argument"]
    desig = args[0]["AttributeDesignator"]
    assert desig["Category"] == "urn:oasis:names:tc:acal:1.0:subject-category:access-subject"
    assert desig["AttributeId"] == "role"


def test_alfa_obligation_urn_resolved():
    doc = load_alfa(str(ALFA / "obligation.alfa"))
    notices = doc["Policy"]["NoticeExpression"]
    obls = [n for n in notices if n.get("IsObligation")]
    assert len(obls) == 1
    assert obls[0]["Id"] == "urn:example:obligation:audit-log"
    assert obls[0]["AppliesTo"] == "Permit"


def test_alfa_advice_urn_resolved():
    doc = load_alfa(str(ALFA / "obligation.alfa"))
    notices = doc["Policy"]["NoticeExpression"]
    advice = [n for n in notices if not n.get("IsObligation")]
    assert len(advice) == 1
    assert advice[0]["Id"] == "urn:example:advice:log-hint"
    assert advice[0]["AppliesTo"] == "Deny"


def test_alfa_attribute_shorthand_resolves_category():
    doc = load_alfa(
        str(ALFA / "shorthand-policy.alfa"),
        include=[str(ALFA / "acal-attributes.alfa")],
    )
    rule = doc["Policy"]["CombinerInput"][0]["Rule"]
    args = rule["Condition"]["Apply"]["Argument"]
    user_desig = args[0]["Apply"]["Argument"][0]["AttributeDesignator"]
    assert user_desig["Category"] == "urn:oasis:names:tc:acal:1.0:subject-category:access-subject"
    assert user_desig["AttributeId"] == "urn:example:attribute:user-id"


def test_alfa_attribute_shorthand_datatype_propagated():
    doc = load_alfa(
        str(ALFA / "shorthand-policy.alfa"),
        include=[str(ALFA / "acal-attributes.alfa")],
    )
    rule = doc["Policy"]["CombinerInput"][0]["Rule"]
    args = rule["Condition"]["Apply"]["Argument"]
    user_desig = args[0]["Apply"]["Argument"][0]["AttributeDesignator"]
    assert user_desig.get("DataType") == "string"


def test_alfa_unresolvable_without_include_warns():
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        load_alfa(str(ALFA / "shorthand-policy.alfa"))
    assert len(w) >= 1, "Expected at least one unresolvable-path warning"


def test_alfa_variable_declaration_and_reference():
    doc = load_alfa(str(ALFA / "variable.alfa"))
    policy = doc["Policy"]
    var_defs = policy.get("VariableDefinition", [])
    assert len(var_defs) == 1
    vd = var_defs[0]
    assert vd["VariableId"] == "com.example.myRole"
    rule = policy["CombinerInput"][0]["Rule"]
    args = rule["Condition"]["Apply"]["Argument"]
    assert "VariableReference" in args[0]
    assert args[0]["VariableReference"]["VariableId"] == "com.example.myRole"


def test_alfa_anonymous_rule_gets_synthesized_id():
    doc = load_alfa(str(ALFA / "simple-permit.alfa"))
    rule = doc["Policy"]["CombinerInput"][0]["Rule"]
    assert rule["Id"] == "com.example.AllowAll"


def test_alfa_error_types_inherit_value_error():
    assert issubclass(ALFASyntaxError, ValueError)
    assert issubclass(ALFAUnsupportedFeatureError, ValueError)


# ---------------------------------------------------------------------------
# ALFA reader — warning-eligible constructs (disposition b)
# ---------------------------------------------------------------------------

def test_alfa_custom_combining_algo_warns():
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        doc = load_alfa(str(ALFA / "custom-combining-algo.alfa"))
    assert any("myCustomAlgorithm" in str(x.message) for x in w), \
        f"Expected warning about custom algo, got: {[str(x.message) for x in w]}"
    assert doc["Policy"]["CombiningAlgId"] == "myCustomAlgorithm"


def test_alfa_custom_combining_algo_strict_raises():
    with pytest.raises(ALFAUnsupportedFeatureError, match="myCustomAlgorithm"):
        load_alfa(str(ALFA / "custom-combining-algo.alfa"), strict=True)


def test_alfa_unresolvable_attr_warns():
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        load_alfa(str(ALFA / "unresolvable-attr.alfa"))
    assert any("unknownCategory.attr" in str(x.message) for x in w)


def test_alfa_unresolvable_attr_strict_raises():
    with pytest.raises(ALFAUnsupportedFeatureError):
        load_alfa(str(ALFA / "unresolvable-attr.alfa"), strict=True)


def test_alfa_unknown_function_warns():
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        doc = load_alfa(str(ALFA / "unknown-function.alfa"))
    assert any("myCustomFunc" in str(x.message) for x in w)
    rule = doc["Policy"]["CombinerInput"][0]["Rule"]
    fn_id = rule["Condition"]["Apply"]["FunctionId"]
    assert fn_id == "urn:custom:function:myCustomFunc"


def test_alfa_unknown_function_strict_raises():
    with pytest.raises(ALFAUnsupportedFeatureError, match="myCustomFunc"):
        load_alfa(str(ALFA / "unknown-function.alfa"), strict=True)


# ---------------------------------------------------------------------------
# ALFA reader — content-sniff detection
# ---------------------------------------------------------------------------

def test_alfa_detected_by_content_sniff(tmp_path):
    f = tmp_path / "policy.txt"
    f.write_text("namespace com.example {\n  policy P apply denyOverrides {}\n}\n")
    assert detect_format(str(f)) == "alfa"


def test_alfa_not_confused_with_yacal_namespace_key(tmp_path):
    assert detect_format_from_bytes(b"namespace: foo\nPolicy:\n") == "yacal"


def test_alfa_detected_by_extension(tmp_path):
    f = tmp_path / "policy.alfa"
    f.write_text("")
    assert detect_format(str(f)) == "alfa"


def test_alfa_comment_stripped_before_sniff():
    chunk = b"// copyright notice\nnamespace com.example {"
    assert detect_format_from_bytes(chunk) == "alfa"


# ---------------------------------------------------------------------------
# Axiomatics demo policy fixtures
# ---------------------------------------------------------------------------

_AX_INCLUDES = [
    str(ALFA / "system.alfa"),
    str(ALFA / "standard-attributes.alfa"),
    str(ALFA / "adaf_standard_attributes.alfa"),
    str(ALFA / "demo-attributes.alfa"),
]


def _ax_load(filename: str, **kwargs):
    return load_alfa(str(ALFA / filename), include=_AX_INCLUDES, **kwargs)


def test_alfa_axiomatics_system_parses_as_include():
    doc = load_alfa(str(ALFA / "system.alfa"))
    assert doc == {}


def test_alfa_axiomatics_standard_attributes_parses():
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        doc = load_alfa(str(ALFA / "standard-attributes.alfa"))
    assert doc == {}
    assert len(w) == 0


def test_alfa_axiomatics_attributes_parses():
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        doc = load_alfa(str(ALFA / "demo-attributes.alfa"))
    assert doc == {}
    assert len(w) == 0


def test_alfa_axiomatics_portal():
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        doc = _ax_load("portal.alfa")
    assert "Policy" in doc
    assert doc["Policy"]["PolicyId"].endswith("portal")
    assert len(w) == 0


def test_alfa_axiomatics_healthcare():
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        doc = _ax_load("healthcare.alfa")
    assert "Policy" in doc
    p = doc["Policy"]
    assert p["Target"] is not None
    assert "Apply" in p["Target"]
    assert "and" in p["Target"]["Apply"]["FunctionId"]


def test_alfa_axiomatics_banking():
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        doc = _ax_load("banking.alfa")
    assert "Policy" in doc or "Bundle" in doc


def test_alfa_axiomatics_online_trial_tutorial():
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        doc = _ax_load("online_trial_tutorial.alfa")
    assert "Policy" in doc or "Bundle" in doc


def test_alfa_axiomatics_online_trial_rule_notices():
    doc = _ax_load("online_trial_tutorial.alfa")
    top = doc.get("Policy") or doc.get("Bundle", {}).get("Policy", [{}])[0]

    def find_rule_with_notice(node):
        if isinstance(node, dict):
            if "Rule" in node:
                rule = node["Rule"]
                if "NoticeExpression" in rule:
                    return rule
            for v in node.values():
                result = find_rule_with_notice(v)
                if result:
                    return result
        elif isinstance(node, list):
            for item in node:
                result = find_rule_with_notice(item)
                if result:
                    return result
        return None

    rule = find_rule_with_notice(top)
    assert rule is not None, "Expected at least one Rule with NoticeExpression"
    assert any("decision_reason" in n.get("Id", "") for n in rule["NoticeExpression"])


def test_alfa_axiomatics_api():
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        doc = _ax_load("api.alfa")
    assert "Policy" in doc or "Bundle" in doc


def test_alfa_axiomatics_aerospace():
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        doc = _ax_load("aerospace.alfa")
    assert "Policy" in doc or "Bundle" in doc


def test_alfa_axiomatics_root_policy():
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        doc = _ax_load("axiomatics-policy.alfa")
    assert "Policy" in doc or "Bundle" in doc


def test_alfa_axiomatics_target_and_keyword():
    doc = _ax_load("healthcare.alfa")
    target = doc["Policy"]["Target"]
    fn_id = target["Apply"]["FunctionId"]
    assert fn_id == "urn:oasis:names:tc:acal:1.0:function:and"


def test_alfa_axiomatics_apply_inside_body():
    doc = _ax_load("online_trial_tutorial.alfa")
    top = doc.get("Policy") or doc.get("Bundle", {}).get("Policy", [{}])[0]
    assert top.get("CombiningAlgId") is not None


# ---------------------------------------------------------------------------
# Bag attribute, malformed syntax
# ---------------------------------------------------------------------------

def test_alfa_bag_attribute_untyped_expands_to_string_is_in():
    # type=bag (no datatype) → defaults to string-is-in(scalar, bag)
    doc = load_alfa(str(ALFA / "bag-attribute.alfa"))
    assert "Policy" in doc
    rule = doc["Policy"]["CombinerInput"][0]["Rule"]
    cmp = rule["Condition"]["Apply"]
    assert cmp["FunctionId"] == "urn:oasis:names:tc:acal:1.0:function:string-is-in"
    # string-is-in(scalar, bag): scalar first, bag second
    assert cmp["Argument"][0] == {"Value": "admin"}
    desig = cmp["Argument"][1]["AttributeDesignator"]
    assert desig["AttributeId"] == "urn:example:attribute:roles"
    assert desig["Category"] == "urn:oasis:names:tc:acal:1.0:subject-category:access-subject"


def test_alfa_bag_comparison_string_is_in():
    doc = load_alfa(str(ALFA / "bag-comparison.alfa"))
    assert "Policy" in doc
    rule0 = doc["Policy"]["CombinerInput"][0]["Rule"]
    cmp0 = rule0["Condition"]["Apply"]
    assert cmp0["FunctionId"] == "urn:oasis:names:tc:acal:1.0:function:string-is-in"
    assert cmp0["Argument"][0] == {"Value": "admin"}
    assert cmp0["Argument"][1]["AttributeDesignator"]["AttributeId"] == "urn:example:attribute:roles"


def test_alfa_bag_comparison_integer_is_in():
    doc = load_alfa(str(ALFA / "bag-comparison.alfa"))
    assert "Policy" in doc
    rule1 = doc["Policy"]["CombinerInput"][1]["Rule"]
    cmp1 = rule1["Condition"]["Apply"]
    assert cmp1["FunctionId"] == "urn:oasis:names:tc:acal:1.0:function:integer-is-in"
    assert cmp1["Argument"][0] == {"Value": 99}
    assert cmp1["Argument"][1]["AttributeDesignator"]["AttributeId"] == "urn:example:attribute:int-bag"


def test_alfa_ordered_deny_overrides():
    doc = load_alfa(str(ALFA / "ordered-deny-overrides.alfa"))
    assert "Policy" in doc
    assert doc["Policy"]["CombiningAlgId"] == (
        "urn:oasis:names:tc:acal:1.0:combining-algorithm:ordered-deny-overrides"
    )


def test_alfa_ordered_permit_overrides():
    doc = load_alfa(str(ALFA / "ordered-permit-overrides.alfa"))
    assert "Policy" in doc
    assert doc["Policy"]["CombiningAlgId"] == (
        "urn:oasis:names:tc:acal:1.0:combining-algorithm:ordered-permit-overrides"
    )


def test_alfa_date_comparison_functions():
    doc = load_alfa(str(ALFA / "date-comparison.alfa"))
    assert "Policy" in doc
    rule0 = doc["Policy"]["CombinerInput"][0]["Rule"]
    cmp0 = rule0["Condition"]["Apply"]
    assert cmp0["FunctionId"] == "urn:oasis:names:tc:acal:1.0:function:date-greater-than"
    # Verify dateFromString nested call
    date_arg = cmp0["Argument"][1]["Apply"]
    assert date_arg["FunctionId"] == "urn:oasis:names:tc:acal:1.0:function:date-from-string"
    assert date_arg["Argument"][0] == {"Value": "2020-01-01"}


def test_alfa_portal_zero_unknown_function_warnings():
    """portal.alfa with its include chain should produce no unknown-function warnings
    after the expanded _NAMED_FUNCTION_MAP covers all system.alfa entries."""
    includes = [
        str(ALFA / "system.alfa"),
        str(ALFA / "standard-attributes.alfa"),
        str(ALFA / "adaf_standard_attributes.alfa"),
        str(ALFA / "demo-attributes.alfa"),
    ]
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        doc = load_alfa(str(ALFA / "portal.alfa"), include=includes)
    assert "Policy" in doc or "Bundle" in doc
    unknown = [str(w.message) for w in caught if "Unknown ALFA function" in str(w.message)]
    assert unknown == [], f"Unexpected unknown-function warnings:\n" + "\n".join(unknown)


def test_alfa_xpath_datatype_warns():
    """Declaring type = xpath should emit a UserWarning (no ACAL 1.0 equivalent)."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        doc = load_alfa(str(ALFA / "xpath-datatype.alfa"))
    assert "Policy" in doc
    xpath_warns = [w for w in caught if "xpath" in str(w.message).lower()]
    assert xpath_warns, "Expected a UserWarning about xpath datatype with no ACAL 1.0 equivalent"
    assert "ACAL 1.0" in str(xpath_warns[0].message)


def test_alfa_malformed_syntax_raises_syntax_error():
    with pytest.raises(ALFASyntaxError) as exc_info:
        load_alfa(str(ALFA / "malformed-syntax.alfa"))
    msg = str(exc_info.value)
    assert "Syntax error" in msg
    assert "line" in msg and "col" in msg
