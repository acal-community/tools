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
