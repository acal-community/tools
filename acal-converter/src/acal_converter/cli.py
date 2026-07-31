import subprocess
import sys
from pathlib import Path

import click

from acal_core import metadata as acal_metadata
from acal_core.languages import READ_FORMATS, WRITE_FORMATS
from acal_core.readers import detect_format, load, load_with_report
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
        "Emit MustBePresent: true on attribute designators the reader synthesizes (rather than "
        "reads from the source), so a rule whose attribute the PDP does not supply is denied "
        "instead of skipped. A deliberate deviation from the source language's fail-open runtime "
        "semantics; the default reproduces the source faithfully."
    ),
)
@click.option(
    "--provenance",
    is_flag=True,
    default=False,
    help=(
        "Stamp source language, tool version and the conversion report into a Metadata "
        "property on the output document, so fidelity information survives the pipeline "
        "instead of living only in this process. Metadata is non-normative and a PDP must "
        "ignore it, but the spec change is proposed, not adopted "
        "(acal-community/tools#12) — the published schemas do not admit it, so --validate "
        "checks against the proposal in docs/proposals/metadata/ instead."
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
def main(input_file, from_fmt, to_fmt, output, validate, strict, no_strict, include_files, debug,
         fail_closed, provenance):
    if no_strict:
        strict = False
    """Convert ACAL policy documents between formats.

    Reads a policy in any supported source language (see the --from choices, which are
    derived from the acal-core language registry) and outputs YACAL or JACAL.

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

    if provenance and validate:
        # Say this up front rather than let a PASS be read as conformance. The document
        # is checked against the published schemas *plus* the metadata proposal; the
        # validator repeats the caveat on its own result line.
        click.echo(
            "Note: --provenance emits a Metadata property, which the published ACAL "
            "schemas do not admit — the spec change is proposed, not adopted "
            "(acal-community/tools#12). --validate will apply the proposal in "
            "docs/proposals/metadata/, so a PASS here is not a conformance result.",
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
        if provenance:
            data, report = load_with_report(
                input_file, fmt, strict=strict, include=include_files,
                debug=debug, fail_closed=fail_closed,
            )
            acal_metadata.stamp_provenance(data, report, tool=_tool_identity())
            # load_with_report captures the fidelity warnings instead of letting them
            # reach stderr. Re-emit them, so --provenance adds a record to the document
            # rather than trading the record you already had for one you have to go read.
            for note in report.notes:
                click.echo(f"Warning: {note.message}", err=True)
        else:
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
            sys.exit(_validate(output, to_fmt, provenance=provenance))


def _tool_identity() -> str:
    """Name and version of this converter, for the provenance `tool` attribute."""
    try:
        from importlib.metadata import version
        return f"acal-convert/{version('acal-converter')}"
    except Exception:
        # An editable checkout without installed metadata should still convert.
        return "acal-convert"


def _validate(path: str, fmt: str, provenance: bool = False) -> int:
    cmd = "yacal-validate" if fmt == "yacal" else "jacal-validate"
    argv = [cmd, path]
    if provenance:
        # We wrote the Metadata property, so we are the ones who have to say which
        # unadopted proposal admits it. Passing the name rather than a blanket
        # "be lenient" flag keeps the validator's result honest about what it applied.
        argv += ["--proposal", "metadata"]
    result = subprocess.run(argv, capture_output=False)
    return result.returncode
