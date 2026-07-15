"""Central registry of every policy language and dialect ACAL knows about.

ACAL 1.0 is a hub, not a dialect of XACML. The hub has three serializations of the same
neutral model — XACML 4.0 (XML), YACAL (YAML), and JACAL (JSON) — and every other policy
language is a spoke that imports into it: XACML 2.0, XACML 3.0, ALFA, and in future Cedar,
AWS IAM, Rego.

Two tables, because a *format* and a *dialect* are different things:

``LANGUAGES``  what a file is encoded as. Drives extension mapping, reader/writer dispatch,
               and the ``--from`` / ``--to`` choices in acal-convert and acal-explain. Users
               say ``--from xacml``; they should not have to know which XACML they have.

``DIALECTS``   what a document actually *is*, resolved at load time. One format can carry
               several dialects: an .xml file may be XACML 2.0, 3.0, or 4.0, and those differ
               enormously — 4.0 is the hub itself and expresses all of ACAL, while 3.0 has no
               cross-policy variable sharing at all. Capability matrices therefore hang off
               dialects, not languages. Hanging them off languages produced a matrix asserting
               XACML "cannot express SharedVariableDefinition", which is false for 4.0.

Registering here is the only step needed to make a language visible everywhere; nothing
downstream keeps its own format list.
"""
from __future__ import annotations

import functools
from dataclasses import dataclass
from pathlib import Path

# Capability matrices live outside the package, next to the docs they formalize.
CAPABILITIES_DIR = Path(__file__).resolve().parents[2] / "capabilities"


@dataclass(frozen=True)
class Language:
    """A serialization format — what a file is encoded as."""

    name: str
    label: str
    extensions: tuple[str, ...]
    can_read: bool
    can_write: bool


@dataclass(frozen=True)
class Dialect:
    """A source model — what a document actually is, resolved at load time."""

    id: str
    language: str
    label: str
    # True for the three serializations of ACAL 1.0 itself. A native dialect expresses the
    # whole model by construction, so it has no capability matrix: there is nothing it
    # cannot say. Foreign dialects are import-only and must declare their gaps.
    native: bool
    # Matrix filename under acal-core/capabilities/. Required for foreign dialects,
    # meaningless for native ones.
    capabilities: str | None = None


LANGUAGES: tuple[Language, ...] = (
    Language("xacml", "XACML (2.0, 3.0, 4.0)", (".xml",), can_read=True, can_write=False),
    Language("yacal", "YACAL (YAML)", (".yaml", ".yml"), can_read=True, can_write=True),
    Language("jacal", "JACAL (JSON)", (".json",), can_read=True, can_write=True),
    Language("alfa", "ALFA (Axiomatics PDP 7.x dialect)", (".alfa",), can_read=True, can_write=False),
    Language("cedar", "Cedar (AWS)", (".cedar",), can_read=True, can_write=False),
)

DIALECTS: tuple[Dialect, ...] = (
    # --- The hub: ACAL 1.0, in its three serializations ---
    Dialect("xacml-4.0", "xacml", "XACML 4.0 (the XML serialization of ACAL 1.0)", native=True),
    Dialect("yacal-1.0", "yacal", "YACAL 1.0 (YAML)", native=True),
    Dialect("jacal-1.0", "jacal", "JACAL 1.0 (JSON)", native=True),

    # --- Spokes: foreign dialects, import-only ---
    Dialect("xacml-2.0", "xacml", "XACML 2.0", native=False, capabilities="xacml-2.0.yaml"),
    Dialect("xacml-3.0", "xacml", "XACML 3.0", native=False, capabilities="xacml-3.0.yaml"),
    Dialect("alfa", "alfa", "ALFA (Axiomatics PDP 7.x)", native=False, capabilities="alfa.yaml"),
    Dialect("cedar", "cedar", "Cedar (AWS)", native=False, capabilities="cedar.yaml"),
)

_BY_NAME: dict[str, Language] = {lang.name: lang for lang in LANGUAGES}
_BY_DIALECT: dict[str, Dialect] = {d.id: d for d in DIALECTS}

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


def get_dialect(dialect_id: str) -> Dialect:
    try:
        return _BY_DIALECT[dialect_id]
    except KeyError:
        raise ValueError(
            f"Unknown dialect: {dialect_id!r}. Known dialects: {sorted(_BY_DIALECT)}"
        ) from None


def dialects_of(language: str) -> tuple[Dialect, ...]:
    return tuple(d for d in DIALECTS if d.language == language)


def detect_dialect(path: str, fmt: str) -> str:
    """Resolve which dialect a document is actually written in.

    Only XACML carries more than one dialect per format, and its version is decided by the
    root namespace. Everything else is one-to-one.
    """
    if fmt == "xacml":
        from .readers.xacml import detect_version
        return f"xacml-{detect_version(path).value}"
    candidates = dialects_of(fmt)
    if len(candidates) != 1:
        raise ValueError(f"Cannot resolve a single dialect for format {fmt!r}")
    return candidates[0].id


@functools.lru_cache(maxsize=None)
def capabilities(dialect_id: str) -> dict:
    """Which ACAL features a dialect can express.

    Answers the export-direction question ("what can this dialect say *about* ACAL?"), which
    the reader's own code cannot answer. Returns {} for native dialects — they are the ACAL
    model itself and can express all of it.
    """
    dialect = get_dialect(dialect_id)
    if dialect.capabilities is None:
        return {}

    import ruamel.yaml

    with open(CAPABILITIES_DIR / dialect.capabilities, encoding="utf-8") as fh:
        return ruamel.yaml.YAML(typ="safe").load(fh)


def unexportable_features(dialect_id: str) -> dict[str, str]:
    """ACAL features this dialect cannot express, mapped to why. Empty for native dialects."""
    matrix = capabilities(dialect_id)
    return {
        feature: spec.get("note", "")
        for feature, spec in matrix.get("acal_features", {}).items()
        if spec.get("exportable") is False
    }
