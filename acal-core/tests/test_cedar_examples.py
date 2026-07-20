"""Cedar reader vs. the real-world corpus in cedar-policy/cedar-examples.

The hand-written fixtures in fixtures/cedar/ exercise one construct at a time; this file
exercises the reader against policies nobody wrote for us — AWS's own tutorials and
benchmarks — as a check against the gap between "passes our unit tests" and "parses a real
policy someone actually shipped". tinytodo in particular (AWS's reference app for
lists/teams/private-tasks sharing) is the scenario this project cares most about.

The corpus is vendored as a git submodule (tests/vendor/cedar-examples) pinned to upstream's
release/4.11.x branch, so bumping the pin is an explicit, reviewable commit — see
`git submodule update --remote acal-core/tests/vendor/cedar-examples`. A shallow/non-recursive
clone leaves the submodule directory empty, so every test here skips (not fails) when it is.
"""
from __future__ import annotations

from pathlib import Path

import pytest

VENDOR = Path(__file__).parent / "vendor" / "cedar-examples"

try:
    import cedarpy  # noqa: F401
    _HAS_CEDAR = True
except ImportError:  # pragma: no cover
    _HAS_CEDAR = False

pytestmark = [
    pytest.mark.skipif(not _HAS_CEDAR, reason="cedarpy not installed"),
    pytest.mark.skipif(
        not (VENDOR / "tinytodo" / "policies.cedar").exists(),
        reason="cedar-examples submodule not checked out (git submodule update --init)",
    ),
]

from acal_core.readers.cedar import CedarUnsupportedFeatureError, load  # noqa: E402

# Files that convert cleanly: the reader's whole job, on a policy nobody wrote for us.
CLEAN = [
    "tinytodo/policies.cedar",
    "tinytodo/policies-templates.cedar",
    "tinytodo-go/policies.cedar",
    "cedar-policy-language-in-action/GitApp/gitapp.cedar",
    "cedar-policy-language-in-action/PhotoApp/photoapp.cedar",
    "cedar-java-partial-evaluation/app/src/main/resources/policies.cedar",
    "oopsla2024-benchmarks/benches/tinytodo/cedar/tinytodo.cedar",
    "oopsla2024-benchmarks/benches/gdrive/cedar/policies.cedar",
    "oopsla2024-benchmarks/benches/gdrive-templates/cedar/policies.cedar",
    "cedar-example-use-cases/hotel_chains/templated/policies.cedar",
]

# Known gaps: real Cedar policies whose constructs have no ACAL mapping yet (nested
# attribute/record traversal, `has` on a non-variable base, a bare `Record` construct — see
# the gap table in docs/policy-language-expressiveness.md). Listed explicitly, rather than
# skipped, so that a cedar-examples update which starts passing one of these is a visible
# test failure demanding a look, not a silent gap that quietly stays open.
KNOWN_GAPS = [
    "cedar-example-use-cases/document_cloud/policies.cedar",
    "cedar-example-use-cases/github_example/policies.cedar",
    "cedar-example-use-cases/hotel_chains/static/policies.cedar",
    "cedar-example-use-cases/sales_orgs/static/policies.cedar",
    "cedar-example-use-cases/sales_orgs/templated/policies.cedar",
    "cedar-example-use-cases/streaming_service/policies.cedar",
    "cedar-example-use-cases/tags_n_roles/policies.cedar",
    "cedar-example-use-cases/tax_preparer/policies.cedar",
    "oopsla2024-benchmarks/benches/github-templates/cedar/policies.cedar",
    "oopsla2024-benchmarks/benches/github/cedar/policies.cedar",
]


@pytest.mark.parametrize("relpath", CLEAN)
def test_converts_cleanly(relpath):
    load(str(VENDOR / relpath))


@pytest.mark.parametrize("relpath", KNOWN_GAPS)
def test_known_gap_still_reproduces(relpath):
    """Not xfail: a silent pass here would hide either a real fix (update CLEAN) or a Cedar
    change that now hits a *different* unsupported construct (worth a fresh look either way)."""
    with pytest.raises(CedarUnsupportedFeatureError):
        load(str(VENDOR / relpath))


def test_clean_and_known_gaps_cover_every_cedar_file_in_the_corpus():
    """A new .cedar file landing upstream is silent unless something asserts total coverage."""
    all_files = {
        str(p.relative_to(VENDOR)) for p in VENDOR.rglob("*.cedar")
    }
    covered = set(CLEAN) | set(KNOWN_GAPS)
    missing = all_files - covered
    assert not missing, (
        f"New .cedar file(s) in the cedar-examples submodule are not classified: {missing}. "
        "Run it through acal_core.readers.cedar.load and add it to CLEAN or KNOWN_GAPS above."
    )
