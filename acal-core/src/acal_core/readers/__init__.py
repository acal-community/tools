import warnings
from pathlib import Path

from ..languages import EXT_TO_FORMAT, READ_FORMATS, detect_dialect
from ..report import LOSSY, ConversionReport

# Re-export language-specific errors so callers can catch them by name.
from .xacml import XACMLUnsupportedFeatureError as XACMLUnsupportedFeatureError  # noqa: E402
from .alfa import ALFAUnsupportedFeatureError as ALFAUnsupportedFeatureError  # noqa: E402
from .cedar import (  # noqa: E402
    CedarSyntaxError as CedarSyntaxError,
    CedarUnsupportedFeatureError as CedarUnsupportedFeatureError,
)

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
    # Cedar opens with permit / forbid / @annotation — none of which collide with YACAL's
    # capitalized root keys or ALFA's namespace/import.
    from .cedar import looks_like_cedar
    if looks_like_cedar(chunk[:256]):
        return "cedar"
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
    return EXT_TO_FORMAT.get(Path(path).suffix.lower())


def load(
    path: str,
    fmt: str,
    strict: bool = False,
    include: tuple[str, ...] = (),
    debug: bool = False,
    fail_closed: bool = False,
) -> dict:
    if fmt not in READ_FORMATS:
        raise ValueError(
            f"Unknown input format: {fmt!r}. Expected one of: {sorted(READ_FORMATS)}"
        )
    if fmt == "xacml":
        from . import xacml
        return xacml.load(path, strict=strict)
    if fmt == "yacal":
        from . import yacal
        return yacal.load(path)
    if fmt == "alfa":
        from . import alfa
        return alfa.load(path, strict=strict, include=include, debug=debug, fail_closed=fail_closed)
    if fmt == "cedar":
        from . import cedar
        return cedar.load(path, strict=strict, fail_closed=fail_closed)
    from . import jacal
    return jacal.load(path)


def load_with_report(
    path: str,
    fmt: str,
    strict: bool = False,
    include: tuple[str, ...] = (),
    debug: bool = False,
    fail_closed: bool = False,
) -> tuple[dict, ConversionReport]:
    """Load a policy and report what the reader had to compromise on.

    Same contract as `load`, but the fidelity warnings the reader would have
    printed to stderr are returned as structured notes instead. Warnings that
    are not about conversion fidelity are re-emitted so nothing is swallowed.
    """
    try:
        dialect = detect_dialect(path, fmt)
    except (ValueError, OSError):
        dialect = None
    report = ConversionReport(source_format=fmt, source_dialect=dialect, strict=strict)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        doc = load(path, fmt, strict=strict, include=include, debug=debug, fail_closed=fail_closed)

    for entry in caught:
        if issubclass(entry.category, UserWarning):
            report.add(LOSSY, str(entry.message))
        else:
            warnings.warn_explicit(
                entry.message, entry.category, entry.filename, entry.lineno
            )

    return doc, report
