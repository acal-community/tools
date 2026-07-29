"""Shared fixtures for jacal-validator tests.

By default, tests that need the normative spec files look for an
xacml-spec checkout alongside this repo (../xacml-spec relative to the
repo root).  Override with the ACAL_SPEC_DIR environment variable to run
in CI or on other machines.  Tests that depend on the spec directory are
automatically skipped when it is not present.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

# conftest.py -> tests -> jacal-validator -> <repo root> -> <parent of repo>
_DEFAULT_SPEC_DIR = Path(__file__).resolve().parents[3] / "xacml-spec"
SPEC_DIR = Path(os.environ.get("ACAL_SPEC_DIR", _DEFAULT_SPEC_DIR))


def _require_spec_dir() -> Path:
    if not SPEC_DIR.is_dir():
        pytest.skip(f"Spec directory not found: {SPEC_DIR}  (set ACAL_SPEC_DIR to override)")
    return SPEC_DIR


@pytest.fixture(scope="session")
def spec_dir() -> Path:
    return _require_spec_dir()


@pytest.fixture(scope="session")
def store():
    _require_spec_dir()
    from jacal_validator.schemas import SchemaStore
    return SchemaStore(source=str(SPEC_DIR))
