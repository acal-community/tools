from pathlib import Path

_EXT_TO_FORMAT = {
    ".xml": "xacml",
    ".yaml": "yacal",
    ".yml": "yacal",
    ".json": "jacal",
}

_VALID_FORMATS = frozenset({"xacml", "yacal", "jacal"})

# Re-export the XACML-specific error so callers can catch it by name.
from .xacml import XACMLUnsupportedFeatureError as XACMLUnsupportedFeatureError  # noqa: E402

# UTF-8 BOM that some editors prepend; strip before inspecting the first byte.
_UTF8_BOM = b"\xef\xbb\xbf"


def detect_format_from_bytes(chunk: bytes) -> str | None:
    """Detect ACAL format from raw bytes (e.g. an HTTP request body).

    Leading-byte rules cover all valid ACAL documents:
      '<'  → XACML  (XML declaration or root element)
      '{'  → JACAL  (JSON object)
      else → YACAL  (YAML: bare key, comment '#', or document marker '---')

    Returns None only if chunk is empty after stripping BOM and whitespace.
    Callers should pass at least the first 64 bytes; the exact amount does not
    matter as long as the leading non-whitespace character is included.
    """
    stripped = chunk.lstrip(_UTF8_BOM).lstrip()
    if not stripped:
        return None
    first = chr(stripped[0])
    if first == "<":
        return "xacml"
    if first == "{":
        return "jacal"
    return "yacal"


def detect_format(path: str) -> str | None:
    """Detect format by inspecting file content, falling back to extension."""
    try:
        with open(path, "rb") as fh:
            raw = fh.read(64)
        result = detect_format_from_bytes(raw)
        if result is not None:
            return result
    except OSError:
        pass
    return _EXT_TO_FORMAT.get(Path(path).suffix.lower())


def load(path: str, fmt: str, strict: bool = False) -> dict:
    if fmt not in _VALID_FORMATS:
        raise ValueError(f"Unknown input format: {fmt!r}. Expected one of: {sorted(_VALID_FORMATS)}")
    if fmt == "xacml":
        from . import xacml
        return xacml.load(path, strict=strict)
    if fmt == "yacal":
        from . import yacal
        return yacal.load(path)
    from . import jacal
    return jacal.load(path)
