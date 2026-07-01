"""ACAL format converter: thin CLI wrapper around acal-core."""

__version__ = "0.2.0"

from acal_core import convert, detect_format, detect_format_from_bytes, load
from acal_core.writers import write_to_string

__all__ = ["convert", "detect_format", "detect_format_from_bytes", "load", "write_to_string"]
