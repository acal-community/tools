"""Central registry of every policy language ACAL knows about.

Format detection, the reader and writer dispatch tables, and the ``--from`` /
``--to`` choices in acal-convert and acal-explain are all derived from
``LANGUAGES``. Registering a language here is the only step required to make it
visible everywhere; nothing downstream keeps its own format list.

Before this table existed each format was declared in five places, and ALFA was
silently missing from acal-explain's ``--from`` because one of them was missed.
"""
from __future__ import annotations

import functools
from dataclasses import dataclass
from pathlib import Path

# Capability matrices live outside the package, next to the docs they formalize.
CAPABILITIES_DIR = Path(__file__).resolve().parents[2] / "capabilities"


@dataclass(frozen=True)
class Language:
    name: str
    label: str
    extensions: tuple[str, ...]
    can_read: bool
    can_write: bool
    # An ACAL serialization of the neutral model, so conversion between natives
    # is lossless. Foreign languages are import-only: see
    # docs/policy-language-expressiveness.md.
    native: bool = False
    # Machine-readable capability matrix under acal-core/capabilities/, naming
    # which ACAL features this language can express. Drives reader dispositions,
    # acal-explain's exportability report, and (later) the export tool's
    # precondition gate. None until the matrix has been authored.
    capabilities: str | None = None


LANGUAGES: tuple[Language, ...] = (
    Language(
        name="xacml",
        label="XACML 2.0-4.0",
        extensions=(".xml",),
        can_read=True,
        can_write=False,
        capabilities="xacml.yaml",
    ),
    Language(
        name="yacal",
        label="YACAL (YAML)",
        extensions=(".yaml", ".yml"),
        can_read=True,
        can_write=True,
        native=True,
    ),
    Language(
        name="jacal",
        label="JACAL (JSON)",
        extensions=(".json",),
        can_read=True,
        can_write=True,
        native=True,
    ),
    Language(
        name="alfa",
        label="ALFA (Axiomatics PDP 7.x dialect)",
        extensions=(".alfa",),
        can_read=True,
        can_write=False,
        capabilities="alfa.yaml",
    ),
)

_BY_NAME: dict[str, Language] = {lang.name: lang for lang in LANGUAGES}

READ_FORMATS: tuple[str, ...] = tuple(l.name for l in LANGUAGES if l.can_read)
WRITE_FORMATS: tuple[str, ...] = tuple(l.name for l in LANGUAGES if l.can_write)

EXT_TO_FORMAT: dict[str, str] = {
    ext: lang.name for lang in LANGUAGES for ext in lang.extensions
}


def get(name: str) -> Language:
    try:
        return _BY_NAME[name]
    except KeyError:
        raise ValueError(
            f"Unknown language: {name!r}. Known languages: {sorted(_BY_NAME)}"
        ) from None


def label(name: str) -> str:
    lang = _BY_NAME.get(name)
    return lang.label if lang else name


@functools.lru_cache(maxsize=None)
def capabilities(name: str) -> dict:
    """Load a language's capability matrix — which ACAL features it can express.

    Answers the export-direction question ("what can this language say about ACAL?"),
    which is the one the reader's own code cannot answer. Returns {} for native ACAL
    serializations, which can express the whole model by construction.
    """
    lang = get(name)
    if lang.capabilities is None:
        return {}

    import ruamel.yaml

    path = CAPABILITIES_DIR / lang.capabilities
    with open(path, encoding="utf-8") as fh:
        return ruamel.yaml.YAML(typ="safe").load(fh)


def unexportable_features(name: str) -> dict[str, str]:
    """ACAL features this language cannot express, mapped to why. Empty for natives."""
    matrix = capabilities(name)
    return {
        feature: spec.get("note", "")
        for feature, spec in matrix.get("acal_features", {}).items()
        if spec.get("exportable") is False
    }
