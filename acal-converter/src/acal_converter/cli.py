import subprocess
import sys
from pathlib import Path

import click

from .readers import detect_format, load
from .writers import write


@click.command()
@click.argument("input_file", type=click.Path(exists=True, dir_okay=False))
@click.option(
    "--from", "from_fmt",
    type=click.Choice(["xacml", "yacal", "jacal"]),
    default=None,
    help="Input format. Auto-detected from file extension if omitted.",
)
@click.option(
    "--to", "to_fmt",
    type=click.Choice(["yacal", "jacal"]),
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
    "--validate",
    is_flag=True,
    default=False,
    help="Validate the output with the appropriate ACAL validator.",
)
def main(input_file, from_fmt, to_fmt, output, validate, strict, no_strict):
    if no_strict:
        strict = False
    """Convert ACAL policy documents between formats.

    Supports XACML 2.0–4.0, YACAL (YAML), and JACAL (JSON) as inputs.
    Outputs only YACAL or JACAL.

    Use --strict (recommended for security use cases) to turn any warning into
    a hard error. Use --no-strict to allow warnings for deprecated-but-harmless
    constructs (like IncludeInResult).
    """
    fmt = from_fmt or detect_format(input_file)
    if fmt is None:
        ext = Path(input_file).suffix or "(none)"
        raise click.UsageError(
            f"Cannot determine input format from extension {ext!r}. "
            f"Use --from [xacml|yacal|jacal] to specify."
        )

    try:
        data = load(input_file, fmt, strict=strict)
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
