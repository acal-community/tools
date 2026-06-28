"""jacal-validate CLI entrypoint."""
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
@click.option(
    "--include", "include_paths",
    multiple=True,
    type=click.Path(exists=True, path_type=Path),
    metavar="FILE",
    help=(
        "Additional JACAL file to load definitions from (repeatable). "
        "Required when the primary document contains PolicyReference or "
        "SharedVariableReference elements whose definitions live in external files."
    ),
)
@click.version_option(__version__, prog_name="jacal-validate")
def main(
    policy_file: Path,
    output_json: bool,
    refresh_schemas: bool,
    include_paths: tuple[Path, ...],
) -> None:
    """Validate a JACAL v1.0 (JSON) policy document.

    \b
    Accepts .json files. Profiles (XPath, JSONPath) are
    auto-detected from the document content.

    \b
    Exit codes:
      0  valid and fully evaluated
      1  validation failed (one or more errors)
      2  incomplete (cross-file references could not be resolved — use --include)
         or tool error (bad input, network failure, missing schemas)

    \b
    Configuration (optional):
      jacal-validator.toml  in the current directory, or
      ~/.config/jacal-validator/config.toml

      [schemas]
      source = "https://github.com/oasis-tcs/xacml-spec"
      branch = "main"
    """
    if policy_file.suffix.lower() in (".yaml", ".yml"):
        click.echo(
            f"error: '{policy_file.name}' appears to be a YAML file. "
            "This tool validates JACAL (JSON) policies. "
            "Use yacal-validate for YACAL (YAML) policies.",
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
            include_paths=list(include_paths) if include_paths else None,
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

    if not result.valid:
        sys.exit(1)
    elif result.incomplete:
        sys.exit(2)
    else:
        sys.exit(0)
