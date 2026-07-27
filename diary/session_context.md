# Session Context

## Current State (July 2026)

Work spans two repos:

- **`xacml-spec/`** (the OASIS spec repo) — spec issue #94 (PR #100) **merged to `main`** on
  2026-07-16. The transition is over: CI, the local spec clone, and the CLI defaults all now
  point at plain `main`, and `main` already contains the #94 fix. Issue #99's first fix is committed
  directly to `main` and pushed (commit `0f6a887`, `origin/main` matches); its **part 2** — the
  TC's decision to lift the `(AttributeId, Category)` uniqueness constraint entirely, plus JACAL
  XPath example schema fixes — is committed on branch `issue-99-part2-and-example-schema-fixes`
  (see the July 25 session). Issue #102 (the
  sibling gap, same defect one type over) is committed on branch
  `issue-102-notice-attributeassignment-unique`, pushed, PR #103 open, awaiting review — not
  yet merged to `main`.
  An external OASIS TC Administration pub-check validation report (2026-07-17, against the
  published `xacml/core/v4.0/csd01` bundle and the sibling ACAL/JACAL bundles) surfaced 8
  documentation-level findings, filed as issues #104-#111. Three (#105, #107, #110) are fixed
  on branch `issue-105-107-110-pubcheck-fixes`, **branched off `main` rather than off #102's
  branch** — #102 is expected to merge separately, so this PR shouldn't carry that dependency —
  not yet committed as of this entry. See below.
  Separately, issue #101 (cdanger's proposal to remove `RequestEntityReferenceType` as an
  unnecessary wrapper) **merged to spec `main` as PR #113 on 2026-07-23** — which is what turned
  `tools/` CI red four days later, since CI resolves spec schemas fresh from `main` (see Most
  Recent Session).
- **`tools/`** — five packages: `acal-core`, `acal-convert`, `acal-explain`, `yacal-validator`, `jacal-validator`. 512 tests pass across all five, verified fresh (cold schema cache).

**Branch state.** Cedar is merged to `main` (PR #15). CI + the spec-#94 alignment merged via PR #16. `main` is the single source of truth. Issue #12's `Metadata` provenance work sits on `feat/metadata-provenance` as open PR #20, with `main` merged in for the spec-drift CI fix.

**CI tracks the spec's `main` with a cold schema cache, and that is load-bearing.** It means an
upstream spec merge can turn `tools/` red without anything here changing — which is the intended
early-warning signal, not a flake. Read a sudden CI failure as possible spec drift before
suspecting the branch under test.

**Two optional heavy dependencies** (→ heavy-runtime-dependencies-are-optional-extras): `acal-core[cedar]` (cedarpy, Cedar's parser) and `acal-explain[llm]` (litellm, for live model calls). Both import lazily and the suites mock/skip them. **CI must install `acal-core[dev]`** (which pulls cedarpy) or the Cedar tests silently skip.

**`acal-core/tests/vendor/cedar-examples`** is a git submodule (AWS's real-world Cedar corpus, pinned to upstream's `release/4.11.x` branch — cedar-examples has no tags). A plain `git clone` leaves it empty; `git submodule update --init` is needed or `test_cedar_examples.py` silently skips (same shape as the cedarpy guard above). CI checks it out via `submodules: true` on the checkout step.

## Most Recent Session (July 27, 2026) — CI red from upstream spec drift, not from Node.js

CI was failing on both matrix jobs, and the visible Node.js 20 deprecation notices looked like
the cause. They were not: GitHub was already force-running those actions on Node 24, so those
lines were warnings and the exit-code-1 came from real test failures underneath them. The actual
cause was upstream spec drift — CI checks out `oasis-tcs/xacml-spec@main` fresh every run, and
spec PR #113 (issue #101) merged on 2026-07-23, after the last green run on 07-20.

PR #113 removed `RequestEntityReferenceType`, retyping
`RequestReferenceType.RequestEntityReference` directly as `LocalIdentifierType [1..*]` — so
`[{Id: subject-one}, …]` became `[subject-one, …]` across all representations. Nothing in
`tools/` source hardcoded the old shape (the constraint engines are catalog-driven and the path
evaluator already handled bare-scalar arrays), so the repair was confined to fixtures, one new
catalog `Kind`, and one test reclassification:

- Nine multi-request fixtures flattened to the new shape, across both validators.
- The catalog's new `uniqueByValue` kind implemented in both constraint engines. It is required
  in `jacal-validator` even though the JSON schema now catches that case structurally, because
  the valid-fixture tests assert `constraints_skipped == 0`.
- JACAL's duplicate-id fixture moved from the constraint-invalid set to the structural-invalid
  set, because the spec gave the JSON schema `uniqueItems: true` and the YAML schema nothing
  equivalent (→ a-spec-change-can-move-an-error-between-validation-layers).

The failure was reported as five tests in `yacal-validator`; it was actually nine, because the
job aborted before `jacal-validator` ran and hid four identical failures
(→ sequential-ci-steps-mask-parallel-failures). The test steps now carry
`if: ${{ !cancelled() }}` so every package reports.

Separately, and genuinely worth doing rather than as the fix: `actions/checkout` and
`actions/setup-python` were bumped off their Node 20 majors to `v7`, retiring the deprecation
warnings before they become hard failures.

**Open question for the spec, not for `tools/`**: the JSON schema enforces
`RequestEntityReference` uniqueness structurally while the YAML structure schema leaves it to
the constraint catalog. The two hub serializations reject the same document at different layers
with different rule-ids. That asymmetry may be deliberate, but it is worth raising upstream.

## Earlier Session (July 27, 2026) — Issue #12: `Metadata` provenance implemented on `feat/metadata-provenance`

Issue #12 asked the XACML TC for an extension point so conversion fidelity could travel with the
document. cdanger's reply converged the design and this session implemented the agreed part in
`tools/`, on branch `feat/metadata-provenance`, for a PR.

**The design settled through disagreement, and the disagreements are the substance.** cdanger
first suggested `PolicyIssuer` as the carrier; it cannot be, because §7.4 requires a PDP without
the Administration and Delegation profile to error or return `Indeterminate` merely on
encountering it (→ a-field-that-looks-inert-may-carry-an-error-clause). He then proposed
generalising the earlier `Provenance` sketch to a `Metadata` container — right, and accepted:
he needs the same slot for author, timestamps and tags, having been using `PolicyIssuer` for
them himself. Provenance is now a URN namespace inside `Metadata`, not a type. His `AttributeType`
reuse was also accepted over the sketch's bespoke `NamedAttributeType`, since `dateTime`
timestamps are a real need and pinning values to `string` would have forced an encoding
convention on every non-string fact.

Two of his suggestions were declined with reasons, and one correction was to our own earlier
sketch. The JSON `DataType` (`urn:com.github.acal-community.tools:1.0:data-type:json`) was
declined: a datatype participates in the type system, and a metadata blob wants a media-type
hint, not a type — the report rides the default `string` datatype and the `AttributeId` defines
its format. Moving `Description` into `Metadata` was declined for 1.0 — it breaks every existing
document and reader and creates two places to look with no precedence rule — while conceding the
strong form of his point, that `ShortIdType`, `ShortIdSetType` and `BundleType` have no
`Description` at all. Our own sketch had said `PolicySetType`, an XACML 3.0 habit; no such type
exists in ACAL 1.0.

**Two attachment points were added to his list.** `BundleType`, because origin is a fact about the
document rather than about any policy in it, and stamping it per-policy goes actively wrong once
bundles of different origin are merged. And `ShortIdType` — his ALFA point, sharpened: an ALFA
attribute declaration carries name, URI, category and datatype, `ShortIdType` holds only the first
two, and our reader currently resolves the rest inline into every designator while emitting no
`ShortIdSet`, so the author's alias survives in no form at all.

**What shipped**: `acal_core.metadata` (build, attach, read back), `acal-convert --provenance`,
`Metadata` round-tripping through the XACML reader, and README documentation. The flag is opt-in
and says why: output carrying `Metadata` fails `yacal-validate` until the TC adopts the change
(→ provenance-rides-a-metadata-property-behind-an-opt-in-flag).

**Open**: the drafted reply to cdanger is written but **not yet posted** to issue #12. The
`ShortIdType` and `ShortIdSetType` attachment points are argued but not implemented — nothing
emits a `ShortIdSet` from ALFA yet, which is the prerequisite. `RuleType` metadata is deferred.

## Earlier Session (July 26, 2026) — Profile backlog: MDP (#59) analysed and parked, HRP (#119) opened, content-selector gap (#118) filed

No code or specification text changed this session. It was an analysis session over the two
XACML 3.0 profiles ACAL has not yet ported, on branch `issue-99-part2-and-example-schema-fixes`
(HEAD `a8c41cb`, working tree clean throughout).

**Issue #59 (Multiple Decision Profile) — analysed, deliberately parked.** The issue as filed
reads as a two-line rename, and is not. Its own text is stale twice over: the rename landed as
`RequestEntity`/`RequestEntityReference`, not `RequestCategory`/`RequestCategoryReference`, and
#101 later removed `RequestEntityReferenceType` so the reference is now a bare
`LocalIdentifierType` value. More importantly the renames touch **one of the profile's five
schemes**. Two schemes (`scope`, `xpath-expression`) are blocked on the Hierarchical Resource
Profile; three (repeated categories, reference, combined decision) plus the mandatory conceptual
model are unblocked and could ship as an ACAL 1.0 MDP on their own. Recommendation recorded: split
#59 that way. A comment to that effect is on the issue; the full analysis is **private**, at
`../issue-59-multiple-decision-profile-analysis.md` (the non-git parent of `xacml-spec/`), and is
written to be read cold.

**Issue #119 (Hierarchical Resource Profile) — opened.** HRP is the prerequisite: MDP consumes its
`content-selector` and its definition of hierarchy membership, while HRP depends on MDP only
softly (§1.1 assumes multi-node requests are already resolved, and says its functionality may be
layered directly on core). So HRP first. The issue leads with the breaking change
(→ single-datatype-per-ancestor-attribute) and its three migration paths, lists five verified
errata in the published CS02 (→ published-oasis-specs-carry-errata-resolve-dont-copy), and poses
four TC questions. Private analysis at `../hrp-acal-port-analysis.md`.

**Issue #118 (`content-selector`) — filed.** `urn:oasis:names:tc:acal:1.0:content-selector` is
used by all six `examples/acal-xpath/` files as the target of `XPathAttributeSelectorType`'s
`ContextSelectorId`, but is defined in no ACAL document — not in core §11.2.6, not in
`acal-xpath-v1.0.md` Annex D, not in any `*-identifiers.*` artifact. In XACML 3.0 it is defined in
HRP §5.1, which is how it fell through. Recommendation in the issue: define it in the ACAL XPath
Profile with the XACML URI as the deprecated identifier, which inverts the XACML 3.0 arrangement
(HRP would then reference it rather than define it) and must be stated as such.

**Bibliography debt found.** `[Multi]` (`acal-core-v1.0.md:6800`) and `[Hier]` (`:6768`) both cite
2010 Committee Drafts; both profiles reached **CS02 on 18 May 2014**
(→ check-for-a-later-oasis-stage-before-porting). The stale citations are duplicated in
`acal-core-xml-v4.0.md`, `acal-core-json-v1.0.md`, `acal-core-yaml-v1.0.md`, `acal-xpath-v1.0.md`
and `acal-jsonpath-v1.0.md`. Also noted for a future cleanup: `acal-core-v1.0.md:3484` still
describes `RequestEntityReference` as having an `Id` property, which #101 removed.

**Standing commitment recorded**: every profile ships a Reviewer's Guide, and its absence is an
audit finding (→ every-profile-ships-a-reviewers-guide). Today only ACAL Core has one
(`acal-core-yaml-v1.0-reviewer-guide.md`, YACAL-specific). HRP's guide is the next one to write,
and it must lead with the ancestor-attribute narrowing.

**PAUSED at end of session, awaiting the TC.** The profile track stops here until #119's four open
questions are answered: (1) adopt the single-datatype narrowing on ancestor attributes, and which
migration path is *the* recommendation; (2) resolve HRP erratum 1 in favour of the body's
`URI-node-id`/`attribute-node-id` spelling; (3) keep or drop §2.2.1's `xpointer` URI-reference
representation; (4) all three schemes in ACAL 1.0 or stage the ancestor-attribute one. Plus one
shared question that must be answered identically for both profiles: JSONPath counterpart for the
XML-document scheme, or XML-only?

**Resume order when the answers land**: read `../hrp-acal-port-analysis.md` §0 → check
`gh issue view 119 --comments` → re-verify the file:line citations (taken at `a8c41cb`;
`acal-core-v1.0.md` line numbers move) → draft `acal-hierarchical-v1.0.md` → its Reviewer's Guide →
then MDP from `../issue-59-multiple-decision-profile-analysis.md`, resuming at that file's Phase 1
Step 4.

**Mechanical work available meanwhile, needing no TC input**: refresh the `[Multi]`/`[Hier]`
bibliography entries from the 2010 CD-03s to the 2014 CS02s across all six spec documents; fix
`acal-core-v1.0.md:3484`; and report HRP CS02's five errata upstream as errata against the XACML
3.0 document itself.

**Nothing in `xacml-spec` changed this session** — the working tree was clean at `a8c41cb`
throughout. The output was three issues (#118, #119, and a comment on #59), two private analysis
files, and these diary entries.

## Previous Session (July 25, 2026) — Issue #99 part 2: lift the notice (AttributeId, Category) uniqueness constraint; fix the JACAL XPath examples

Two independent bodies of work landed together on branch
`issue-99-part2-and-example-schema-fixes`, both surfaced while reviewing the PR #116 merge.

**Lifting the uniqueness constraint.** Issue #99's earlier fix constrained notice attribute
assignments to be unique by `(AttributeId, Category)`; the TC (cdanger's option 3, agreed with
steven-legg's analysis) concluded the constraint should be lifted entirely, matching XACML 3.0,
which imposed no such rule on obligation/advice assignments. Beyond the precedent, the constraint
was self-contradictory as written: §7.29 already states that an `AttributeAssignmentExpression`
evaluating to a bag produces one `AttributeAssignment` per bag value — all necessarily sharing the
same `(AttributeId, Category)` pair — so `NoticeType` could not both require the pair to be unique
and admit the assignments its own evaluation rule generates. The constraint was removed from every
artifact that carried it: the model doc (§7.26, §7.29), the XSD (`xs:unique` identity constraints
plus the XSD 1.1 `xs:assert` blocks that covered the absent-Category case for #99 and #102), the
Schematron (both `ACAL_constraint_on_Notice*` patterns), the YACAL constraint catalog (two
`uniqueByProperty` rules), the JACAL JSON Schema (two now-moot ArrayExt `uniqueKeys` TODOs), and
the prose in the YACAL doc and adoption guide. The UML field declarations dropped both `{unique}`
and the OCL key clause, becoming `{ordered, nonunique}` to match the sibling collections
(→ notice-attribute-assignments-are-ordered-nonunique). The Rule 3 walkthrough kept its
`string-concatenate`/`string-one-and-only` form but its justification was rewritten — it had been
justified by the very constraint being removed; it is now recommended practice on
steven-legg's actual grounds (assignment/bag order is not guaranteed preserved, so composing the
value in the policy leaves no ambiguity for the PEP).

**Fixing the JACAL XPath examples.** All four `examples/acal-xpath/*.json` files failed validation
against the core schema composed with the XPath and JSONPath profiles, for two distinct reasons:
`Apply` used `Expression` for its argument list where `ApplyType` defines `Argument` with
`additionalProperties: false` (27 sites), and `PolicyDefaults`/`RequestDefaults` were JSON objects
where the schema requires an array (4 sites). This generalises the one-site fix cdanger applied in
9dfcc05, which had left Rule3.json internally inconsistent. The XML counterparts need no equivalent
fix — XML flattens Defaults through substitution groups and Apply arguments are positional
elements, so neither defect can arise there. These went unnoticed because
`acal-xpath-json-v1.0-schema.json` is `$defs`-only with no root constraints, so validating an
instance directly against it silently passes anything
(→ defs-only-schema-validates-nothing). Argues for a CI validation step using a composed root
schema.

Committed on branch `issue-99-part2-and-example-schema-fixes` this session.

## Previous Session (July 20, 2026) — Issue #101: RequestEntityReferenceType removed as an unneeded wrapper, across every representation

cdanger proposed on issue #101 that `RequestEntityReferenceType` — a wrapper object holding
exactly one property (`Id`) — be eliminated in favor of typing
`RequestReferenceType.RequestEntityReference` directly as `LocalIdentifierType [1..*]
{unordered, unique}`. The proposal matches a convention the model doc already states explicitly
(§3182: primitive-typed multi-valued unique properties use `{unique}` alone, no wrapper object,
no OCL) — the wrapper only existed because two earlier renames (#18, #62) carried it forward
unchanged rather than asking whether it was still needed. Implemented on branch
`issue-101-requestentityreference-simplify`, off `main` — checked first that neither open PR
(#103's Notice/#102 fix, #112's pub-check fixes) touches the same lines; both only append content
elsewhere in the shared files, so no rebase risk.

The change had to land in every representation the ACAL model has: the ACAL model doc itself
(renumbering §7.40-48 down by one after the section merge), XML schema + Schematron (dropping
`RequestEntityReferenceType`, fixing the `xs:keyref`/`xs:assert` that read the now-gone `@Id`
attribute), YACAL doc + its constraint catalog + its JSON-Schema structural file — and, missed on
the first sweep and only caught because the diff got a second look, the JACAL JSON Schema
(`acal-core-json-v1.0-schema.json`). The initial stray-reference grep filtered by extension
(`.md`, `.yaml`, `.xsd`, `.sch`) and simply never added `.json` to the list.
(→ sweep-every-representation-file-extension-not-the-ones-you-remember)

The YACAL constraint catalog had no existing `Kind` for "a list of scalars must be unique by their
own value" — every existing `uniqueByProperty` rule assumes list items are objects with a named
key. Added `uniqueByValue` to the catalog's own `RuleKinds` registry rather than force-fitting
`uniqueByProperty` with an absent `KeyProperties`. The JACAL JSON Schema fix reused a pattern
already present in the same file for `ShortIdSetReference`: plain `"uniqueItems": true` for a
primitive-typed array, rather than the `ArrayExt` `uniqueKeys` vocabulary TODO reserved for arrays
of objects.

Not yet committed as of this diary entry.

## Previous Session (July 20, 2026) — OASIS pub-check report triaged into 8 issues; 3 fixed

Given an external OASIS TC Administration pub-check validation PDF (`oasis_pub_check.py`,
run 2026-07-17 against the published `xacml/core/v4.0/csd01` bundle plus a corpus summary
covering all nine published stage trees across the ACAL/JACAL/XACML bundles). The report
itself only gives full per-condition detail for the one tree it's titled for (XACML Core);
the other eight trees get only aggregate blocker/warning counts. Before filing anything, every
finding was traced back to an actual line in the current source — not taken on the report's
word — which changed the shape of the work in two ways.
(→ pub-check-reports-validate-the-frozen-publish-not-trunk)

**Two of the ten findings turned out to be already fixed.** The "Latest-stage URL points at
`/csd01/` instead of the version root" blocker and the "horizontal rule between logo and
title" warning both trace to `git blame` showing the offending lines were rewritten by commit
`a5101e4d` (2026-03-23) — a front-matter template refactor that happened *after* CSD01
published (2026-02-22) but is already in trunk headed for CSD02. The pub-check tool validated
the immutable, already-published CSD01 bundle, which can never reflect a post-publish trunk
fix. Filing issues for these would have been noise with nothing to action, so they were
deliberately **not** filed.

**The other 8 were filed as one issue per defect class** (#104-#111), matching the report's
own framing that these are template-level patterns repeated across documents — fixing the
shared cause once clears the finding everywhere it appears, rather than filing per-document.
Notable finds while grounding these in source:
- The `#XS`/`#entities` "unresolved internal anchor" blockers (#106, #107) turned out to be two
  different bugs wearing the same symptom: `#XS` is a case mismatch (pandoc lowercases
  auto-generated heading ids; the citing links used uppercase), while `#entities` cites a
  `[ENTITIES]` bibliography entry that was never written into `acal-core-xml-v4.0.md` at all
  (the sibling `acal-core-v1.0.md` has the citation text; the XML doc never got it copied over).
- The XPath profile's fence-collapse blocker (#109) isn't really a content bug — it's a latent
  build-script footgun: `acal-xpath-v1.0.md`'s `{.numberLines}` fence syntax only parses under
  `pandoc/mkdocs.sh --number-lines`, and nothing enforces that flag for this specific document.

**Fixed this session (#105, #107, #110), on `issue-105-107-110-pubcheck-fixes` off `main`:**
- **#105** — a malformed CACAO citation link (stray backslash-escapes in the visible text vs.
  the actual href) had been copy-pasted identically into 5 source files. One clean link,
  applied 5 times.
- **#107** — added the missing `[ENTITIES]` bibliography entry to `acal-core-xml-v4.0.md`,
  copied from `acal-core-v1.0.md`'s existing citation of the same XACML v3.0 Related and Nested
  Entities Profile, in correct alphabetical position.
- **#110** — replaced dual `[url](url)` IPR/Trademark boilerplate links with descriptive anchor
  text (`[XACML IPR Policy]`, `[OASIS Trademark Policy]`), matching the pattern
  `acal-core-v1.0.md`'s IPR line already used, applied consistently across all 5 docs.

Not yet committed as of this diary entry — see Open Items.

## Previous Session (July 19, 2026) — Issue #5 (XACML→YACAL): already wired, four bugs found validating it

Asked to work through open GitHub issues starting with #5 ("Mechanism to convert XACML 4.0
and 3.x to YACAL 1.0"). No new mechanism was needed — `acal-convert --from xacml --to yacal`
already does this generically (the hub/spoke architecture makes it one reader + one writer,
not a per-pair mechanism) — but nobody had run the *full* xacml3/xacml4 fixture corpus through
both the CLI and yacal-validator/jacal-validator end to end. Doing that (not just running the
reader's own unit tests) surfaced four real, previously-invisible bugs, each following the same
shape as the Cedar entity-literal bug from earlier this session: the reader ran without error,
but the document it produced violated ACAL's own spec.
(→ validate-the-actual-document-not-just-that-the-reader-ran)

1. **`_rule()` emitted a bare `Target` key on Rule.** `RuleType` in the ACAL 1.0 spec has no
   `Target` property at all — only `PolicyType` does. This was the July 13 session's fix for
   rule-target being silently dropped (→ acal-spec-has-no-rule-level-target): reading the
   Target was right, emitting it as its own key was not. It is now AND'd into `Condition`,
   matching how the spec actually expresses "applies iff Target matches and Condition holds."
2. **A test fixture had a schema violation of its own**: `bundle.xml`'s
   `SharedVariableDefinition` omitted `Version`, which the XACML 4.0 schema declares
   `use="required"` on that element (unlike Policy/PolicySet, which default it to "1.0" only
   on 2.0/3.0). The reader's behavior (surface a missing required attribute downstream rather
   than fabricate one) was correct; the fixture was wrong.
3. **`PolicyReference`/`PolicyIdReference` used the wrong key.** `_policy_id_ref` (XACML
   2.0/3.0) and `_policy_ref_4` (XACML 4.0) both emitted `PolicyId`, but `PolicyReferenceType`
   is a `PatternMatchIdReferenceType` (→ `IdReferenceType`), which uses `Id` — `PolicyId`
   belongs to the *referenced* Policy/PolicySet, not the reference. The XACML 4.0 XML itself
   also uses an `Id` attribute on `<PolicyReference>`, not `PolicyId` as the reader (and its
   own fixture) had assumed — both were wrong in the same way, which is exactly why nothing
   caught it. Every PolicyReference this tool has ever emitted was misnamed.
4. **`RequestAttribute.Value` was unwrapped to a bare scalar for a single value.**
   `AttributeType.Value` is a `ValueArray` unconditionally in the spec — there is no
   scalar-or-array alternative. `_request_attribute` special-cased `len(values) == 1` to emit
   a bare string; now it always emits the array.

All four are fixed, with new fixtures/tests covering paths that had zero coverage before
(XACML 3.0's `PolicySet` + `PolicyIdReference`, Rule with both Target and Condition). Every
xacml3/xacml4 fixture meant to convert successfully now does, and passes yacal-validator and
jacal-validator at 39/39 (or INCOMPLETE only where a `PolicyReference` legitimately points
outside the document — not a bug). Issue #5 is ready to close on verified behavior.

## Previous Session (July 19, 2026) — Cedar reader closes 19/20 of the real cedar-examples corpus

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

- **Post the drafted reply on issue #12** — written this session, not yet posted. Everything on
  `feat/metadata-provenance` implements the agreed half of it; cdanger has not yet seen the
  declines (the JSON `DataType`, `Description` staying put) or the two added attachment points.
- **Emit `ShortIdSet` from the ALFA reader.** The prerequisite for `ShortIdType` metadata, and
  worth doing on its own: ALFA attribute declarations currently resolve inline into every
  designator and the author's alias survives nowhere.
- **Raise the `RequestEntityReference` uniqueness asymmetry upstream**: spec PR #113 gave the
  JSON schema `uniqueItems: true` but left the YAML structure schema relying on the constraint
  catalog, so the two hub serializations reject the same duplicate at different layers.
- **AWS IAM JSON** is the next spoke (per ROADMAP), and the second matrix the interactive-decisions
  abstraction should be drawn from before `acal-decisions` starts.
- Retrofit the datatype ladder onto XACML and ALFA — the XACML reader still remaps datatypes by
  unchecked regex passthrough. (→ datatype-resolution-ladder)
- **Consider content-hashing the validators' schema cache** (or a `--refresh` in test setup). The
  current `source@branch` key is what let stale schemas mask real failures for a whole session.
  (→ a-content-blind-cache-makes-a-test-suite-lie)

**Spec:**

- **Issue #119** (port the Hierarchical Resource Profile to ACAL 1.0): opened, unstarted,
  **PAUSED awaiting TC**. Four TC decisions gate the document — the single-datatype narrowing on ancestor attributes and its
  recommended migration path, the erratum-1 identifier spelling, whether §2.2.1's `xpointer`
  representation survives, and the JSON-content story (which must match whatever #59 does).
  Analysis: `../hrp-acal-port-analysis.md` (private, outside the repo).
- **Issue #118** (`content-selector` defined nowhere): filed, unstarted. Smallest of the three;
  resolving it inside the ACAL XPath Profile unblocks part of #119 and MDP's XPath scheme.
- **Issue #59** (Multiple Decision Profile): analysed and parked behind #119. Proposal on the issue
  is to split it — three schemes deliverable now, two deferred. Analysis:
  `../issue-59-multiple-decision-profile-analysis.md` (private, outside the repo).
- **Reviewer's Guides**: only ACAL Core has one. HRP's is due with #119; XPath and JSONPath are
  retroactively owed one. **Check for this in any completeness audit.**
  (→ every-profile-ships-a-reviewers-guide)
- **Stale bibliography**: `[Multi]` and `[Hier]` cite 2010 CD-03s in six documents; both profiles
  are at CS02 (18 May 2014). Small, mechanical, and worth folding into whichever spec PR lands
  next. Same for `acal-core-v1.0.md:3484`, which still gives `RequestEntityReference` an `Id`
  property that #101 removed.
- **Issue #99**: fixed, committed, and pushed to `main` directly. Done.
- **Issue #102**: committed, pushed, PR #103 open — awaiting review, not yet merged.
- **Issues #105, #107, #110** (pub-check report): fixed on branch
  `issue-105-107-110-pubcheck-fixes` (off `main`, independent of #102) — needs commit, push,
  and PR opened next session (or later this one).
- **Issue #101** (RequestEntityReferenceType wrapper removal): fixed on branch
  `issue-101-requestentityreference-simplify` (off `main`, independent of #102 and #112) —
  needs commit, push, and PR opened next session (or later this one).
- **Issues #104, #106, #108, #109, #111** (remaining pub-check findings): filed, not yet
  addressed. #104 (pandoc `title-block-header` template) and #109 (fence-collapse build
  fragility) are the two with the widest blast radius if picked up next — both are one-time
  fixes to shared tooling (`pandoc/templates/default.html`, `pandoc/mkdocs.sh`) rather than
  per-document content edits.

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
