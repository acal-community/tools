"""Named schema proposals — unadopted changes, applied only when asked for.

A proposal is a directory under ``docs/proposals/`` holding the schema fragments for one
proposed change to ACAL, in every serialization it touches. ``--proposal <name>`` loads
that directory's fragments and merges them into the schemas before validation.

The point is that the file the TC reviews and the file the validator applies are the same
file. A validator that hardcoded a proposed shape in Python would drift from the written
proposal the first time either moved, and the drift would be invisible: the demonstration
would still pass.

This is deliberately *not* folded into `_patch_core_schema_shape_bugs`. That function
works around defects in the published schemas — shapes the TC would agree are wrong — and
it runs unconditionally because a validator that cannot parse the schema is useless. A
proposal is the opposite case: the published schema is behaving exactly as intended, and
we are asking it to say something new. Applying one silently would make the validator lie
about what ACAL admits.

Every result records which proposals were applied, so a passing run under ``--proposal``
never reads as a conformance result.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from ruamel.yaml import YAML

#: Fragment filename per serialization. The YACAL validator reads the YAML fragment; the
#: JACAL validator reads the JSON one. They describe the same change in each schema
#: language's own house style rather than one being generated from the other.
STRUCTURE_FRAGMENT = "yaml.fragment.yaml"
CONSTRAINTS_FRAGMENT = "constraints.fragment.yaml"

_yaml = YAML(typ="safe")


class ProposalError(ValueError):
    """A named proposal could not be found or could not be applied."""


def proposals_dir() -> Path:
    """Locate ``docs/proposals/``.

    Checked in order: ``$ACAL_PROPOSALS_DIR``, the repository this package is a
    checkout of, then the current directory. There is no packaged copy on purpose —
    a fragment vendored into the wheel would be a second copy of the proposal, which is
    the one thing this module exists to prevent.
    """
    env = os.environ.get("ACAL_PROPOSALS_DIR")
    if env:
        return Path(env)
    # .../<repo>/yacal-validator/src/yacal_validator/proposals.py
    repo_relative = Path(__file__).resolve().parents[3] / "docs" / "proposals"
    if repo_relative.is_dir():
        return repo_relative
    return Path.cwd() / "docs" / "proposals"


def available() -> list[str]:
    root = proposals_dir()
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir() if (p / STRUCTURE_FRAGMENT).is_file())


def _read(path: Path) -> dict:
    if path.suffix == ".json":
        return json.loads(path.read_text(encoding="utf-8"))
    return _yaml.load(path.read_text(encoding="utf-8")) or {}


def load(name: str) -> dict:
    """Load one proposal's structure fragment."""
    path = proposals_dir() / name / STRUCTURE_FRAGMENT
    if not path.is_file():
        known = available()
        suffix = f" Known proposals: {', '.join(known)}." if known else ""
        raise ProposalError(f"No proposal named {name!r} at {path}.{suffix}")
    return _read(path)


def load_constraints(name: str) -> list[dict]:
    """Load one proposal's constraint-catalog rules, or an empty list if it adds none."""
    path = proposals_dir() / name / CONSTRAINTS_FRAGMENT
    if not path.is_file():
        return []
    rules = _read(path).get("Rule") or []
    return list(rules)


def apply(schema: dict, fragment: dict, name: str) -> None:
    """Merge one fragment's additions into *schema*, in place.

    A fragment adds two kinds of thing and nothing else: new definitions under ``$defs``,
    and new properties on existing types under ``PropertyAdditions``. It never restates a
    host type. That restriction is what keeps the fragment from silently reverting an
    upstream change to a type it happens to mention — it can only add.
    """
    defs = schema.setdefault("$defs", {})
    if not isinstance(defs, dict):
        raise ProposalError(f"Cannot apply proposal {name!r}: schema has no $defs object.")

    for def_name, definition in (fragment.get("$defs") or {}).items():
        if def_name in defs:
            raise ProposalError(
                f"Proposal {name!r} defines {def_name!r}, which the schema already has. "
                "A proposal may only add; if this landed upstream, retire the fragment."
            )
        defs[def_name] = definition

    for type_name, properties in (fragment.get("PropertyAdditions") or {}).items():
        target = defs.get(type_name)
        if not isinstance(target, dict):
            raise ProposalError(
                f"Proposal {name!r} adds properties to {type_name!r}, "
                "which is not a type in this schema."
            )
        target.setdefault("properties", {}).update(properties)


def apply_constraints(catalog: dict, rules: list[dict]) -> None:
    """Append a proposal's rules to a loaded constraint catalog, in place."""
    if rules:
        catalog.setdefault("Rule", []).extend(rules)
