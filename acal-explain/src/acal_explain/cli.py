"""CLI entrypoint for acal-explain."""
from __future__ import annotations

import sys
from pathlib import Path

import click

from acal_core.languages import DIALECTS, READ_FORMATS
from acal_core.readers import detect_format, load_with_report

from .analyzer import analyze
from .config import Config
from .llm import explain
from .output import render


@click.command()
@click.argument("input_file", type=click.Path(exists=True, dir_okay=False))
@click.option(
    "--from", "from_fmt",
    type=click.Choice(READ_FORMATS),
    default=None,
    help=(
        "Input format. Auto-detected from file content/extension if omitted. "
        "Non-native inputs are converted in memory — no policy file is written."
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
    help="Output file path for the explanation. Defaults to stdout.",
)
@click.option(
    "--include",
    "include_files",
    multiple=True,
    type=click.Path(exists=True, dir_okay=False),
    help=(
        "Additional ALFA file to load for symbol resolution (attribute registries, "
        "standard namespaces). May be repeated. Only meaningful with ALFA input."
    ),
)
@click.option(
    "--strict",
    is_flag=True,
    default=False,
    help="Fail on any construct the source language cannot express faithfully in ACAL.",
)
@click.option(
    "--fail-closed",
    is_flag=True,
    default=False,
    help=(
        "Harden synthesized designators (Cedar, ALFA) to MustBePresent: true, so a rule whose "
        "attribute is missing denies rather than being skipped. Deviates from the source's "
        "fail-open semantics; off by default."
    ),
)
@click.option(
    "--check-export",
    "export_targets",
    multiple=True,
    type=click.Choice([d.id for d in DIALECTS if not d.native]),
    help=(
        "Also report which ACAL features in this policy the named dialect could NOT express. "
        "May be repeated. Defaults to the policy's own source dialect, which answers whether "
        "it could round-trip back to where it came from."
    ),
)
@click.option(
    "--model",
    default=None,
    help=(
        "LLM model string in litellm format (e.g. 'anthropic/claude-sonnet-4-6', "
        "'ollama/llama3'). Overrides config.toml and ACAL_EXPLAIN_MODEL env var."
    ),
)
def main(
    input_file: str,
    from_fmt: str | None,
    output_fmt: str | None,
    output: str,
    include_files: tuple[str, ...],
    strict: bool,
    fail_closed: bool,
    export_targets: tuple[str, ...],
    model: str | None,
) -> None:
    """Explain what an ACAL policy does in plain English.

    Reads a policy in any supported source language, analyses its structure, then
    uses an LLM to produce a plain-English explanation and a set of observations
    about completeness and potential issues.

    Non-native inputs (XACML, ALFA) are converted in memory. No policy document is
    ever written — the only output is the explanation itself. Anything the source
    language could not express faithfully in ACAL is reported as an import-fidelity
    note alongside the explanation.

    Configure the LLM provider via ~/.config/acal-explain/config.toml or the
    ACAL_EXPLAIN_MODEL / ACAL_EXPLAIN_API_KEY environment variables.
    """
    cfg = Config()
    if model:
        cfg.model = model

    fmt = from_fmt or detect_format(input_file)
    if fmt is None:
        ext = Path(input_file).suffix or "(none)"
        choices = "|".join(READ_FORMATS)
        raise click.UsageError(
            f"Cannot determine input format from extension {ext!r}. "
            f"Use --from [{choices}] to specify."
        )

    if include_files and fmt != "alfa":
        click.echo(
            f"Warning: --include is only meaningful for ALFA input (got {fmt!r}). "
            "The included files will be ignored.",
            err=True,
        )

    try:
        doc, report = load_with_report(
            input_file, fmt, strict=strict, include=include_files, fail_closed=fail_closed
        )
    except Exception as exc:
        raise click.ClickException(f"Failed to load policy: {exc}") from exc

    # With no explicit target, ask the round-trip question: can this policy go back to the
    # language it came from? Native input has no gaps by construction, so we skip it.
    targets = export_targets
    if not targets and report.source_dialect:
        from acal_core.languages import get_dialect
        if not get_dialect(report.source_dialect).native:
            targets = (report.source_dialect,)

    analysis = analyze(doc, fmt, report=report, export_targets=targets)
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
