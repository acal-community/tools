"""`MetadataType` — non-normative annotations that travel with the document.

A `Metadata` property carries facts *about* a document that are not part of the policy
it expresses: what language it was converted from, which tool did it, what the conversion
lost. Its defining contract is that a PDP MUST evaluate the enclosing object exactly as
if the property were absent. That is what makes it safe to stamp — and what distinguishes
it from `PolicyIssuer`, which a PDP without the Administration and Delegation profile MUST
reject outright (§7.4).

Shape, following `EntityType` rather than inventing new grammar::

    MetadataType {
      Attribute: AttributeType [*]   {unique by (AttributeId, Issuer)}
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

`Metadata` attaches to `BundleType` and `PolicyType`, and to nothing else. Attaching it to
`ShortIdType` was considered — an ALFA attribute declaration binds a `category` and a
`type` that `Name`/`Value` cannot hold — and dropped. The declarations ride here instead,
as the source language's whole symbol table under `SOURCE_SYMBOLS`, which asks nothing
further of the schemas and keeps inert facts out of a type the PDP resolves.

Status: the spec change is proposed, not adopted (acal-community/tools#12). The proposal
and the schema fragments that implement it live in ``docs/proposals/metadata/``; the
validators apply them on demand via ``--proposal metadata``, so a stamped document can be
validated without pretending the published schemas admit it. Stamping stays opt-in
(``acal-convert --provenance``) for the same reason.
"""
from __future__ import annotations

import json

from .report import ConversionReport


class MetadataError(ValueError):
    """A document's `Metadata` property violates `MetadataType`.

    Raised for structural problems — a non-object `Metadata`, an empty one, a duplicate
    attribute key. Deliberately *not* raised for unparseable content inside an attribute
    value: those are opaque blobs this module has no standing to police, and a
    non-normative annotation is never a reason to reject an otherwise valid policy.
    """


#: Namespace for provenance facts within `Metadata`. Assigned by the TC, so it holds only
#: facts general enough to be worth standardising.
PROVENANCE_NS = "urn:oasis:names:tc:acal:1.0:provenance:"

SOURCE_LANGUAGE = PROVENANCE_NS + "source-language"
SOURCE_DIALECT = PROVENANCE_NS + "source-dialect"
TOOL = PROVENANCE_NS + "tool"
FIDELITY = PROVENANCE_NS + "fidelity"
CONVERSION_REPORT = PROVENANCE_NS + "conversion-report"

#: Namespace for facts whose *shape* is defined by this toolchain rather than by the TC.
#: The distinction is not ceremony: an identifier in the OASIS namespace is a claim that
#: the TC has assigned it, and a payload whose structure only this repository defines has
#: no business making that claim.
TOOL_NS = "urn:com.github.acal-community.tools:1.0:provenance:"

#: The source language's declarations, as a JSON object. Tool-namespaced because the shape
#: is per-language and defined here — see `acal_core.readers.alfa.symbol_table_as_dict`.
SOURCE_SYMBOLS = TOOL_NS + "source-symbols"

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

    # Declarations the source bound and the conversion spent. Distinct from the notes
    # above: nothing here was lost in a way that changes what the policy decides, so
    # filing it as fidelity loss would overstate it. It is the material a writer back to
    # the source language would need, and the reason the ALFA case needs no `Metadata`
    # on `ShortIdType`.
    if report.source_symbols:
        attrs.append(
            attribute(
                SOURCE_SYMBOLS,
                json.dumps(report.source_symbols, separators=(",", ":"), sort_keys=True),
            )
        )

    return attrs


def attach(doc: dict, additions: list[dict]) -> dict:
    """Stamp *additions* into the document's `Metadata` property, in place.

    Attaches to whichever root the document has — `Bundle` for a bundle, `Policy` for a
    single policy. Existing attributes are preserved; an incoming attribute replaces an
    existing one with the same `(AttributeId, Issuer)`, since `MetadataType` requires
    uniqueness there and a converter re-stamping a document should refresh its own facts
    rather than duplicate them. Keying on the issuer too means refreshing our own tool
    stamp does not clobber someone else's attribute of the same name.
    """
    if not additions:
        return doc

    root = _root_object(doc)
    metadata = root.setdefault("Metadata", {})
    if not isinstance(metadata, dict):
        raise MetadataError(
            f"Cannot stamp into a Metadata property that is {type(metadata).__name__}, "
            "not an object. MetadataType is {Attribute: [...], Content: {...}}."
        )
    existing = metadata.get("Attribute", [])
    if not isinstance(existing, list):
        raise MetadataError(
            f"Metadata.Attribute is {type(existing).__name__}, not a list. "
            "AttributeType has multiplicity [*] and is always a sequence."
        )

    incoming = {_attribute_key(a) for a in additions}
    merged = [a for a in existing if _attribute_key(a) not in incoming]
    merged.extend(additions)
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
    """Return the document's `Metadata` object, or None if it carries none.

    Raises `MetadataError` if the property is present but not an object. Absence and
    malformation are different answers, and returning None for both — as this did — let
    a hand-written ``Metadata: [...]`` travel all the way through a conversion and back
    out into the written document unremarked.
    """
    try:
        root = _root_object(doc)
    except MetadataError:
        return None
    if "Metadata" not in root:
        return None
    metadata = root["Metadata"]
    if not isinstance(metadata, dict):
        raise MetadataError(
            f"Metadata is {type(metadata).__name__}, not an object. "
            "MetadataType is {Attribute: [...], Content: {...}}."
        )
    return metadata


def attributes(doc: dict) -> list[dict]:
    """Return the document's metadata attributes, validating as it goes.

    Raises `MetadataError` on a `Metadata` that violates `MetadataType`: an empty one
    (the type requires ``Content <> null or Attribute->notEmpty()``, so there is no
    "declared but empty" state), a non-list `Attribute`, or two attributes sharing an
    `AttributeId` and `Issuer`.
    """
    metadata = read(doc)
    if metadata is None:
        return []

    attrs = metadata.get("Attribute", [])
    if not isinstance(attrs, list):
        raise MetadataError(
            f"Metadata.Attribute is {type(attrs).__name__}, not a list. "
            "AttributeType has multiplicity [*] and is always a sequence."
        )
    if not attrs and "Content" not in metadata:
        raise MetadataError(
            "Metadata is empty. MetadataType requires Content or at least one "
            "Attribute; a converter must not emit an empty property to say it was here."
        )

    seen: set[tuple] = set()
    for attr in attrs:
        if not isinstance(attr, dict):
            raise MetadataError(
                f"Metadata.Attribute contains {type(attr).__name__}, not an object."
            )
        key = _attribute_key(attr)
        if key in seen:
            issuer = attr.get("Issuer")
            where = f"{key[0]!r}" + (f" from issuer {issuer!r}" if issuer else "")
            raise MetadataError(
                f"Duplicate metadata attribute {where}. MetadataType requires "
                "uniqueness by (AttributeId, Issuer), and there is no correct way to "
                "choose between two values for the same fact."
            )
        seen.add(key)
    return attrs


def attribute_values(doc: dict, attribute_id: str) -> list:
    """Return the values of one metadata attribute; empty list if it is not present."""
    for attr in attributes(doc):
        if attr.get("AttributeId") == attribute_id:
            values = attr.get("Value", [])
            return list(values) if isinstance(values, list) else [values]
    return []


def provenance(doc: dict) -> dict | None:
    """Read provenance back out of a document, or None if it carries none.

    The inverse of `stamp_provenance`, to the extent one exists: it recovers the facts,
    not the `ConversionReport` object.

    Raises `MetadataError` if the `Metadata` property is structurally invalid — that is a
    document defect worth surfacing. A *value* that will not parse is different: the
    payload is opaque by design, so an unreadable conversion report degrades to no notes
    rather than taking the whole read down with it.
    """
    if read(doc) is None:
        return None

    source = attribute_values(doc, SOURCE_LANGUAGE)
    if not source:
        return None

    fidelity = attribute_values(doc, FIDELITY)
    dialect = attribute_values(doc, SOURCE_DIALECT)
    tool = attribute_values(doc, TOOL)

    return {
        "source_format": source[0],
        "source_dialect": dialect[0] if dialect else None,
        "tool": tool[0] if tool else None,
        # Tri-state, on purpose. False means the converter recorded a lossless
        # conversion; None means nothing recorded a fidelity claim at all. Collapsing
        # the second into the first reads silence as a clean bill of health, which is
        # the same conflation the write side goes out of its way to avoid by emitting
        # an explicit `lossless` rather than omitting the attribute.
        "lossy": (fidelity[0] == FIDELITY_LOSSY) if fidelity else None,
        "notes": _decode_json_value(attribute_values(doc, CONVERSION_REPORT), list) or [],
        # The source language's declarations, if the reader had any to preserve.
        "source_symbols": _decode_json_value(attribute_values(doc, SOURCE_SYMBOLS), dict) or {},
    }


def _decode_json_value(values: list, expected: type):
    """Decode a JSON-string attribute value, or None if it will not decode.

    Metadata is non-normative by construction, so a payload this module cannot read is
    never a reason to reject the enclosing policy — the policy is unaffected either way.
    """
    if not values:
        return None
    try:
        decoded = json.loads(values[0])
    except (TypeError, ValueError):
        return None
    return decoded if isinstance(decoded, expected) else None


def _attribute_key(attr: dict) -> tuple:
    """The identity of a metadata attribute: `AttributeId` paired with `Issuer`.

    Not `AttributeId` alone. `AttributeType` carries an `Issuer`, and two attributes
    sharing an id while differing in issuer are meaningful everywhere else the type is
    used — an author stamp from two issuers is an ordinary document. An attribute with no
    issuer keys on None and so stays distinct from one that has it, which leaves the
    common single-issuer case fully checked.
    """
    return (attr.get("AttributeId"), attr.get("Issuer"))


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
    raise MetadataError(
        "Document has no Bundle or Policy root to attach Metadata to. "
        f"Found top-level keys: {sorted(doc)!r}"
    )
