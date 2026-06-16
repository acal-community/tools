"""yacal-validate CLI entrypoint."""
from __future__ import annotations

import sys
from pathlib import Path

import click

from . import __version__
from .config import load as load_config
from .output import as_json, human
from .schemas import SCHEMA_FILES, SchemaStore
from .validator import validate


@click.command(context_settings={"help_option_names": ["-h", "--help"]})
@click.argument("policy_file", metavar="FILE", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--json", "output_json",
    is_flag=True, default=False,
    help="Emit results as JSON instead of human-readable text.",
)
@click.option(
    "--refresh-schemas",
    is_flag=True, default=False,
    help="Re-fetch schema files from the configured source before validating.",
)
@click.version_option(__version__, prog_name="yacal-validate")
def main(
    policy_file: Path,
    output_json: bool,
    refresh_schemas: bool,
) -> None:
    """Validate a YACAL v1.0 (YAML) policy document.

    \b
    Accepts .yaml and .yml files. Profiles (XPath, JSONPath) are
    auto-detected from the document content.

    \b
    Exit codes:
      0  valid
      1  validation failed (one or more errors)
      2  tool error (bad input, network failure, missing schemas)

    \b
    Configuration (optional):
      yacal-validator.toml  in the current directory, or
      ~/.config/yacal-validator/config.toml

      [schemas]
      source = "https://github.com/oasis-tcs/xacml-spec"
      branch = "main"
    """
    if policy_file.suffix.lower() == ".json":
        click.echo(
            f"error: '{policy_file.name}' appears to be a JSON file. "
            "This tool validates YACAL (YAML) policies. "
            "Use jacal-validate for JACAL (JSON) policies.",
            err=True,
        )
        sys.exit(2)

    cfg = load_config()
    store = SchemaStore(
        source=cfg.schemas.source,
        branch=cfg.schemas.branch,
        refresh=refresh_schemas,
    )

    try:
        result = validate(
            policy_file,
            core_structure_path=store.resolve(SCHEMA_FILES["core_structure"]),
            core_constraints_path=store.resolve(SCHEMA_FILES["core_constraints"]),
            xpath_structure_path=store.try_resolve(SCHEMA_FILES["xpath_structure"]),
            jsonpath_structure_path=store.try_resolve(SCHEMA_FILES["jsonpath_structure"]),
        )
    except FileNotFoundError as exc:
        click.echo(
            f"error: {exc}\n"
            "Schemas not cached. Run with --refresh-schemas to fetch them.",
            err=True,
        )
        sys.exit(2)
    except Exception as exc:
        click.echo(f"error: {exc}", err=True)
        sys.exit(2)

    if output_json:
        as_json(result, policy_file.name)
    else:
        human(result, policy_file.name)

    sys.exit(0 if result.valid else 1)
