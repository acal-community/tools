"""Tests for `--proposal` — validating against an unadopted schema change by name.

The proposal under test is `metadata` (acal-community/tools#12): a `Metadata` property on
`PolicyType` and `BundleType` that a PDP must ignore.

What matters here is not only that the fragment loads, but that applying one stays
visible. A validator that could be talked into a PASS without saying what it admitted
would make the demonstration worthless.
"""
from __future__ import annotations

import io
from pathlib import Path

import pytest

from yacal_validator import proposals
from yacal_validator.output import human
from yacal_validator.schemas import SCHEMA_FILES
from yacal_validator.validator import validate

PROPOSAL = "metadata"


@pytest.fixture(scope="module")
def yaml_schemas(store):
    return {
        "structure": store.resolve(SCHEMA_FILES["core_structure"]),
        "constraints": store.resolve(SCHEMA_FILES["core_constraints"]),
        "xpath": store.try_resolve(SCHEMA_FILES["xpath_structure"]),
        "jsonpath": store.try_resolve(SCHEMA_FILES["jsonpath_structure"]),
    }


def _validate(path, schemas, proposal_names=()):
    return validate(
        path,
        core_structure_path=schemas["structure"],
        core_constraints_path=schemas["constraints"],
        xpath_structure_path=schemas["xpath"],
        jsonpath_structure_path=schemas["jsonpath"],
        proposals=list(proposal_names),
    )


_POLICY = """\
Policy:
  PolicyId: urn:example:policy
  Version: '1.0'
  CombiningAlgId: urn:oasis:names:tc:acal:1.0:combining-algorithm:deny-overrides
  CombinerInput:
  - Rule:
      Id: r1
      Effect: Permit
"""

_METADATA = """\
  Metadata:
    Attribute:
    - AttributeId: urn:oasis:names:tc:acal:1.0:provenance:source-language
      Value: [alfa]
    - AttributeId: urn:oasis:names:tc:acal:1.0:provenance:fidelity
      Value: [lossy]
"""


def _write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "policy.yaml"
    path.write_text(body, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# The fragment on disk is the thing being applied
# ---------------------------------------------------------------------------

def test_the_metadata_proposal_is_discoverable():
    assert PROPOSAL in proposals.available()


def test_fragment_adds_metadatatype_and_attaches_it_to_two_types():
    """The attachment points are the whole scope of the ask; a drift here is the
    proposal quietly growing."""
    fragment = proposals.load(PROPOSAL)
    assert "MetadataType" in fragment["$defs"]
    assert set(fragment["PropertyAdditions"]) == {"PolicyType", "BundleType"}


def test_a_proposal_may_only_add():
    """Redefining an existing type would let a fragment silently revert an upstream
    change to a type it happens to mention."""
    schema = {"$defs": {"MetadataType": {"type": "object"}}}
    with pytest.raises(proposals.ProposalError, match="already has"):
        proposals.apply(schema, proposals.load(PROPOSAL), PROPOSAL)


def test_an_unknown_proposal_names_the_ones_that_exist():
    with pytest.raises(proposals.ProposalError, match="Known proposals"):
        proposals.load("no-such-proposal")


# ---------------------------------------------------------------------------
# Applying it changes the verdict, and only when asked for
# ---------------------------------------------------------------------------

def test_metadata_is_rejected_without_the_proposal(tmp_path, yaml_schemas):
    """The premise of the whole exercise: the published schemas do not admit this."""
    result = _validate(_write(tmp_path, _POLICY + _METADATA), yaml_schemas)
    assert not result.valid


def test_metadata_is_accepted_with_the_proposal(tmp_path, yaml_schemas):
    result = _validate(_write(tmp_path, _POLICY + _METADATA), yaml_schemas, [PROPOSAL])
    assert result.valid, [i.message for i in result.issues]


def test_a_clean_policy_validates_the_same_either_way(tmp_path, yaml_schemas):
    """Applying a proposal must not relax anything it did not ask to change."""
    path = _write(tmp_path, _POLICY)
    assert _validate(path, yaml_schemas).valid
    assert _validate(path, yaml_schemas, [PROPOSAL]).valid


def test_an_empty_metadata_is_still_rejected_under_the_proposal(tmp_path, yaml_schemas):
    """MetadataType has no 'declared but empty' state — that is what the non-empty
    guard in the fragment is for."""
    result = _validate(_write(tmp_path, _POLICY + "  Metadata: {}\n"),
                       yaml_schemas, [PROPOSAL])
    assert not result.valid


# ---------------------------------------------------------------------------
# The constraint the structural schema cannot express
# ---------------------------------------------------------------------------

def test_duplicate_attribute_id_is_rejected(tmp_path, yaml_schemas):
    body = _POLICY + """\
  Metadata:
    Attribute:
    - AttributeId: urn:oasis:names:tc:acal:1.0:provenance:tool
      Value: [acal-convert/1]
    - AttributeId: urn:oasis:names:tc:acal:1.0:provenance:tool
      Value: [acal-convert/2]
"""
    result = _validate(_write(tmp_path, body), yaml_schemas, [PROPOSAL])
    assert not result.valid
    assert any("metadata-attribute-unique" in (i.rule_id or "") for i in result.issues)


def test_same_attribute_id_from_different_issuers_is_allowed(tmp_path, yaml_schemas):
    """Uniqueness is by (AttributeId, Issuer). Keying on AttributeId alone would reject
    an author stamp from two issuers, which is an ordinary document."""
    body = _POLICY + """\
  Metadata:
    Attribute:
    - AttributeId: urn:example:author
      Issuer: one
      Value: [alice]
    - AttributeId: urn:example:author
      Issuer: two
      Value: [bob]
"""
    result = _validate(_write(tmp_path, body), yaml_schemas, [PROPOSAL])
    assert result.valid, [i.message for i in result.issues]


# ---------------------------------------------------------------------------
# A pass under a proposal is not a conformance result
# ---------------------------------------------------------------------------

def test_the_result_records_which_proposals_were_applied(tmp_path, yaml_schemas):
    result = _validate(_write(tmp_path, _POLICY + _METADATA), yaml_schemas, [PROPOSAL])
    assert result.proposals == [PROPOSAL]


def test_the_pass_line_itself_says_the_proposal_is_unadopted(tmp_path, yaml_schemas):
    """On the outcome line, not in a footnote: that is the line quoted out of context."""
    result = _validate(_write(tmp_path, _POLICY + _METADATA), yaml_schemas, [PROPOSAL])
    out = io.StringIO()
    human(result, "policy.yaml", file=out)

    first_line = out.getvalue().splitlines()[0]
    assert first_line.startswith("PASS")
    assert "UNADOPTED" in first_line
    assert PROPOSAL in first_line


def test_an_ordinary_pass_mentions_no_proposal(tmp_path, yaml_schemas):
    result = _validate(_write(tmp_path, _POLICY), yaml_schemas)
    out = io.StringIO()
    human(result, "policy.yaml", file=out)
    assert "UNADOPTED" not in out.getvalue()
