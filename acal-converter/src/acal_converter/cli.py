import subprocess
import sys
from pathlib import Path

import click

from acal_core.languages import READ_FORMATS, WRITE_FORMATS
from acal_core.readers import detect_format, load
from acal_core.writers import write


@click.command()
@click.argument("input_file", type=click.Path(exists=True, dir_okay=False))
@click.option(
    "--from", "from_fmt",
    type=click.Choice(READ_FORMATS),
    default=None,
    help="Input format. Auto-detected from file extension if omitted.",
)
@click.option(
    "--to", "to_fmt",
    type=click.Choice(WRITE_FORMATS),
    required=True,
    help="Output format.",
)
@click.option(
    "-o", "--output",
    default="-",
    help="Output file path. Defaults to stdout.",
)
@click.option(
    "--strict",
    is_flag=True,
    default=False,
    help="Fail on any non-semantic construct (e.g. IncludeInResult). Use --no-strict to allow warnings.",
)
@click.option(
    "--no-strict",
    is_flag=True,
    default=False,
    help="Allow warnings for non-semantic deprecated constructs (default).",
)
@click.option(
    "--include",
    "include_files",
    multiple=True,
    type=click.Path(exists=True, dir_okay=False),
    help=(
        "Additional Axiomatics PDP 7.x ALFA dialect file to load for symbol resolution "
        "(attribute registries, standard namespaces). May be repeated. Only meaningful "
        "with --from alfa. These files are not converted — they are used only to resolve "
        "attribute shorthand names and obligation/advice URNs in the main policy file."
    ),
)
@click.option(
    "--fail-closed",
    is_flag=True,
    default=False,
    help=(
        "Emit MustBePresent: true on synthesized attribute designators (Cedar, ALFA), so a "
        "rule whose attribute the PDP does not supply DENIES rather than being skipped. This "
        "is a deliberate deviation from those languages' fail-open runtime semantics; the "
        "default reproduces the source faithfully."
    ),
)
@click.option(
    "--validate",
    is_flag=True,
    default=False,
    help="Validate the output with the appropriate ACAL validator.",
)
@click.option(
    "--debug",
    is_flag=True,
    default=False,
    help=(
        "For ALFA input: dump the collected symbol table (attributes, obligations, advice) "
        "to stderr before converting. Useful for debugging shorthand resolution."
    ),
)
def main(input_file, from_fmt, to_fmt, output, validate, strict, no_strict, include_files, debug, fail_closed):
    if no_strict:
        strict = False
    """Convert ACAL policy documents between formats.

    Supports XACML 2.0–4.0, YACAL (YAML), JACAL (JSON), and Axiomatics PDP 7.x ALFA dialect as inputs.
    Outputs only YACAL or JACAL.

    Use --strict (recommended for security use cases) to turn any warning into
    a hard error. Use --no-strict to allow warnings for deprecated-but-harmless
    constructs (like IncludeInResult).

    For ALFA input, use --include to supply attribute-registry files (e.g.
    standard-attributes.alfa, attributes.alfa) that define the attribute
    shorthand names referenced in the policy file.
    """
    fmt = from_fmt or detect_format(input_file)

    if include_files and fmt and fmt != "alfa":
        click.echo(
            f"Warning: --include is only meaningful for Axiomatics PDP 7.x ALFA dialect input (got --from {fmt!r}). "
            "The included files will be ignored.",
            err=True,
        )

    if fmt is None:
        ext = Path(input_file).suffix or "(none)"
        choices = "|".join(READ_FORMATS)
        raise click.UsageError(
            f"Cannot determine input format from extension {ext!r}. "
            f"Use --from [{choices}] to specify."
        )

    try:
        data = load(input_file, fmt, strict=strict, include=include_files, debug=debug, fail_closed=fail_closed)
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc

    try:
        if output == "-":
            write(data, to_fmt, sys.stdout)
        else:
            with open(output, "w", encoding="utf-8") as fh:
                write(data, to_fmt, fh)
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc

    if validate:
        if output == "-":
            click.echo(
                "Warning: --validate requires an output file (-o). Skipping validation.",
                err=True,
            )
        else:
            sys.exit(_validate(output, to_fmt))


def _validate(path: str, fmt: str) -> int:
    cmd = "yacal-validate" if fmt == "yacal" else "jacal-validate"
    result = subprocess.run([cmd, path], capture_output=False)
    return result.returncode
