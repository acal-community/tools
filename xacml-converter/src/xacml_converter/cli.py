import sys

import click
from ruamel.yaml import YAML

from .converter import convert_file


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

    yaml = YAML()
    yaml.default_flow_style = False
    yaml.width = 120

    if output == "-":
        yaml.dump(yacal, sys.stdout)
    else:
        with open(output, "w", encoding="utf-8") as fh:
            yaml.dump(yacal, fh)

    if validate:
        _validate(yacal)


def _validate(yacal: dict) -> None:
    try:
        from yacal_validator import validate_dict  # type: ignore[import-not-found]
    except ImportError:
        click.echo(
            "warning: yacal-validator is not installed; skipping validation.\n"
            "  Install it with: pip install yacal-validator",
            err=True,
        )
        return

    issues = validate_dict(yacal)
    if issues:
        for issue in issues:
            click.echo(f"validation: {issue}", err=True)
        sys.exit(1)
    click.echo("validation: OK", err=True)
