"""Configuration loading for acal-explain.

Priority (highest first):
  1. Environment variables (ACAL_EXPLAIN_MODEL, ACAL_EXPLAIN_API_KEY, ACAL_EXPLAIN_API_BASE)
  2. ~/.config/acal-explain/config.toml
  3. Built-in defaults

Config file format (TOML):

    [llm]
    model = "anthropic/claude-sonnet-4-6"
    api_key = "sk-..."        # optional — prefer env var
    api_base = "..."          # optional, for local/custom endpoints

    [output]
    format = "text"           # text | markdown | json

Example model strings (litellm provider/model format):
    anthropic/claude-sonnet-4-6
    openai/gpt-4o
    xai/grok-3
    google/gemini-2.0-flash
    ollama/llama3
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomllib  # type: ignore[no-redef]
    except ImportError:
        import tomli as tomllib  # type: ignore[no-redef]


_CONFIG_PATH = Path.home() / ".config" / "acal-explain" / "config.toml"

_DEFAULT_MODEL = "anthropic/claude-sonnet-4-6"
_DEFAULT_FORMAT = "text"


def _load_toml() -> dict:
    if _CONFIG_PATH.exists():
        with open(_CONFIG_PATH, "rb") as fh:
            return tomllib.load(fh)
    return {}


class Config:
    def __init__(self) -> None:
        raw = _load_toml()
        llm = raw.get("llm", {})
        out = raw.get("output", {})

        self.model: str = (
            os.environ.get("ACAL_EXPLAIN_MODEL")
            or llm.get("model")
            or _DEFAULT_MODEL
        )
        self.api_key: str | None = (
            os.environ.get("ACAL_EXPLAIN_API_KEY")
            or llm.get("api_key")
        )
        self.api_base: str | None = (
            os.environ.get("ACAL_EXPLAIN_API_BASE")
            or llm.get("api_base")
        )
        self.default_format: str = out.get("format", _DEFAULT_FORMAT)

    def llm_kwargs(self) -> dict:
        kwargs: dict = {}
        if self.api_key:
            kwargs["api_key"] = self.api_key
        if self.api_base:
            kwargs["api_base"] = self.api_base
        return kwargs
