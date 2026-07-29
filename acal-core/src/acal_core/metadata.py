"""`MetadataType` — non-normative annotations that travel with the document.

A `Metadata` property carries facts *about* a document that are not part of the policy
it expresses: what language it was converted from, which tool did it, what the conversion
lost. Its defining contract is that a PDP MUST evaluate the enclosing object exactly as
if the property were absent. That is what makes it safe to stamp — and what distinguishes
it from `PolicyIssuer`, which a PDP without the Administration and Delegation profile MUST
reject outright (§7.4).

Shape, following `EntityType` rather than inventing new grammar::

    MetadataType {
      Attribute: AttributeType [*]   {unique by AttributeId}
      Content:   ContentType   [0..1]
    }
    -- Content <> null or Attribute->notEmpty()

Provenance is not a type here; it is the ``urn:oasis:names:tc:acal:1.0:provenance:*``
namespace *inside* `Metadata`. Other metadata (author, timestamps, tags) shares the
container under its own namespaces.

Two deliberate restrictions on what this module emits:

**Attributes only, never Content.** `ContentType` support is optional in ACAL
(§7.34: *"Support for this object type is optional"*), and the JSON schema instructs
implementers to *"Remove this subschema if your implementation does not support
ContentType objects."* Provenance that lived in `Content` would depend on a feature
implementations are explicitly invited to delete.

**No new datatype.** The conversion report is a JSON string carried at the default
`DataType` of ``urn:oasis:names:tc:acal:1.0:data-type:string``; the `AttributeId` defines
the format by convention. Minting a datatype identifier for it would pull a metadata blob
into the type system, where datatypes carry equality and matching functions and take part
in designator resolution — none of which a blob wants.

Status: the spec change is proposed, not adopted (acal-community/tools#12). Documents
carrying `Metadata` will not validate against the published schemas until it lands, which
is why stamping is opt-in (``acal-convert --provenance``) rather than the default.
"""
from __future__ import annotations

import json

from .report import ConversionReport

#: Namespace for provenance facts within `Metadata`.
PROVENANCE_NS = "urn:oasis:names:tc:acal:1.0:provenance:"

SOURCE_LANGUAGE = PROVENANCE_NS + "source-language"
SOURCE_DIALECT = PROVENANCE_NS + "source-dialect"
TOOL = PROVENANCE_NS + "tool"
FIDELITY = PROVENANCE_NS + "fidelity"
CONVERSION_REPORT = PROVENANCE_NS + "conversion-report"

#: Document root keys a `Metadata` property may attach to. A YACAL/JACAL document is
#: either ``{Policy: PolicyType}`` or ``{Bundle: BundleType}``, and both types take
#: `Metadata` under the proposal.
DOCUMENT_ROOTS = ("Bundle", "Policy")

#: Value of the `fidelity` attribute when a conversion lost nothing.
FIDELITY_LOSSLESS = "lossless"
#: Value when at least one construct was approximated, dropped, or otherwise compromised.
FIDELITY_LOSSY = "lossy"


def attribute(attribute_id: str, *values: object) -> dict:
    """Build one `AttributeType` object.

    `DataType` is omitted rather than spelled out: it defaults to
    ``urn:oasis:names:tc:acal:1.0:data-type:string`` (§7.27), so writing it would add
    noise to every attribute without changing meaning. Callers needing a non-string
    datatype should add the key themselves.
    """
    if not values:
        raise ValueError(
            f"Attribute {attribute_id!r} needs at least one value: "
            "AttributeType.Value has multiplicity [1..*]."
        )
    return {"AttributeId": attribute_id, "Value": list(values)}


def provenance_attributes(
    report: ConversionReport,
    tool: str | None = None,
) -> list[dict]:
    """Render a `ConversionReport` as the attributes of a `Metadata` property.

    The flat facts — source language, dialect, tool, fidelity — go in their own
    attributes so a consumer can read them without parsing anything. The notes go in a
    single JSON-encoded attribute, because they are structured but have no reason to
    earn first-class ACAL grammar.
    """
    attrs = [attribute(SOURCE_LANGUAGE, report.source_format)]

    # The dialect is the more precise fact where the reader could determine it: an .xml
    # file may be foreign XACML 3.0 or the native ACAL XML serialization, and only the
    # dialect distinguishes them.
    if report.source_dialect:
        attrs.append(attribute(SOURCE_DIALECT, report.source_dialect))

    if tool:
        attrs.append(attribute(TOOL, tool))

    attrs.append(
        attribute(FIDELITY, FIDELITY_LOSSY if report.lossy else FIDELITY_LOSSLESS)
    )

    if report.notes:
        notes = [
            {"kind": n.kind, "construct": n.construct, "message": n.message}
            for n in report.notes
        ]
        attrs.append(attribute(CONVERSION_REPORT, json.dumps(notes, separators=(",", ":"))))

    return attrs


def attach(doc: dict, attributes: list[dict]) -> dict:
    """Stamp *attributes* into the document's `Metadata` property, in place.

    Attaches to whichever root the document has — `Bundle` for a bundle, `Policy` for a
    single policy. Existing attributes are preserved; an incoming attribute replaces an
    existing one with the same `AttributeId`, since `MetadataType` requires uniqueness
    there and a converter re-stamping a document should refresh its own facts rather
    than duplicate them.
    """
    if not attributes:
        return doc

    root = _root_object(doc)
    metadata = root.setdefault("Metadata", {})
    existing = metadata.get("Attribute", [])

    incoming_ids = {a["AttributeId"] for a in attributes}
    merged = [a for a in existing if a.get("AttributeId") not in incoming_ids]
    merged.extend(attributes)
    metadata["Attribute"] = merged
    return doc


def stamp_provenance(
    doc: dict,
    report: ConversionReport,
    tool: str | None = None,
) -> dict:
    """Convenience wrapper: render *report* as provenance and attach it to *doc*."""
    return attach(doc, provenance_attributes(report, tool=tool))


def read(doc: dict) -> dict | None:
    """Return the document's `Metadata` object, or None if it carries none."""
    try:
        root = _root_object(doc)
    except ValueError:
        return None
    metadata = root.get("Metadata")
    return metadata if isinstance(metadata, dict) else None


def attribute_values(doc: dict, attribute_id: str) -> list:
    """Return the values of one metadata attribute; empty list if it is not present."""
    metadata = read(doc)
    if not metadata:
        return []
    for attr in metadata.get("Attribute", []):
        if attr.get("AttributeId") == attribute_id:
            return list(attr.get("Value", []))
    return []


def provenance(doc: dict) -> dict | None:
    """Read provenance back out of a document, or None if it carries none.

    The inverse of `stamp_provenance`, to the extent one exists: it recovers the facts,
    not the `ConversionReport` object. Returns a dict with the keys ``source_format``,
    ``source_dialect``, ``tool``, ``lossy``, and ``notes``, mirroring
    `ConversionReport.as_dict` so callers can present either interchangeably.
    """
    metadata = read(doc)
    if not metadata:
        return None

    source = attribute_values(doc, SOURCE_LANGUAGE)
    if not source:
        return None

    fidelity = attribute_values(doc, FIDELITY)
    raw_notes = attribute_values(doc, CONVERSION_REPORT)
    notes: list = []
    if raw_notes:
        try:
            decoded = json.loads(raw_notes[0])
        except (TypeError, ValueError):
            # A malformed report is a reason to say so, not to crash: the policy is
            # still perfectly valid, and Metadata is non-normative by construction.
            decoded = None
        if isinstance(decoded, list):
            notes = decoded

    dialect = attribute_values(doc, SOURCE_DIALECT)
    tool = attribute_values(doc, TOOL)

    return {
        "source_format": source[0],
        "source_dialect": dialect[0] if dialect else None,
        "tool": tool[0] if tool else None,
        "lossy": bool(fidelity) and fidelity[0] == FIDELITY_LOSSY,
        "notes": notes,
    }


def _root_object(doc: dict) -> dict:
    """Return the `BundleType` or `PolicyType` object a `Metadata` property hangs off.

    A document root is a single wrapper key (`Bundle` or `Policy`); the schemas close
    both document forms with ``additionalProperties: false``, so `Metadata` belongs
    inside the wrapped object, never beside it.
    """
    for key in DOCUMENT_ROOTS:
        value = doc.get(key)
        if isinstance(value, dict):
            return value
    raise ValueError(
        "Document has no Bundle or Policy root to attach Metadata to. "
        f"Found top-level keys: {sorted(doc)!r}"
    )
