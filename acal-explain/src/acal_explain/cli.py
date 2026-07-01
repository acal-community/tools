"""CLI entrypoint for acal-explain."""
from __future__ import annotations

import sys
from pathlib import Path

import click

from acal_core.readers import detect_format, load

from .analyzer import analyze
from .config import Config
from .llm import explain
from .output import render

_ACAL_FORMATS = frozenset({"xacml", "yacal", "jacal"})


@click.command()
@click.argument("input_file", type=click.Path(exists=True, dir_okay=False))
@click.option(
    "--from", "from_fmt",
    type=click.Choice(["xacml", "yacal", "jacal"]),
    default=None,
    help=(
        "Input format. Auto-detected from file content/extension if omitted. "
        "Only XACML, YACAL, and JACAL are accepted — to explain an ALFA policy, "
        "convert it first with acal-convert."
    ),
)
@click.option(
    "--format", "output_fmt",
    type=click.Choice(["text", "markdown", "json"]),
    default=None,
    help="Output format. Defaults to the value in config.toml or 'text'.",
)
@click.option(
    "--output", "-o",
    default="-",
    help="Output file path. Defaults to stdout.",
)
@click.option(
    "--model",
    default=None,
    help=(
        "LLM model string in litellm format (e.g. 'anthropic/claude-sonnet-4-6', "
        "'ollama/llama3'). Overrides config.toml and ACAL_EXPLAIN_MODEL env var."
    ),
)
def main(input_file: str, from_fmt: str | None, output_fmt: str | None, output: str, model: str | None) -> None:
    """Explain what an ACAL policy does in plain English.

    Reads an XACML, YACAL, or JACAL policy file, analyses its structure, then
    uses an LLM to produce a plain-English explanation and a set of observations
    about completeness and potential issues.

    Configure the LLM provider via ~/.config/acal-explain/config.toml or the
    ACAL_EXPLAIN_MODEL / ACAL_EXPLAIN_API_KEY environment variables.
    """
    cfg = Config()
    if model:
        cfg.model = model

    fmt = from_fmt or detect_format(input_file)
    if fmt is None:
        ext = Path(input_file).suffix or "(none)"
        raise click.UsageError(
            f"Cannot determine input format from extension {ext!r}. "
            "Use --from [xacml|yacal|jacal] to specify."
        )
    if fmt not in _ACAL_FORMATS:
        raise click.UsageError(
            f"Format {fmt!r} is not accepted by acal-explain. "
            "Only XACML, YACAL, and JACAL inputs are supported. "
            "To explain an ALFA policy, convert it first: "
            "acal-convert <file> --to yacal | acal-explain /dev/stdin --from yacal"
        )

    try:
        doc = load(input_file, fmt)
    except Exception as exc:
        raise click.ClickException(f"Failed to load policy: {exc}") from exc

    analysis = analyze(doc, fmt)
    resolved_fmt = output_fmt or cfg.default_format

    try:
        summary, observations = explain(doc, analysis, cfg)
    except Exception as exc:
        raise click.ClickException(f"LLM call failed: {exc}") from exc

    if output == "-":
        render(summary, observations, analysis, resolved_fmt, sys.stdout)
    else:
        with open(output, "w", encoding="utf-8") as fh:
            render(summary, observations, analysis, resolved_fmt, fh)
