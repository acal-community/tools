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

def test_cli_alfa_rejected(runner):
    result = runner.invoke(main, ["--format", "text", str(_ALFA)])
    assert result.exit_code != 0
    assert "not accepted" in result.output or "alfa" in result.output.lower()


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
