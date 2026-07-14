import io
import sys

from ..languages import WRITE_FORMATS


def write(data: dict, fmt: str, stream=None) -> None:
    if fmt not in WRITE_FORMATS:
        raise ValueError(f"Unknown output format: {fmt!r}. Expected one of: {sorted(WRITE_FORMATS)}")
    if stream is None:
        stream = sys.stdout
    if fmt == "yacal":
        from . import yacal
        yacal.dump(data, stream)
    else:
        from . import jacal
        jacal.dump(data, stream)


def write_to_string(data: dict, fmt: str) -> str:
    buf = io.StringIO()
    write(data, fmt, buf)
    return buf.getvalue()
