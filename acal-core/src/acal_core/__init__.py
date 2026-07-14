"""ACAL Core: readers and writers for ACAL policy formats.

Languages are registered once in `languages.py`; everything else derives its
format list from there.
"""

__version__ = "0.1.0"

from .languages import LANGUAGES, READ_FORMATS, WRITE_FORMATS, Language
from .readers import detect_format, detect_format_from_bytes, load, load_with_report
from .report import ConversionNote, ConversionReport
from .writers import write, write_to_string


def convert(path: str, *, from_fmt: str | None = None, to_fmt: str, strict: bool = False) -> str:
    """Convert a policy file and return the serialized output as a string.

    Args:
        path: Path to the input file.
        from_fmt: Input format. Auto-detected if None. See `READ_FORMATS`.
        to_fmt: Output format. See `WRITE_FORMATS`.
        strict: If True, treat non-semantic deprecations as errors.

    Returns:
        Serialized policy document as a string.
    """
    fmt = from_fmt or detect_format(path)
    if fmt is None:
        raise ValueError(
            "Cannot determine input format from file extension. "
            f"Use from_fmt= to specify one of: {sorted(READ_FORMATS)}."
        )
    data = load(path, fmt, strict=strict)
    return write_to_string(data, to_fmt)
