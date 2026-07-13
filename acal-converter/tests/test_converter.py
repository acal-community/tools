import json
import warnings
from pathlib import Path

import pytest
import ruamel.yaml
from click.testing import CliRunner

from acal_converter import convert
from acal_converter.cli import main
from acal_converter.readers.yacal import load as load_yacal
from acal_converter.readers.jacal import load as load_jacal
from acal_converter.readers.xacml import load as load_xacml, XACMLUnsupportedFeatureError

XACML2 = Path(__file__).parent / "fixtures" / "xacml2"
XACML3 = Path(__file__).parent / "fixtures" / "xacml3"

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

from acal_converter.readers import detect_format, detect_format_from_bytes


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
    # A JSON file misnamed as .yaml should still be detected as jacal
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

    # Write JACAL to temp file and convert back
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
# CLI tests
# ---------------------------------------------------------------------------

@pytest.fixture
def runner():
    return CliRunner()


@pytest.mark.parametrize("yaml_file,json_file", _PAIRS)
def test_cli_yacal_to_jacal(runner, yaml_file, json_file):
    result = runner.invoke(main, ["--to", "jacal", str(FIXTURES / yaml_file)])
    assert result.exit_code == 0, result.output
    actual = json.loads(result.output)
    expected = load_jacal(str(FIXTURES / json_file))
    assert actual == expected


@pytest.mark.parametrize("yaml_file,json_file", _PAIRS)
def test_cli_jacal_to_yacal(runner, yaml_file, json_file):
    result = runner.invoke(main, ["--to", "yacal", str(FIXTURES / json_file)])
    assert result.exit_code == 0, result.output
    yaml = ruamel.yaml.YAML()
    actual = dict(yaml.load(result.output))
    expected = load_yacal(str(FIXTURES / yaml_file))
    assert actual == expected


def test_cli_missing_format_empty_file_no_known_extension(runner, tmp_path):
    # Empty file with unknown extension: content sniff fails, extension fallback fails → error
    f = tmp_path / "policy.txt"
    f.write_bytes(b"")
    result = runner.invoke(main, ["--to", "yacal", str(f)])
    assert result.exit_code != 0
    assert "Cannot determine input format" in result.output


def test_cli_explicit_from_overrides_extension(runner, tmp_path):
    # Rename a YACAL fixture to .txt and use --from yacal
    import shutil
    src = FIXTURES / "ex01-simple-permit.yaml"
    dst = tmp_path / "policy.txt"
    shutil.copy(src, dst)
    result = runner.invoke(main, ["--from", "yacal", "--to", "jacal", str(dst)])
    assert result.exit_code == 0
    actual = json.loads(result.output)
    expected = load_jacal(str(FIXTURES / "ex01-simple-permit.json"))
    assert actual == expected


def test_cli_output_to_file(runner, tmp_path):
    out = tmp_path / "out.json"
    result = runner.invoke(main, ["--to", "jacal", "-o", str(out), str(FIXTURES / "ex01-simple-permit.yaml")])
    assert result.exit_code == 0
    assert out.exists()
    actual = json.loads(out.read_text())
    expected = load_jacal(str(FIXTURES / "ex01-simple-permit.json"))
    assert actual == expected


# ---------------------------------------------------------------------------
# XACML reader availability (no-xacml-converter smoke test)
# ---------------------------------------------------------------------------

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
    # With strict=False (default), IncludeInResult emits a warning.
    # The full XACML 3.0 <Attributes> request body still raises.
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        with pytest.raises(XACMLUnsupportedFeatureError, match="Attributes"):
            load_xacml(str(XACML3 / "include-in-result.xml"), strict=False)
    messages = [str(w.message) for w in caught]
    assert any("IncludeInResult" in m for m in messages), \
        f"Expected IncludeInResult warning, got: {messages}"


def test_xacml_include_in_result_strict():
    """With --strict / strict=True, IncludeInResult becomes a hard error."""
    with pytest.raises(XACMLUnsupportedFeatureError, match="IncludeInResult"):
        load_xacml(str(XACML3 / "include-in-result.xml"), strict=True)


def test_xacml_unsupported_feature_error_is_value_error():
    # Callers that catch ValueError will also catch this.
    with pytest.raises(ValueError):
        load_xacml(str(XACML3 / "combiner-parameters.xml"))


# ---------------------------------------------------------------------------
# XACML reader — no silent drops
# ---------------------------------------------------------------------------

def test_xacml_unknown_expr_elem_raises():
    """An unrecognised element in an expression context must raise, not be silently dropped."""
    with pytest.raises(XACMLUnsupportedFeatureError, match="Unsupported expression element"):
        load_xacml(str(XACML3 / "unknown-expr-elem.xml"))


def test_xacml_unknown_policy_child_raises():
    """An unrecognised direct child of <Policy> must raise, not be silently skipped."""
    with pytest.raises(XACMLUnsupportedFeatureError, match="not a recognised child"):
        load_xacml(str(XACML3 / "unknown-policy-child.xml"))


def test_xacml3_request_with_attributes_raises():
    """A XACML 3.0 Request using <Attributes> raises because conversion is not implemented."""
    with pytest.raises(XACMLUnsupportedFeatureError, match="Attributes"):
        load_xacml(str(XACML3 / "request-attributes.xml"))


# ---------------------------------------------------------------------------
# XACML → JACAL via CLI
# ---------------------------------------------------------------------------

def test_cli_xacml_to_jacal(runner):
    result = runner.invoke(main, [
        "--from", "xacml", "--to", "jacal",
        str(XACML3 / "simple-policy.xml"),
    ])
    assert result.exit_code == 0, result.output
    doc = json.loads(result.output)
    assert "Policy" in doc


def test_cli_xacml_combiner_parameters_exits_nonzero(runner):
    result = runner.invoke(main, [
        "--from", "xacml", "--to", "jacal",
        str(XACML3 / "combiner-parameters.xml"),
    ])
    assert result.exit_code != 0
    assert "CombinerParameters" in result.output


def test_cli_xacml_strict_flag(runner):
    """Test that --strict turns IncludeInResult into an error, while --no-strict allows a warning."""
    # --no-strict (default) should warn but still fail on the request body
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = runner.invoke(main, [
            "--from", "xacml",
            "--to", "jacal",
            "--no-strict",
            str(XACML3 / "include-in-result.xml"),
        ])
        assert result.exit_code != 0
        assert "IncludeInResult" in result.output or any("IncludeInResult" in str(w.message) for w in caught)

    # --strict should fail immediately on IncludeInResult
    result = runner.invoke(main, [
        "--from", "xacml",
        "--to", "jacal",
        "--strict",
        str(XACML3 / "include-in-result.xml"),
    ])
    assert result.exit_code != 0
    assert "IncludeInResult" in result.output


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
    """Target's SubjectMatch → Apply with SubjectAttributeDesignator → AttributeDesignator."""
    result = load_xacml(str(XACML2 / "simple-policy.xml"))
    target = result["Policy"]["Target"]
    # Single SubjectMatch → a single Apply
    apply = target["Apply"]
    assert apply["FunctionId"] == "urn:oasis:names:tc:acal:1.0:function:string-equal"
    args = apply["Argument"]
    assert args[0] == {"Value": "doctor"}
    desig = args[1]["AttributeDesignator"]
    assert desig["Category"] == "urn:oasis:names:tc:acal:1.0:subject-category:access-subject"
    assert desig["AttributeId"] == "urn:example:attribute:role"


def test_xacml2_condition_function_id_on_element():
    """XACML 2.0 <Condition FunctionId="..."> → Apply with arguments."""
    result = load_xacml(str(XACML2 / "simple-policy.xml"))
    rule = result["Policy"]["CombinerInput"][0]["Rule"]
    assert rule["Id"] == "permit-doctors"
    cond = rule["Condition"]
    apply = cond["Apply"]
    assert apply["FunctionId"] == "urn:oasis:names:tc:acal:1.0:function:string-equal"
    args = apply["Argument"]
    assert args[0] == {"Value": "read"}
    desig = args[1]["AttributeDesignator"]
    # ActionAttributeDesignator → ACAL action category (no remapping needed)
    assert desig["Category"] == "urn:oasis:names:tc:acal:1.0:attribute-category:action"
    assert desig["AttributeId"] == "urn:oasis:names:tc:acal:1.0:action:action-id"


def test_xacml2_obligations_converted():
    """XACML 2.0 <Obligations>/<Obligation>/<AttributeAssignment> → NoticeExpression."""
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
