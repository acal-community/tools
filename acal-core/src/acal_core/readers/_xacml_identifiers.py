"""
Identifier remapping: XACML 3.0 URNs → ACAL 1.0 URNs.

XACML 4.0 policies already use ACAL 1.0 identifiers internally, so this
module is only applied when converting from XACML 3.0.  Calling it on an
already-ACAL identifier is safe — nothing matches, so the value passes through
unchanged.
"""

import re

_XACML_VER = r"\d+\.\d+"

# urn:oasis:names:tc:xacml:3.0:rule-combining-algorithm:deny-overrides
# urn:oasis:names:tc:xacml:1.0:policy-combining-algorithm:deny-overrides
_COMBINING_RE = re.compile(
    r"^urn:oasis:names:tc:xacml:"
    + _XACML_VER
    + r":(?:rule|policy)-combining-algorithm:(.+)$"
)

# http://www.w3.org/2001/XMLSchema#string  →  acal:data-type:string
_XSD_TYPE_RE = re.compile(r"^http://www\.w3\.org/2001/XMLSchema#(.+)$")

# All other urn:...xacml:<ver>:<remainder>  →  urn:...acal:1.0:<remainder>
_XACML_URN_RE = re.compile(
    r"^urn:oasis:names:tc:xacml:" + _XACML_VER + r":(.+)$"
)

_ACAL_BASE = "urn:oasis:names:tc:acal:1.0"
_ACAL_STRING_DT = f"{_ACAL_BASE}:data-type:string"


def remap_identifier(value: str | None) -> str | None:
    """Return the ACAL 1.0 equivalent of an XACML identifier, or the value unchanged."""
    if not value:
        return value

    m = _COMBINING_RE.match(value)
    if m:
        return f"{_ACAL_BASE}:combining-algorithm:{m.group(1)}"

    m = _XSD_TYPE_RE.match(value)
    if m:
        return f"{_ACAL_BASE}:data-type:{m.group(1)}"

    m = _XACML_URN_RE.match(value)
    if m:
        return f"{_ACAL_BASE}:{m.group(1)}"

    return value


def optional_datatype(raw_dt: str | None) -> str | None:
    """Remap a DataType and return None when the result is the ACAL default (string)."""
    if not raw_dt:
        return None
    remapped = remap_identifier(raw_dt)
    if remapped == _ACAL_STRING_DT:
        return None
    return remapped
