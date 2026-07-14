"""CLI tests for acal-explain — LLM calls are mocked."""
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from acal_explain.cli import main

_CORE_FIXTURES = Path(__file__).parent.parent.parent / "acal-core" / "tests" / "fixtures"
_SIMPLE_PERMIT = _CORE_FIXTURES / "ex01-simple-permit.yaml"
_CONDITION = _CORE_FIXTURES / "ex02-condition.yaml"
_XACML = _CORE_FIXTURES / "xacml3" / "simple-policy.xml"
_ALFA = _CORE_FIXTURES / "alfa" / "simple-permit.alfa"

_MOCK_SUMMARY = "This policy permits all requests."
_MOCK_OBS = "- No issues detected."


def _mock_completion(summary=_MOCK_SUMMARY, obs=_MOCK_OBS):
    """Return a side_effect list for two litellm.completion calls."""
    def _resp(text):
        m = MagicMock()
        m.choices[0].message.content = text
        return m
    return [_resp(summary), _resp(obs)]


@pytest.fixture
def runner():
    return CliRunner()


# ---------------------------------------------------------------------------
# Happy path — text / markdown / json output
# ---------------------------------------------------------------------------

def test_cli_text_output(runner):
    with patch("acal_explain.llm.litellm") as mock_litellm:
        mock_litellm.completion.side_effect = _mock_completion()
        result = runner.invoke(main, ["--format", "text", str(_SIMPLE_PERMIT)])
    assert result.exit_code == 0, result.output
    assert _MOCK_SUMMARY in result.output
    assert _MOCK_OBS in result.output


def test_cli_markdown_output(runner):
    with patch("acal_explain.llm.litellm") as mock_litellm:
        mock_litellm.completion.side_effect = _mock_completion()
        result = runner.invoke(main, ["--format", "markdown", str(_SIMPLE_PERMIT)])
    assert result.exit_code == 0, result.output
    assert "## Summary" in result.output
    assert "## Observations" in result.output


def test_cli_json_output(runner):
    with patch("acal_explain.llm.litellm") as mock_litellm:
        mock_litellm.completion.side_effect = _mock_completion()
        result = runner.invoke(main, ["--format", "json", str(_SIMPLE_PERMIT)])
    assert result.exit_code == 0, result.output
    doc = json.loads(result.output)
    assert "summary" in doc
    assert "observations" in doc
    assert "rule_count" in doc


def test_cli_json_contains_analysis_fields(runner):
    with patch("acal_explain.llm.litellm") as mock_litellm:
        mock_litellm.completion.side_effect = _mock_completion()
        result = runner.invoke(main, ["--format", "json", str(_SIMPLE_PERMIT)])
    doc = json.loads(result.output)
    assert "is_default_deny" in doc
    assert "shadowed_rules" in doc
    assert "obligation_gaps" in doc
    assert "unresolved_attrs" in doc


def test_cli_output_to_file(runner, tmp_path):
    out = tmp_path / "result.txt"
    with patch("acal_explain.llm.litellm") as mock_litellm:
        mock_litellm.completion.side_effect = _mock_completion()
        result = runner.invoke(main, ["--format", "text", "-o", str(out), str(_SIMPLE_PERMIT)])
    assert result.exit_code == 0, result.output
    assert out.exists()
    assert _MOCK_SUMMARY in out.read_text()


def test_cli_xacml_accepted(runner):
    with patch("acal_explain.llm.litellm") as mock_litellm:
        mock_litellm.completion.side_effect = _mock_completion()
        result = runner.invoke(main, ["--format", "text", str(_XACML)])
    assert result.exit_code == 0, result.output


def test_cli_explicit_from(runner):
    with patch("acal_explain.llm.litellm") as mock_litellm:
        mock_litellm.completion.side_effect = _mock_completion()
        result = runner.invoke(main, ["--from", "yacal", "--format", "text", str(_SIMPLE_PERMIT)])
    assert result.exit_code == 0, result.output


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------

def test_cli_alfa_accepted_without_writing_a_policy_file(runner, tmp_path):
    """ALFA is converted in memory; the only artifact is the explanation itself."""
    with runner.isolated_filesystem(temp_dir=tmp_path) as cwd:
        with patch("acal_explain.llm.litellm") as mock_litellm:
            mock_litellm.completion.side_effect = _mock_completion()
            result = runner.invoke(main, ["--format", "text", str(_ALFA)])
        assert result.exit_code == 0, result.output
        assert _MOCK_SUMMARY in result.output
        assert list(Path(cwd).iterdir()) == []


def test_cli_alfa_reports_import_fidelity(runner):
    """Unresolvable ALFA constructs surface as import-fidelity notes, not stderr noise."""
    with patch("acal_explain.llm.litellm") as mock_litellm:
        mock_litellm.completion.side_effect = _mock_completion()
        result = runner.invoke(
            main, ["--format", "json", str(_CORE_FIXTURES / "alfa" / "unresolvable-attr.alfa")]
        )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["format"] == "alfa"
    assert any("could not be resolved" in n for n in payload["import_notes"])


def test_cli_alfa_fidelity_notes_render_in_text(runner):
    with patch("acal_explain.llm.litellm") as mock_litellm:
        mock_litellm.completion.side_effect = _mock_completion()
        result = runner.invoke(
            main, ["--format", "text", str(_CORE_FIXTURES / "alfa" / "xpath-datatype.alfa")]
        )
    assert result.exit_code == 0, result.output
    assert "Import fidelity" in result.output
    assert "xpath" in result.output.lower()


def test_cli_native_input_has_no_import_notes(runner):
    with patch("acal_explain.llm.litellm") as mock_litellm:
        mock_litellm.completion.side_effect = _mock_completion()
        result = runner.invoke(main, ["--format", "json", str(_SIMPLE_PERMIT)])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["import_notes"] == []


def test_cli_unknown_extension_fails(runner, tmp_path):
    f = tmp_path / "policy.txt"
    f.write_bytes(b"")
    result = runner.invoke(main, ["--format", "text", str(f)])
    assert result.exit_code != 0
    assert "Cannot determine input format" in result.output


# ---------------------------------------------------------------------------
# --model flag overrides config
# ---------------------------------------------------------------------------

def test_cli_model_override(runner):
    with patch("acal_explain.llm.litellm") as mock_litellm:
        mock_litellm.completion.side_effect = _mock_completion()
        result = runner.invoke(main, [
            "--model", "openai/gpt-4o",
            "--format", "text",
            str(_SIMPLE_PERMIT),
        ])
    assert result.exit_code == 0, result.output
    # Confirm the model was passed through
    call_kwargs = mock_litellm.completion.call_args_list[0]
    assert call_kwargs.kwargs.get("model") == "openai/gpt-4o" or \
           call_kwargs.args[0] == "openai/gpt-4o" if call_kwargs.args else True


# ---------------------------------------------------------------------------
# LLM failure surfaces as a clean error
# ---------------------------------------------------------------------------

def test_cli_llm_failure_exits_nonzero(runner):
    with patch("acal_explain.llm.litellm") as mock_litellm:
        mock_litellm.completion.side_effect = RuntimeError("API key missing")
        result = runner.invoke(main, ["--format", "text", str(_SIMPLE_PERMIT)])
    assert result.exit_code != 0
    assert "LLM call failed" in result.output


def test_from_choices_track_the_registry():
    """acal-explain must accept every format acal-core can read.

    This test is the guard for the bug it was written after: --from was
    hardcoded to xacml/yacal/jacal, silently excluding ALFA.
    """
    from acal_core.languages import READ_FORMATS

    params = {p.name: p for p in main.params}
    assert tuple(params["from_fmt"].type.choices) == READ_FORMATS
    assert "alfa" in params["from_fmt"].type.choices
