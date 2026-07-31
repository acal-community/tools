"""Tests for the `Metadata` property — non-normative annotations on a document.

The proposal these exercise is acal-community/tools#12: a `Metadata` object a PDP must
ignore, so conversion fidelity can travel with the document instead of living only in the
process that performed the import.
"""
import json
from pathlib import Path

import pytest

from acal_core import metadata
from acal_core.readers import load_with_report
from acal_core.readers.xacml import XACMLUnsupportedFeatureError, load as load_xacml
from acal_core.report import APPROXIMATED, LOSSY, ConversionReport
from acal_core.writers import write_to_string

FIXTURES = Path(__file__).parent / "fixtures"
XACML4 = FIXTURES / "xacml4"


def _lossless_report() -> ConversionReport:
    return ConversionReport(source_format="alfa", source_dialect="alfa")


def _lossy_report() -> ConversionReport:
    report = ConversionReport(source_format="alfa", source_dialect="alfa")
    report.add(LOSSY, "Attribute 'docPath' declares type 'xpath'", construct="attribute")
    report.add(APPROXIMATED, "Combining algorithm mapped to nearest equivalent")
    return report


# ---------------------------------------------------------------------------
# Attribute construction
# ---------------------------------------------------------------------------

def test_attribute_omits_datatype():
    """DataType defaults to string (spec §7.27); spelling it out is noise.

    This is the resolution of the open question on #12 — no JSON datatype is minted for
    the conversion report, so nothing here enters the type system.
    """
    attr = metadata.attribute(metadata.TOOL, "acal-convert/0.2.0")
    assert attr == {
        "AttributeId": metadata.TOOL,
        "Value": ["acal-convert/0.2.0"],
    }
    assert "DataType" not in attr


def test_attribute_value_is_always_a_list():
    """AttributeType.Value has multiplicity [1..*], so it is an array even when single."""
    assert metadata.attribute(metadata.FIDELITY, "lossless")["Value"] == ["lossless"]
    assert metadata.attribute("urn:x:tags", "a", "b")["Value"] == ["a", "b"]


def test_attribute_rejects_empty_values():
    with pytest.raises(ValueError, match=r"\[1\.\.\*\]"):
        metadata.attribute("urn:x:empty")


# ---------------------------------------------------------------------------
# Rendering a ConversionReport as provenance
# ---------------------------------------------------------------------------

def test_provenance_records_language_dialect_and_tool():
    attrs = metadata.provenance_attributes(_lossless_report(), tool="acal-convert/0.2.0")
    by_id = {a["AttributeId"]: a["Value"] for a in attrs}

    assert by_id[metadata.SOURCE_LANGUAGE] == ["alfa"]
    assert by_id[metadata.SOURCE_DIALECT] == ["alfa"]
    assert by_id[metadata.TOOL] == ["acal-convert/0.2.0"]


def test_lossless_conversion_says_so_explicitly():
    """Absence of notes must be recorded as a fact, not inferred from a missing key.

    'No conversion report attribute' and 'conversion lost nothing' are different claims;
    only the second is worth carrying.
    """
    attrs = metadata.provenance_attributes(_lossless_report())
    by_id = {a["AttributeId"]: a["Value"] for a in attrs}

    assert by_id[metadata.FIDELITY] == [metadata.FIDELITY_LOSSLESS]
    assert metadata.CONVERSION_REPORT not in by_id


def test_lossy_conversion_carries_the_notes_as_json():
    attrs = metadata.provenance_attributes(_lossy_report())
    by_id = {a["AttributeId"]: a["Value"] for a in attrs}

    assert by_id[metadata.FIDELITY] == [metadata.FIDELITY_LOSSY]
    notes = json.loads(by_id[metadata.CONVERSION_REPORT][0])
    assert [n["kind"] for n in notes] == [LOSSY, APPROXIMATED]
    assert notes[0]["construct"] == "attribute"
    assert "docPath" in notes[0]["message"]


def test_dialect_omitted_when_the_reader_could_not_determine_it():
    report = ConversionReport(source_format="yacal", source_dialect=None)
    ids = {a["AttributeId"] for a in metadata.provenance_attributes(report)}
    assert metadata.SOURCE_DIALECT not in ids


# ---------------------------------------------------------------------------
# Attaching to a document
# ---------------------------------------------------------------------------

def test_attaches_inside_the_policy_root_not_beside_it():
    """Both document forms are additionalProperties: false, so Metadata goes inside."""
    doc = {"Policy": {"PolicyId": "urn:example:p", "Version": "1.0"}}
    metadata.stamp_provenance(doc, _lossless_report())

    assert set(doc) == {"Policy"}, "Metadata must not become a second top-level key"
    assert "Metadata" in doc["Policy"]


def test_attaches_inside_the_bundle_root():
    doc = {"Bundle": {"Policy": [{"PolicyId": "urn:example:p"}]}}
    metadata.stamp_provenance(doc, _lossless_report())

    assert set(doc) == {"Bundle"}
    assert "Metadata" in doc["Bundle"]
    assert "Metadata" not in doc["Bundle"]["Policy"][0], (
        "Bundle-level origin must not be stamped onto contained policies"
    )


def test_attach_preserves_foreign_metadata():
    """Provenance shares the container with other metadata; it does not own it."""
    doc = {
        "Policy": {
            "PolicyId": "urn:example:p",
            "Metadata": {"Attribute": [
                {"AttributeId": "urn:example:author", "Value": ["example-author"]},
            ]},
        }
    }
    metadata.stamp_provenance(doc, _lossless_report())

    by_id = {a["AttributeId"]: a["Value"]
             for a in doc["Policy"]["Metadata"]["Attribute"]}
    assert by_id["urn:example:author"] == ["example-author"]
    assert by_id[metadata.SOURCE_LANGUAGE] == ["alfa"]


def test_restamping_refreshes_rather_than_duplicates():
    """MetadataType requires AttributeId uniqueness, so a second stamp must replace."""
    doc = {"Policy": {"PolicyId": "urn:example:p"}}
    metadata.stamp_provenance(doc, ConversionReport(source_format="alfa"))
    metadata.stamp_provenance(doc, ConversionReport(source_format="cedar"))

    attrs = doc["Policy"]["Metadata"]["Attribute"]
    ids = [a["AttributeId"] for a in attrs]
    assert len(ids) == len(set(ids)), f"Duplicate AttributeIds: {ids}"
    assert metadata.attribute_values(doc, metadata.SOURCE_LANGUAGE) == ["cedar"]


def test_attach_rejects_a_document_with_no_recognised_root():
    with pytest.raises(ValueError, match="no Bundle or Policy root"):
        metadata.stamp_provenance({"Request": {}}, _lossless_report())


def test_empty_attribute_list_leaves_the_document_untouched():
    """No empty skeleton: Metadata: {} is not a legal state under the proposal."""
    doc = {"Policy": {"PolicyId": "urn:example:p"}}
    metadata.attach(doc, [])
    assert "Metadata" not in doc["Policy"]


# ---------------------------------------------------------------------------
# Reading it back
# ---------------------------------------------------------------------------

def test_provenance_round_trips_through_the_document():
    doc = {"Policy": {"PolicyId": "urn:example:p"}}
    metadata.stamp_provenance(doc, _lossy_report(), tool="acal-convert/0.2.0")

    recovered = metadata.provenance(doc)
    assert recovered["source_format"] == "alfa"
    assert recovered["source_dialect"] == "alfa"
    assert recovered["tool"] == "acal-convert/0.2.0"
    assert recovered["lossy"] is True
    assert len(recovered["notes"]) == 2


def test_provenance_survives_a_yacal_jacal_serialization_round_trip():
    """The point of the whole exercise: fidelity outliving the process that found it."""
    doc = {"Policy": {"PolicyId": "urn:example:p", "Version": "1.0"}}
    metadata.stamp_provenance(doc, _lossy_report(), tool="acal-convert/0.2.0")

    reloaded = json.loads(write_to_string(doc, "jacal"))
    recovered = metadata.provenance(reloaded)

    assert recovered["source_format"] == "alfa"
    assert recovered["lossy"] is True
    assert "docPath" in recovered["notes"][0]["message"]


def test_document_without_metadata_reports_none():
    assert metadata.provenance({"Policy": {"PolicyId": "urn:example:p"}}) is None
    assert metadata.read({"Policy": {"PolicyId": "urn:example:p"}}) is None


def test_foreign_metadata_alone_is_not_provenance():
    doc = {"Policy": {"Metadata": {"Attribute": [
        {"AttributeId": "urn:example:author", "Value": ["example-author"]},
    ]}}}
    assert metadata.read(doc) is not None
    assert metadata.provenance(doc) is None


def test_malformed_conversion_report_does_not_crash_the_reader():
    """Metadata is non-normative: a corrupt note list must not take the policy with it."""
    doc = {"Policy": {"Metadata": {"Attribute": [
        {"AttributeId": metadata.SOURCE_LANGUAGE, "Value": ["alfa"]},
        {"AttributeId": metadata.FIDELITY, "Value": [metadata.FIDELITY_LOSSY]},
        {"AttributeId": metadata.CONVERSION_REPORT, "Value": ["{not json"]},
    ]}}}
    recovered = metadata.provenance(doc)
    assert recovered["source_format"] == "alfa"
    assert recovered["lossy"] is True
    assert recovered["notes"] == []


# ---------------------------------------------------------------------------
# XACML (the hub's XML serialization) reads Metadata rather than rejecting it
# ---------------------------------------------------------------------------

_XACML_WITH_METADATA = """<?xml version="1.0" encoding="UTF-8"?>
<Policy xmlns="urn:oasis:names:tc:xacml:4.0:core:schema"
        PolicyId="urn:example:metadata"
        Version="1.0"
        CombiningAlgId="urn:oasis:names:tc:acal:1.0:combining-algorithm:deny-overrides">
  <Metadata>
    <Attribute AttributeId="urn:oasis:names:tc:acal:1.0:provenance:source-language">
      <AttributeValue>alfa</AttributeValue>
    </Attribute>
    <Attribute AttributeId="urn:oasis:names:tc:acal:1.0:provenance:fidelity">
      <AttributeValue>lossy</AttributeValue>
    </Attribute>
  </Metadata>
  <Rule Id="permit-all" Effect="Permit"/>
</Policy>
"""


def test_xacml_reader_carries_metadata_through(tmp_path):
    path = tmp_path / "with-metadata.xml"
    path.write_text(_XACML_WITH_METADATA, encoding="utf-8")

    doc = load_xacml(str(path))
    assert metadata.attribute_values(doc, metadata.SOURCE_LANGUAGE) == ["alfa"]
    assert metadata.attribute_values(doc, metadata.FIDELITY) == ["lossy"]


def test_xacml_reader_rejects_a_metadata_attribute_with_no_value(tmp_path):
    path = tmp_path / "bad-metadata.xml"
    path.write_text(
        _XACML_WITH_METADATA.replace(
            "<AttributeValue>alfa</AttributeValue>", ""
        ),
        encoding="utf-8",
    )
    with pytest.raises(XACMLUnsupportedFeatureError, match=r"\[1\.\.\*\]"):
        load_xacml(str(path))


def test_xacml_reader_rejects_metadata_content(tmp_path):
    """Content is refused deliberately: ContentType support is optional in ACAL (§7.34)."""
    path = tmp_path / "content-metadata.xml"
    path.write_text(
        _XACML_WITH_METADATA.replace(
            "  </Metadata>", "    <Content>blob</Content>\n  </Metadata>"
        ),
        encoding="utf-8",
    )
    with pytest.raises(XACMLUnsupportedFeatureError, match="Content"):
        load_xacml(str(path))


# ---------------------------------------------------------------------------
# End to end, against a real conversion
# ---------------------------------------------------------------------------

def test_real_conversion_stamps_the_language_it_came_from():
    doc, report = load_with_report(str(XACML4 / "simple-policy.xml"), "xacml")
    metadata.stamp_provenance(doc, report, tool="acal-convert/test")

    recovered = metadata.provenance(doc)
    assert recovered["source_format"] == "xacml"
    assert recovered["source_dialect"] == "xacml-4.0", (
        "The dialect is the fact that matters: an .xml file may be foreign XACML 3.0 "
        "or the native ACAL XML serialization"
    )
    assert recovered["lossy"] is False


# ---------------------------------------------------------------------------
# Structural defects in a Metadata this module did not write
#
# Everything above stamps a document and reads it back, so `attach` gets to guarantee
# the shape it later relies on. These start from a document someone else wrote.
# ---------------------------------------------------------------------------

def test_attach_refuses_a_metadata_that_is_not_an_object():
    """`Metadata: [...]` used to crash with a bare AttributeError from setdefault."""
    doc = {"Policy": {"PolicyId": "p", "Metadata": ["not", "an", "object"]}}
    with pytest.raises(metadata.MetadataError, match="not an object"):
        metadata.attach(doc, [metadata.attribute(metadata.TOOL, "acal-convert/test")])


def test_read_refuses_a_metadata_that_is_not_an_object():
    """Absent and malformed are different answers; both used to be None.

    Returning None for a malformed property let a hand-written `Metadata:` of the wrong
    shape travel through a conversion and back out into the written document unremarked.
    """
    doc = {"Policy": {"PolicyId": "p", "Metadata": "a string"}}
    with pytest.raises(metadata.MetadataError, match="not an object"):
        metadata.read(doc)


def test_empty_metadata_is_rejected_rather_than_ignored():
    """MetadataType has no 'declared but empty' state — that is the point of the guard."""
    doc = {"Policy": {"PolicyId": "p", "Metadata": {}}}
    with pytest.raises(metadata.MetadataError, match="empty"):
        metadata.attributes(doc)


def test_metadata_holding_only_content_is_not_empty():
    """The non-empty constraint is a disjunction: Content alone satisfies it.

    This module never emits Content (§7.34 makes ContentType support optional), but a
    document that uses it is conformant and must not be rejected on the way through.
    """
    doc = {"Policy": {"PolicyId": "p", "Metadata": {"Content": {"Value": "<x/>"}}}}
    assert metadata.attributes(doc) == []


def test_duplicate_attribute_id_is_reported_not_silently_resolved():
    doc = {"Policy": {"PolicyId": "p", "Metadata": {"Attribute": [
        {"AttributeId": metadata.TOOL, "Value": ["acal-convert/1"]},
        {"AttributeId": metadata.TOOL, "Value": ["acal-convert/2"]},
    ]}}}
    with pytest.raises(metadata.MetadataError, match="Duplicate"):
        metadata.attribute_values(doc, metadata.TOOL)


def test_same_attribute_id_from_different_issuers_is_legal():
    """Uniqueness is by (AttributeId, Issuer), amending the isUnique(AttributeId) of #12.

    AttributeType carries an Issuer and two same-id attributes from different issuers are
    meaningful everywhere else in ACAL; a container defined by a MUST-ignore rule has no
    reason to be the one place it is forbidden.
    """
    doc = {"Policy": {"PolicyId": "p", "Metadata": {"Attribute": [
        {"AttributeId": "urn:example:author", "Issuer": "a", "Value": ["one"]},
        {"AttributeId": "urn:example:author", "Issuer": "b", "Value": ["two"]},
    ]}}}
    assert len(metadata.attributes(doc)) == 2


def test_restamping_replaces_only_the_matching_issuer():
    """A converter refreshing its own facts must not clobber another issuer's."""
    doc = {"Policy": {"PolicyId": "p", "Metadata": {"Attribute": [
        {"AttributeId": metadata.TOOL, "Issuer": "someone-else", "Value": ["theirs"]},
        {"AttributeId": metadata.TOOL, "Value": ["acal-convert/old"]},
    ]}}}
    metadata.attach(doc, [metadata.attribute(metadata.TOOL, "acal-convert/new")])

    attrs = doc["Policy"]["Metadata"]["Attribute"]
    assert len(attrs) == 2
    assert {a.get("Issuer"): a["Value"][0] for a in attrs} == {
        "someone-else": "theirs",
        None: "acal-convert/new",
    }


# ---------------------------------------------------------------------------
# Fidelity is tri-state on the way back out
# ---------------------------------------------------------------------------

def test_absent_fidelity_reads_as_unknown_not_as_lossless():
    """Silence is not a clean bill of health.

    The write side goes out of its way to emit an explicit `lossless` rather than omit
    the attribute; reading a missing attribute as False would undo that distinction.
    """
    doc = {"Policy": {"PolicyId": "p", "Metadata": {"Attribute": [
        {"AttributeId": metadata.SOURCE_LANGUAGE, "Value": ["alfa"]},
    ]}}}
    assert metadata.provenance(doc)["lossy"] is None


def test_recorded_lossless_reads_as_false():
    doc = {"Policy": {"PolicyId": "p"}}
    metadata.stamp_provenance(doc, _lossless_report())
    assert metadata.provenance(doc)["lossy"] is False


# ---------------------------------------------------------------------------
# ALFA declarations survive as metadata rather than as a ShortIdType change
# ---------------------------------------------------------------------------

def test_alfa_declarations_are_preserved_in_metadata():
    """An ALFA attribute declaration binds four facts; conversion spends three of them.

    The transformer resolves the short name away and stamps category and datatype onto
    every referencing designator, so the declaration itself is gone. This is the whole
    reason #12 does not need `Metadata` on `ShortIdType`: the symbol table rides in the
    document-level `Metadata` that proposal already asks for.
    """
    doc, report = load_with_report(str(FIXTURES / "alfa" / "xpath-datatype.alfa"), "alfa")
    metadata.stamp_provenance(doc, report, tool="acal-convert/test")

    symbols = metadata.provenance(doc)["source_symbols"]
    assert symbols["namespace"] == "com.example"

    decl = symbols["attributes"]["docPath"]
    assert decl["id"] == "urn:example:attribute:doc-path"
    assert decl["category"] == "urn:oasis:names:tc:acal:1.0:attribute-category:resource"
    assert decl["type"] == "xpath", (
        "the declared ALFA type, not the ACAL datatype it was mapped to — this is source "
        "material for a writer back to ALFA, not a fact about the ACAL document"
    )


def test_source_symbols_use_the_tool_namespace_not_the_oasis_one():
    """The payload shape is defined here, so the identifier must not claim TC assignment.

    The generic provenance facts are candidates for standardisation and keep the OASIS
    namespace; a per-language symbol table is not.
    """
    assert metadata.SOURCE_SYMBOLS.startswith("urn:com.github.acal-community.tools:")
    assert metadata.SOURCE_LANGUAGE.startswith("urn:oasis:names:tc:acal:")


def test_readers_with_nothing_to_preserve_emit_no_symbols_attribute():
    doc, report = load_with_report(str(XACML4 / "simple-policy.xml"), "xacml")
    metadata.stamp_provenance(doc, report)

    ids = [a["AttributeId"] for a in metadata.attributes(doc)]
    assert metadata.SOURCE_SYMBOLS not in ids
    assert metadata.provenance(doc)["source_symbols"] == {}


def test_unparseable_symbol_payload_degrades_rather_than_raising():
    """A blob this module cannot read is never a reason to reject the policy.

    Structural defects raise; opaque content does not. The payload is opaque by design,
    and the enclosing policy is unaffected either way.
    """
    doc = {"Policy": {"PolicyId": "p", "Metadata": {"Attribute": [
        {"AttributeId": metadata.SOURCE_LANGUAGE, "Value": ["alfa"]},
        {"AttributeId": metadata.SOURCE_SYMBOLS, "Value": ["{not json"]},
    ]}}}
    assert metadata.provenance(doc)["source_symbols"] == {}


# ---------------------------------------------------------------------------
# XACML reader
# ---------------------------------------------------------------------------

def test_empty_metadata_element_is_rejected_not_dropped(tmp_path):
    """This reader rejects rather than ignores; deleting an empty property would hide
    the bug in whatever wrote it."""
    path = tmp_path / "empty-metadata.xml"
    path.write_text(
        '<Policy xmlns="urn:oasis:names:tc:xacml:4.0:core:schema" '
        'PolicyId="p" Version="1.0" '
        'CombiningAlgId="urn:oasis:names:tc:acal:1.0:combining-algorithm:deny-overrides">'
        "<Metadata/>"
        "</Policy>",
        encoding="utf-8",
    )
    with pytest.raises(XACMLUnsupportedFeatureError, match="empty"):
        load_xacml(str(path))
