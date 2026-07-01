"""CLI integration tests for acal-converter.

Reader/writer unit tests and format-detection tests live in acal-core/tests/test_core.py.
This file tests only the CLI plumbing: argument handling, --strict/--no-strict, --include,
--debug, --output, and end-to-end conversion via the CLI entrypoint.
"""
import json
import warnings
from pathlib import Path

import pytest
import ruamel.yaml
from click.testing import CliRunner

from acal_converter.cli import main
from acal_core.readers.yacal import load as load_yacal
from acal_core.readers.jacal import load as load_jacal

# Fixtures live in acal-core (canonical fixture set; acal-converter is a thin wrapper)
_TOOLS_DIR = Path(__file__).parent.parent.parent
FIXTURES = _TOOLS_DIR / "acal-core" / "tests" / "fixtures"
XACML3 = FIXTURES / "xacml3"
ALFA = FIXTURES / "alfa"

_PAIRS = [
    ("ex01-simple-permit.yaml", "ex01-simple-permit.json"),
    ("ex02-condition.yaml", "ex02-condition.json"),
]


@pytest.fixture
def runner():
    return CliRunner()


# ---------------------------------------------------------------------------
# Basic format conversion via CLI
# ---------------------------------------------------------------------------

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
    f = tmp_path / "policy.txt"
    f.write_bytes(b"")
    result = runner.invoke(main, ["--to", "yacal", str(f)])
    assert result.exit_code != 0
    assert "Cannot determine input format" in result.output


def test_cli_explicit_from_overrides_extension(runner, tmp_path):
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

    result = runner.invoke(main, [
        "--from", "xacml",
        "--to", "jacal",
        "--strict",
        str(XACML3 / "include-in-result.xml"),
    ])
    assert result.exit_code != 0
    assert "IncludeInResult" in result.output


# ---------------------------------------------------------------------------
# ALFA → YACAL/JACAL via CLI
# ---------------------------------------------------------------------------

def test_cli_alfa_to_yacal(runner):
    result = runner.invoke(main, [
        "--from", "alfa", "--to", "yacal",
        str(ALFA / "simple-permit.alfa"),
    ])
    assert result.exit_code == 0, result.output
    yaml = ruamel.yaml.YAML()
    doc = dict(yaml.load(result.output))
    assert "Policy" in doc
    assert doc["Policy"]["PolicyId"] == "com.example.SimplePermit"


def test_cli_alfa_to_jacal(runner):
    result = runner.invoke(main, [
        "--from", "alfa", "--to", "jacal",
        str(ALFA / "condition.alfa"),
    ])
    assert result.exit_code == 0, result.output
    doc = json.loads(result.output)
    assert "Policy" in doc


def test_cli_alfa_strict_warns_exit_nonzero(runner):
    result = runner.invoke(main, [
        "--from", "alfa", "--to", "yacal",
        "--strict",
        str(ALFA / "custom-combining-algo.alfa"),
    ])
    assert result.exit_code != 0
    assert "myCustomAlgorithm" in result.output


def test_cli_alfa_no_strict_succeeds_with_warning(runner):
    with warnings.catch_warnings(record=True):
        warnings.simplefilter("always")
        result = runner.invoke(main, [
            "--from", "alfa", "--to", "yacal",
            "--no-strict",
            str(ALFA / "custom-combining-algo.alfa"),
        ])
    assert result.exit_code == 0, result.output


def test_cli_alfa_include_resolves_shorthands(runner):
    result = runner.invoke(main, [
        "--from", "alfa", "--to", "yacal",
        "--include", str(ALFA / "acal-attributes.alfa"),
        str(ALFA / "shorthand-policy.alfa"),
    ])
    assert result.exit_code == 0, result.output
    yaml = ruamel.yaml.YAML()
    doc = dict(yaml.load(result.output))
    rule = doc["Policy"]["CombinerInput"][0]["Rule"]
    args = rule["Condition"]["Apply"]["Argument"]
    user_desig = args[0]["Apply"]["Argument"][0]["AttributeDesignator"]
    assert user_desig["Category"] == "urn:oasis:names:tc:acal:1.0:subject-category:access-subject"
    assert user_desig["AttributeId"] == "urn:example:attribute:user-id"


def test_cli_alfa_include_multiple_files(runner):
    result = runner.invoke(main, [
        "--from", "alfa", "--to", "jacal",
        "--include", str(ALFA / "acal-attributes.alfa"),
        "--include", str(ALFA / "acal-attributes.alfa"),
        str(ALFA / "shorthand-policy.alfa"),
    ])
    assert result.exit_code == 0, result.output
    doc = json.loads(result.output)
    assert "Policy" in doc


def test_cli_alfa_import_stmt_does_not_error(runner):
    result = runner.invoke(main, [
        "--from", "alfa", "--to", "yacal",
        "--include", str(ALFA / "acal-attributes.alfa"),
        str(ALFA / "shorthand-policy.alfa"),
    ])
    assert result.exit_code == 0, result.output


_AX_INCLUDES = [
    str(ALFA / "system.alfa"),
    str(ALFA / "standard-attributes.alfa"),
    str(ALFA / "adaf_standard_attributes.alfa"),
    str(ALFA / "demo-attributes.alfa"),
]


def test_cli_alfa_axiomatics_portal(runner):
    result = runner.invoke(main, [
        "--from", "alfa", "--to", "jacal",
        *[arg for f in _AX_INCLUDES for arg in ("--include", f)],
        str(ALFA / "portal.alfa"),
    ])
    assert result.exit_code == 0, result.output
    doc = json.loads(result.output)
    assert "Policy" in doc


# ---------------------------------------------------------------------------
# --include warning for non-ALFA formats
# ---------------------------------------------------------------------------

def test_cli_include_warns_for_non_alfa(runner, tmp_path):
    yacal_file = tmp_path / "policy.yaml"
    yacal_file.write_text(
        "Policy:\n  PolicyId: test\n  CombinerInput: []\n"
    )
    result = runner.invoke(main, [
        "--from", "yacal", "--to", "jacal",
        "--include", str(ALFA / "acal-attributes.alfa"),
        str(yacal_file),
    ])
    assert "--include is only meaningful for ALFA" in result.output


# ---------------------------------------------------------------------------
# --debug symbol table dump
# ---------------------------------------------------------------------------

def test_cli_debug_dumps_symbol_table(runner):
    result = runner.invoke(main, [
        "--from", "alfa", "--to", "jacal",
        "--debug",
        "--include", str(ALFA / "acal-attributes.alfa"),
        str(ALFA / "shorthand-policy.alfa"),
    ])
    assert result.exit_code == 0, result.output
    assert "ALFA symbol table" in result.output
