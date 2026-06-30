from pathlib import Path

_EXT_TO_FORMAT = {
    ".xml": "xacml",
    ".yaml": "yacal",
    ".yml": "yacal",
    ".json": "jacal",
    ".alfa": "alfa",
}

_VALID_FORMATS = frozenset({"xacml", "yacal", "jacal", "alfa"})

# Re-export language-specific errors so callers can catch them by name.
from .xacml import XACMLUnsupportedFeatureError as XACMLUnsupportedFeatureError  # noqa: E402
from .alfa import ALFAUnsupportedFeatureError as ALFAUnsupportedFeatureError  # noqa: E402

# UTF-8 BOM that some editors prepend; strip before inspecting the first byte.
_UTF8_BOM = b"\xef\xbb\xbf"


def detect_format_from_bytes(chunk: bytes) -> str | None:
    """Detect ACAL format from raw bytes (e.g. an HTTP request body).

    Detection order:
      '<'  → XACML  (XML declaration or root element)
      '{'  → JACAL  (JSON object)
      ALFA keyword heuristic → ALFA
      else → YACAL  (YAML: bare key, comment '#', or document marker '---')

    ALFA detection reads up to 256 bytes, strips C-style comments, and checks
    whether the first keyword token is 'namespace' or 'import' followed by
    something other than ':' (which would indicate a YAML key).

    Returns None only if chunk is empty after stripping BOM and whitespace.
    """
    stripped = chunk.lstrip(_UTF8_BOM).lstrip()
    if not stripped:
        return None
    first = chr(stripped[0])
    if first == "<":
        return "xacml"
    if first == "{":
        return "jacal"
    # ALFA check — use the longer chunk (up to 256 bytes) for comment stripping.
    from .alfa import _looks_like_alfa
    if _looks_like_alfa(chunk[:256]):
        return "alfa"
    return "yacal"


def detect_format(path: str) -> str | None:
    """Detect format by inspecting file content, falling back to extension."""
    try:
        with open(path, "rb") as fh:
            raw = fh.read(256)
        result = detect_format_from_bytes(raw)
        if result is not None:
            return result
    except OSError:
        pass
    return _EXT_TO_FORMAT.get(Path(path).suffix.lower())


def load(
    path: str,
    fmt: str,
    strict: bool = False,
    include: tuple[str, ...] = (),
    debug: bool = False,
) -> dict:
    if fmt not in _VALID_FORMATS:
        raise ValueError(f"Unknown input format: {fmt!r}. Expected one of: {sorted(_VALID_FORMATS)}")
    if fmt == "xacml":
        from . import xacml
        return xacml.load(path, strict=strict)
    if fmt == "yacal":
        from . import yacal
        return yacal.load(path)
    if fmt == "alfa":
        from . import alfa
        return alfa.load(path, strict=strict, include=include, debug=debug)
    from . import jacal
    return jacal.load(path)
