# Session Context

## Current State (July 2026)

Work spans two repos:

- **`xacml-spec/`** (the OASIS spec repo) — spec issue #94 (PR #100) **merged to `main`** on
  2026-07-16. The transition is over: CI, the local spec clone, and the CLI defaults all now
  point at plain `main`, and `main` already contains the #94 fix. Issue #99's fix is committed
  directly to `main` and pushed (commit `0f6a887`, `origin/main` matches). Issue #102 (the
  sibling gap, same defect one type over) is implemented on branch
  `issue-102-notice-attributeassignment-unique`, not yet committed — see below.
- **`tools/`** — five packages: `acal-core`, `acal-convert`, `acal-explain`, `yacal-validator`, `jacal-validator`. 452 tests pass across all five, verified fresh (cold schema cache).

**Branch state.** Cedar is merged to `main` (PR #15). CI + the spec-#94 alignment merged via PR #16. `main` is the single source of truth.

**Two optional heavy dependencies** (→ heavy-runtime-dependencies-are-optional-extras): `acal-core[cedar]` (cedarpy, Cedar's parser) and `acal-explain[llm]` (litellm, for live model calls). Both import lazily and the suites mock/skip them. **CI must install `acal-core[dev]`** (which pulls cedarpy) or the Cedar tests silently skip.

**`acal-core/tests/vendor/cedar-examples`** is a git submodule (AWS's real-world Cedar corpus, pinned to upstream's `release/4.11.x` branch — cedar-examples has no tags). A plain `git clone` leaves it empty; `git submodule update --init` is needed or `test_cedar_examples.py` silently skips (same shape as the cedarpy guard above). CI checks it out via `submodules: true` on the checkout step.

## Most Recent Session (July 19, 2026) — Cedar reader closes 19/20 of the real cedar-examples corpus

Asked to add AWS's cedar-examples (tinytodo especially — its shared-list/team/private-task
model) to the test suite. Running the Cedar reader against the corpus first, before writing any
fixtures, was the right call: 19 of 20 real policies failed, including tinytodo itself.
(→ hand-written-fixtures-dont-find-the-bugs-real-corpora-do)

**First pass — three root causes, 1/20 → 12/20.** Multi-entity scope `in`
(`action in [Action::"A", Action::"B"]`) crashed with a raw `KeyError` — the reader only ever
handled the single-entity form, because no hand-written fixture had exercised the list form.
Expression-position `in`/`is` (`principal in resource.readers`, `resource is List`) had no
handler at all — scope-position `in`/`is` existed, but Cedar also allows both as ordinary
boolean expressions inside `when`/`unless`, and tinytodo's whole sharing model runs through
exactly this. (→ cedar-expr-in-is-reuse-scope-entity-designators)

**Second pass, asked explicitly to close the rest — 12/20 → 19/20.** The remaining 8 failures
all traced to one root cause, not eight: Cedar's `Record` type, showing up as multi-level
`.attr.attr` chains, bracket `["key"]` indexing (identical EST shape to `.attr`), and `has` on
a chained base. This **reversed a prior explicit decision** in `capabilities/cedar.yaml`, which
had declined to flatten records into dotted attribute names. Re-examining it: *reading* through
a chain is the same risk already accepted for the single-level case (`resource.owner` → flat
AttributeId `"owner"`), just applied once more per depth — not a new kind of risk, so there was
no real reason it had been declined beyond not yet having a corpus that needed it. Implemented
as one compound dotted AttributeId per chain, warned once per document.
(→ cedar-expr-in-is-reuse-scope-entity-designators)

Chasing that also **found a silent bug, not a crash**: `principal.job == Job::"internal"` (a
literal entity used as an ordinary `==` operand, not a scope/`in`/`is` target) was emitting
cedarpy's raw `{"__entity": {...}}` dict as the ACAL `Value` instead of Cedar's own canonical
`Type::"id"` string — a non-scalar `Value` that silently produced a document failing our own
JACAL schema. Caught by validating every converted file with jacal-validator, not just checking
the reader didn't raise. (→ validate-the-actual-document-not-just-that-the-reader-ran)

Genuinely one gap now remains, and it is not "record traversal" but a narrower thing:
tax_preparer builds an inline Record *literal* (`{organization: ..., ...}`) to pass to
`.contains(...)` — ACAL has no composite Value type to construct, so an ad-hoc structural value
has nowhere to land. All 19 passing conversions verified against jacal-validator at 39/39
constraints, not just "didn't throw."

cedar-examples is vendored as a submodule rather than copied files, specifically so upstream
drift is something CI catches rather than something nobody notices.

## Previous Session (July 19, 2026) — spec issue #99 fixed

Issue #99 (→ xsd10-unique-silently-skips-absent-optional-fields) had two independent authors
converge on the same fix, so this session implemented the union rather than picking a side: the
user's issue proposed (1) rewrite the violating examples to use `Apply`/`string-concatenate`
instead of two colliding `AttributeAssignmentExpression`s, and (2) close the XSD 1.0 enforcement
gap with an XSD 1.1 `xs:assert`; cdanger's review agreed with both and added that XSD-1.0-only
consumers need the equivalent as a Schematron rule, since `xs:assert` requires 1.1. All four
pieces landed: the spec doc's own worked example (all three of its XML/YAML/JSON renderings,
→ acal-core-md-line-numbers-are-cross-format-slots for how that renumbering was done safely),
`examples/acal-xpath/Rule3.{xml,json}`, the new `xs:assert` on `NoticeExpressionType`, and a
matching Schematron pattern.

A companion gap was found but deliberately **not** fixed in that pass: `NoticeType.AttributeAssignment`
(the resolved/runtime `Notice`, not the policy-time `NoticeExpression`) has the identical
`xs:unique`-cannot-see-absent-`Category` defect and the identical schema comment admitting it,
one type over in the same file. Scoped out to keep the #99 PR matching what #99 actually reports.
Filed as **spec issue #102** and then implemented in the same session on branch
`issue-102-notice-attributeassignment-unique`: the same three-part fix (`xs:assert` on
`NoticeType`, matching Schematron pattern, and — new this time, since #99 had no YACAL-side gap
to close — a `notice-attributeassignment-unique` entry in `acal-core-yaml-v1.0-constraints.yaml`).
No violating example needed fixing for #102 (`Notice` is a PDP-resolved runtime object, not
something that appears in hand-written policy examples), so the diff is schema/schematron/YACAL
only. The `CollectionPath` for the new YACAL entry uses the specific-path convention
(`$.Response.Result[].Notice[].AttributeAssignment`, matching `result-resultentity-category-unique`)
rather than `NoticeExpression`'s recursive-descent `$..` form, because `NoticeType` is referenced
from exactly one place in the object model (`ResultType.Notice`) versus `NoticeExpressionType`'s
several.

Validating any of this exposed that the repo has **no working schema-validation tooling** for
this XSD 1.1 file — see → xsd-1.1-assert-goes-after-attributes-and-needs-a-real-processor-to-check
for the workaround (an isolated minimal-schema check plus running the real XPath through Saxon
directly against real/synthetic example files), reused unchanged for #102.

#99 is committed and pushed to `main`. #102 is committed on branch
`issue-102-notice-attributeassignment-unique`, pushed, and PR #103 opened — awaiting review.

**Sandbox note**: `git push`/`gh pr create` against `origin` (an `ssh://git@github.com` URL)
fail here — no SSH key (`Permission denied (publickey)`), same failure mode noted in the
July 17 session for `git fetch`. Workaround used: temporarily `git remote set-url origin
https://github.com/oasis-tcs/xacml-spec.git`, push (`gh`'s stored token authenticates the
HTTPS push via the `osxkeychain` credential helper), then restore the original `ssh://` URL.
`gh issue create`/`gh pr create` work over the API regardless and don't need this. Also: `gh
pr create` requires the branch's tracked upstream to be the *named* remote `origin`, not a raw
URL — pushing straight to a URL (`git push -u https://...`) sets tracking to that URL and `gh`
then refuses with "you must first push the current branch to a remote," even though the push
itself succeeded.

## Previous Session (July 17, 2026) — spec PR #100 merged; transition closed

The prior session had left the tools deliberately split: CI and the validator tests tracked
the `issue-94-notice-id-nonunique` branch of `oasis-tcs/xacml-spec` (the direction the tools
were built for), while the `acal-convert`/validator CLI defaults already pointed at public
spec `main` (pre-#94) — a gap that was supposed to close itself once #100 merged.

**#100 merged 2026-07-16T23:43 UTC** (`gh pr view 100` confirms `state: MERGED`, merge commit
`6d0f17f`). Closing out the transition required three things, not just editing the CI ref:

- The local `xacml-spec` clone (`~/source/acal/xacml-spec`, the default source for validator
  tests via `ACAL_SPEC_DIR`) was 2 commits behind `origin/main` — cloning/fetching over `ssh`
  failed in this sandbox (no `publickey`), but the repo is public, so `git fetch
  https://github.com/oasis-tcs/xacml-spec.git main` worked and fast-forwarded cleanly.
- `.github/workflows/ci.yml` now checks out the spec's `main` directly instead of the
  transition branch.
- **The warm schema cache had to be cleared by hand** (`~/.cache/{yacal,jacal}-validator/schemas`)
  before re-running the suites. This is the same content-blind `source@branch` cache key called
  out in (→ a-content-blind-cache-makes-a-test-suite-lie): the local spec's `main` moved but the
  cache key did not, so a warm run would have silently kept serving pre-#100 schemas. Confirmed
  fresh-cache green after clearing: yacal 88/88, jacal 90/90.

No code change was needed on the CLI-default side — `yacal-validator`/`jacal-validator`
`config.py` already defaulted `branch` to `main`; the split was in the *content* of upstream
`main`, not in any tools-side branch string. That resolves for free now that #100 is merged.

## Previous Session (July 15, 2026) — first CI, and the cache that had been lying

The goal was to add CI. Standing it up exposed that the picture we thought was consistent was
not — and the reason is a lesson worth its own entry (→ a-content-blind-cache-makes-a-test-suite-lie).

**The validators' green was a cache artifact.** They cache resolved spec schemas keyed by
`source@branch` with no content check, so a changed local spec kept serving stale schemas.
Warm-cache runs reported `yacal 88/88, jacal 90/90` all session; the true fresh-cache state was
`85/88` and `82/90`. Every "452 passing" report made against a warm cache was fiction. A fresh
clone — or CI's empty-cache runner — is the only trustworthy signal.

The masked failures were two independent, pre-existing drifts:

- **Notice-Id uniqueness (#94).** Spec PR #100 removed the requirement that notice Ids be unique.
  Six error fixtures asserting the old behaviour were stale; they moved to the *valid* sets and
  now affirmatively test that duplicates are permitted.
- **Stale XPath fixtures.** The jacal XPath failures were *not* the `ContextSelectorId` /
  `unevaluatedProperties` issue the code comment and the diary claimed — that diagnosis had gone
  stale. The real cause: the schema now models `PolicyDefaults`/`RequestDefaults` as arrays, but
  the jacal fixtures still used the pre-collection object shape (yacal's were already arrays). The
  `_patch_core_schema_shape_bugs` workaround was removed — a schema refactor had made it a dead
  no-op. (→ find-based-readers-drop-what-they-do-not-ask-for is a cousin: a workaround outliving
  the thing it worked around.)

**CI, and simulating it first.** The workflow runs all five packages on ubuntu 3.11/3.12, installs
acal-core[dev] first so cedarpy is present (with an import guard, or Cedar tests would skip), and
clones the spec at the #94 branch for the validators. A fresh runner has an empty cache, so the
masking above cannot recur. The whole workflow was simulated in a clean venv before committing —
which caught that acal-explain's litellm dependency would fail a fresh install and take the
package down with it. That became a real improvement rather than a workaround: litellm is now an
optional `[llm]` extra. (→ simulate-a-ci-workflow-in-a-clean-env-before-committing-it,
→ heavy-runtime-dependencies-are-optional-extras)

## Previous Session (July 14, 2026 — later) — Cedar import

Cedar is **not** the first spoke — ALFA, and XACML 2.0/3.0, are older spokes. It is the first
spoke *designed as one from the start*: the earlier spokes had the hub/spoke frame, the
capability matrix, and the presence/`--fail-closed` machinery **retrofitted** onto them this
session, after the fact, whereas Cedar was taken through the full `/import-model` process —
matrix-before-code, the datatype ladder, decisions-as-data — with the frame already explicit.
So it is also the first to exercise the interactive-decision machinery as data rather than as a
later addition.

The parser choice was the pivot: **Cedar parses itself.** `cedarpy` wraps Cedar's own Rust
parser and yields Cedar's official JSON AST (the EST), which the reader maps. Nothing here
re-derives Cedar's grammar, so our understanding cannot silently drift from Cedar's as the
language evolves — the failure mode a hand-written Lark grammar would have carried.

Every non-obvious mapping was settled by asking a tool, not by reasoning:

- **Combining** is an outer `deny-unless-permit` wrapping an inner `deny-overrides`. Cedar
  allows iff some permit matches and no forbid matches, else deny; the naive flat encoding
  silently turns every `forbid` into a no-op. (→ combining truth table in the expressiveness doc)
- **Missing-attribute presence** was verified against Cedar's *own evaluator*: a `forbid`
  whose attribute is absent errors, is skipped, and the request is **allowed**. Cedar fails
  open. The reader reproduces that (`MustBePresent: false`) and reports it, rather than
  silently hardening. (→ presence-semantics-must-be-explicit)
- **Datatypes** walk the ladder the matrix defines: `decimal → double` warns (approximate),
  `ipaddr`/`record` hard-error naming the one YAML line that would map them. The ladder is
  now actually wired into the reader, not just described. (→ datatype-resolution-ladder)

**The presence work closed a live bug in ALFA**, not just a Cedar decision. ALFA omitted
`MustBePresent` entirely, so its converted deny rules fell back to a schema default and could
fail open with no diagnostic. It now states presence explicitly (false — faithful to ALFA's
XACML 3.0 lineage) and honours `--fail-closed`. A cross-reader invariant test now fails if any
reader emits a synthesized designator without a `MustBePresent` key.

`--fail-closed` runs through both CLIs as the declared, opt-in deviation for users who want a
hardened policy — the first concrete instance of a captured decision becoming a flag.

Also cleaned up: PR #9's merge had committed **unresolved conflict markers** into this very
file. Resolved to the July-14 rewrite, dropping the stale pre-rewrite duplicate.
(→ merge-conflict-markers-can-be-committed)

## Previous Session (July 14, 2026 — earlier)

### Pre-Cedar audit — five gaps, three of them shipped bugs

Asked "what else should we fix before Cedar", the honest answer required an audit rather than
a recollection. It found five things, and the audit paid for itself several times over.

**The converter was emitting documents our own validator rejects.** An XACML 3.0 policy with
no `Version` attribute — optional in XACML — produced `Version:` as a YAML null, which YACAL
prohibits. Omitting it wasn't the fix either, since ACAL *requires* Version. The faithful
answer is the XACML schema default: an absent Version *means* "1.0".
(→ converter-output-must-be-fed-to-our-own-validator)

**The silent-drop class was wider than `Rule`.** `_bundle`, `_request`, `_response`, `_result`,
`_status`, and `_notice_expr` were all `find()`-based with no allowlist. `_result` was
discarding Obligations, AssociatedAdvice, Attributes, and PolicyIdentifierList outright — an
obligation lost from a Result is an enforcement requirement the PEP never sees. All of them now
raise. (→ unconverted-constructs-raise-they-do-not-vanish)

**`Bundle` and `Response` had zero fixtures.** Written; they worked.

**My own capability matrix was wrong.** `xacml.yaml` asserted XACML cannot express
`SharedVariableDefinition`. XACML 4.0 carries it natively — the reader parses it.
(→ capability-claims-must-be-checked-against-the-reader)

**Exportability was never wired into acal-explain**, despite being half of a decision taken in
the grill session. Now shipped: `export_gaps()` lives in acal-core (it is the export tool's
precondition gate in embryo), and explain asks the round-trip question automatically.

### The model correction that made it all cohere

The user's framing, and it is the right one: **ACAL is a hub, not a dialect of XACML.** Three
native serializations — XACML 4.0 (XML), YACAL, JACAL — and everything else, *including XACML
2.0 and 3.0*, is a foreign spoke importing into it.

This dissolved the matrix problem: native dialects need no matrix (they express all of ACAL by
construction), and foreign dialects each get their own. The code had believed this all along —
`_remap` is False for V4_0 because 4.0 identifiers *are* ACAL URNs — but the registry hadn't
caught up. (→ acal-is-a-hub-not-a-xacml-dialect)

It also exposed a live misconception: **XACML 4.0 output is serialization, not export**, and it
is not blocked by Saxon licensing — that argument conflates writing XML with validating it, the
very conflation this project already caught once for reading. An XACML 4.0 writer belongs beside
the YACAL/JACAL writers, would enable `XACML 4.0 → YACAL → XACML 4.0` round-trip tests, and
closes issue #1 outright. (→ xacml-writer-is-not-blocked)

## Previous Session (July 13, 2026)

### XACML 4.0 fixtures — and the shipped bug they exposed

Closing GitHub issue #2 (cdanger's XACML → JACAL request) meant verifying the claim first.
XACML 4.0 conversion *worked*, but `tests/fixtures/xacml4/` was an **empty directory** and no
test referenced 4.0 at all — the support was real but had never been executed.
(→ empty-fixture-directory-is-a-coverage-lie)

Writing the missing 4.0 fixtures immediately turned up a shipped, security-relevant bug —
**in XACML 3.0, not 4.0**. `_rule()` never read `<Target>`. A Rule's Target scopes when the
rule applies, so a rule that permitted only doctors was converting into a rule that permitted
**everyone**, across all three XACML versions. The root cause is structural: `_rule()` is
built from targeted `find()` calls with no allowlist, so any element it does not explicitly
ask for disappears in silence. `Policy` already had such a guard, which made the codebase look
like it enforced no-silent-drops when `Rule` did not.
(→ find-based-readers-drop-what-they-do-not-ask-for)

Fixed by reading `Target` in `_rule()` and adding a `_RULE_KNOWN_CHILDREN` allowlist that
raises on anything unrecognised. Issue #2 is now closeable on verified behaviour rather than
an assumption.


### Direction: the next languages, and why not Rego

A `/grill-me` session set the next phase. The imports are **Cedar, then AWS IAM JSON**. Rego
is deferred, and the reason is worth keeping: the stated criterion was "start with what
imports cleanly," and this project's own expressiveness doc already calls Rego a
Turing-complete *program, not a document* whose parser is "a non-trivial dependency." Rego
lost to our own prior analysis rather than to a preference. A Rego reader would have to
define and police a recognized *subset* of the language — a different kind of problem from
every import so far, and one worth taking deliberately rather than by momentum.

The long-term goal list (ACAL export, Rego, the provenance spec extension) now lives in
`ROADMAP.md` and GitHub issues rather than in this file. The diary is a working log; a
roadmap outside contributors cannot read is not a roadmap.

### The delta list became executable

The plan had been to audit each language for what it can and cannot export, as prose. Prose
cannot gate a tool, and the export tool is the entire point of the audit — so the gap
analysis now lives in `acal-core/capabilities/<lang>.yaml`, keyed by ACAL feature, with three
consumers. Matrices for ALFA and XACML were written from the existing prose; Cedar's gets
authored by `/import-model` before its reader exists.
(→ capability-matrix-is-the-delta-list)

### acal-explain now reads every source language

A user feature request — "explain should not export a file, simply explain" — turned out to
mean: *don't make me materialize a converted `.yaml` just to explain a `.alfa`*. It is now
`acal-explain policy.alfa`, converting in memory and writing nothing but the explanation.
This reverses a deliberate June decision (→ acal-explain-reads-every-source-language), and
explain also gained import-fidelity reporting: what the source language could not express
faithfully in ACAL, surfaced in all three output formats and fed to the LLM so the
observations account for it.

The fidelity information travels *beside* the document, never inside it — stamping provenance
into the ACAL doc would make acal-convert emit output that fails our own validators.
(→ conversion-report-never-enters-the-document)

### Four defects surfaced along the way

- The `/import-model` skill pointed at pre-refactor paths and would have failed its own Phase 0 check on Cedar. Repointed at acal-core; taught about the registry and the capability matrix.
- `policy-language-expressiveness.md` existed twice **and had forked** — each copy held content the other lacked. It was nearly deleted as a duplicate. (→ check-for-fork-before-deleting-a-duplicate)
- A format was declared in five places, which is why the registry now exists. (→ central-language-registry)
- **A real bug:** the ALFA `xpath` datatype is documented as disposition (b) — warn by default, error under `--strict`. It never errored, because the warning fires in symbol collection and `_collect_symbols` never received the `strict` flag. `--strict` is what a user turns on when they need conversion to *fail* rather than approximate; it was silently not keeping that promise. (→ strict-must-be-threaded-through-every-pass)

### Spec issue #94 (earlier in July)

The notice-`Id` uniqueness constraint was reversed across all six artifacts where it had been
encoded. A notice `Id` names the obligation's *meaning*, not an occurrence.
(→ notice-id-is-a-concept-identifier). Branch is unmerged pending TC agreement — it is a
normative change. Probing a neighbouring constraint as a control turned up a long-standing
enforcement gap, filed as spec issue #99.
(→ xsd10-unique-silently-skips-absent-optional-fields)

## Open Items for Next Session

**Immediate:**

- **Push the `ci.yml` ref change and confirm CI green** against real spec `main` (not yet
  pushed/run as of this session — the change is local only).
- **AWS IAM JSON** is the next spoke (per ROADMAP), and the second matrix the interactive-decisions
  abstraction should be drawn from before `acal-decisions` starts.
- Retrofit the datatype ladder onto XACML and ALFA — the XACML reader still remaps datatypes by
  unchecked regex passthrough. (→ datatype-resolution-ladder)
- **Consider content-hashing the validators' schema cache** (or a `--refresh` in test setup). The
  current `source@branch` key is what let stale schemas mask real failures for a whole session.
  (→ a-content-blind-cache-makes-a-test-suite-lie)

**Spec:**

- **Issue #99**: fixed, committed, and pushed to `main` directly. Done.
- **Issue #102**: fix implemented on branch `issue-102-notice-attributeassignment-unique` in
  `~/source/acal/xacml-spec` — needs commit, push, and PR opened next session (or later this
  one).

**Known limitations, deferred:**

- **Cedar Record *literal* construction** (`{organization: ..., location: ...}` built as a
  value, e.g. tax_preparer's `.contains({...})`) is the one remaining gap in the cedar-examples
  corpus. ACAL has no composite Value type, so this is a harder problem than the attribute-chain
  *reading* case (solved this session) — it would need ACAL itself to grow a structural value
  type, not just a reader change.
- **Nested attribute resolution**: `user.clearance`, `medicalrecord.patientId` etc. still produce unresolved-attribute warnings because nested namespace paths aren't walked. Surfaces in analyzer output as `unresolved_attrs`, and now also as import-fidelity notes.
- **Infix comparison type dispatch**: `>`, `<`, `>=`, `<=` default to `integer-*` regardless of attribute type; `==` defaults to `string-equal` for non-bag scalars. Should dispatch on the declared type.
- **Streaming output for acal-explain** (`--stream`).
- **acal-explain end-to-end smoke test** against a real LLM (CI-gated).
- Populate the root `README.md` (still empty). `acal-core/README.md` exists.
- File the upstream schema/catalog bugs (see prior sessions; still unfiled).
- Publish to PyPI when stable.

## Key Diary Files

- [architectural_decisions.md](architectural_decisions.md) — design principles and non-negotiable patterns
- [lessons_learned.md](lessons_learned.md) — anti-patterns and hard-won insights (most recent at top)
