from __future__ import annotations

import io
import os
import sys
import tempfile
from pathlib import Path

import click
from ruamel.yaml import YAML

from .converter import convert_file

_yaml_writer = YAML()
_yaml_writer.default_flow_style = False
_yaml_writer.width = 120


@click.command()
@click.argument("input_file", type=click.Path(exists=True, dir_okay=False))
@click.option("--output", "-o", default="-",
              help="Output file path (default: stdout).")
@click.option("--validate", is_flag=True,
              help="Run yacal-validator on the converted output (requires yacal-validator).")
def main(input_file: str, output: str, validate: bool) -> None:
    """Convert an XACML 3.0 or 4.0 policy to YACAL v1.0 YAML."""
    try:
        yacal = convert_file(input_file)
    except ValueError as exc:
        click.echo(f"error: {exc}", err=True)
        sys.exit(2)
    except Exception as exc:  # noqa: BLE001
        click.echo(f"error: {exc}", err=True)
        sys.exit(2)

    if output == "-":
        _yaml_writer.dump(yacal, sys.stdout)
    else:
        with open(output, "w", encoding="utf-8") as fh:
            _yaml_writer.dump(yacal, fh)

    if validate:
        _validate(yacal, output_path=output if output != "-" else None)


def _validate(yacal: dict, output_path: str | None = None) -> None:
    """Validate the converted YACAL dict using yacal-validator's internal API."""
    try:
        from yacal_validator.validator import validate as yv_validate  # type: ignore[import-not-found]
        from yacal_validator.schemas import SCHEMA_FILES, SchemaStore  # type: ignore[import-not-found]
        from yacal_validator.config import load as load_config  # type: ignore[import-not-found]
        from yacal_validator.output import human as yv_human  # type: ignore[import-not-found]
    except ImportError:
        click.echo(
            "warning: yacal-validator is not installed; skipping validation.\n"
            "  Install it with: pip install -e ../yacal-validator  (or pip install yacal-validator)",
            err=True,
        )
        return

    # yacal-validator's validate() takes a file path, not a dict.
    # Re-use the output file if one was written; otherwise use a temp file.
    tmp_path: Path | None = None
    if output_path:
        validate_path = Path(output_path)
    else:
        buf = io.StringIO()
        _yaml_writer.dump(yacal, buf)
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, encoding="utf-8"
        )
        tmp.write(buf.getvalue())
        tmp.close()
        tmp_path = Path(tmp.name)
        validate_path = tmp_path

    try:
        cfg = load_config()
        store = SchemaStore(source=cfg.schemas.source, branch=cfg.schemas.branch)
        try:
            result = yv_validate(
                validate_path,
                core_structure_path=store.resolve(SCHEMA_FILES["core_structure"]),
                core_constraints_path=store.resolve(SCHEMA_FILES["core_constraints"]),
                xpath_structure_path=store.try_resolve(SCHEMA_FILES["xpath_structure"]),
                jsonpath_structure_path=store.try_resolve(SCHEMA_FILES["jsonpath_structure"]),
            )
        except FileNotFoundError:
            click.echo(
                "warning: yacal-validator schemas not cached.\n"
                "  Fetch them first: yacal-validate --refresh-schemas <any-yacal-file>",
                err=True,
            )
            return

        yv_human(result, validate_path.name)

        if not result.valid:
            sys.exit(1)
        elif result.incomplete:
            sys.exit(2)

    finally:
        if tmp_path and tmp_path.exists():
            os.unlink(tmp_path)
