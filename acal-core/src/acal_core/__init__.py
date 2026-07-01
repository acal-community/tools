"""ACAL Core: readers and writers for ACAL policy formats (XACML, YACAL, JACAL, ALFA)."""

__version__ = "0.1.0"

from .readers import detect_format, detect_format_from_bytes, load
from .writers import write, write_to_string


def convert(path: str, *, from_fmt: str | None = None, to_fmt: str, strict: bool = False) -> str:
    """Convert a policy file and return the serialized output as a string.

    Args:
        path: Path to the input file.
        from_fmt: Input format ('xacml', 'yacal', 'jacal', 'alfa'). Auto-detected if None.
        to_fmt: Output format ('yacal' or 'jacal').
        strict: If True, treat non-semantic deprecations as errors.

    Returns:
        Serialized policy document as a string.
    """
    fmt = from_fmt or detect_format(path)
    if fmt is None:
        raise ValueError(
            f"Cannot determine input format from file extension. "
            f"Use from_fmt= to specify 'xacml', 'yacal', 'jacal', or 'alfa'."
        )
    data = load(path, fmt, strict=strict)
    return write_to_string(data, to_fmt)
