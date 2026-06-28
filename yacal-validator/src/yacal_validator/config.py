"""Configuration loading.

Lookup order:
  1. yacal-validator.toml in the current working directory
  2. ~/.config/yacal-validator/config.toml
  3. Built-in defaults
"""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

_DEFAULT_SOURCE = "https://github.com/oasis-tcs/xacml-spec"
_DEFAULT_BRANCH = "main"


@dataclass
class SchemasConfig:
    source: str = _DEFAULT_SOURCE
    branch: str = _DEFAULT_BRANCH


@dataclass
class Config:
    schemas: SchemasConfig = field(default_factory=SchemasConfig)


def load() -> Config:
    cfg = Config()
    data = _read_toml()
    if data and "schemas" in data:
        s = data["schemas"]
        cfg.schemas.source = s.get("source", _DEFAULT_SOURCE)
        cfg.schemas.branch = s.get("branch", _DEFAULT_BRANCH)
    return cfg


def _read_toml() -> dict | None:
    for path in (
        Path.cwd() / "yacal-validator.toml",
        Path.home() / ".config" / "yacal-validator" / "config.toml",
    ):
        if path.exists():
            with open(path, "rb") as f:
                return tomllib.load(f)
    return None
