# Session Context

## Current State (July 2026)

Work spans two repos:

- **`xacml-spec/`** (the OASIS spec repo) — spec issue #94 is public PR #100 (branch `issue-94-notice-id-nonunique`), **not yet merged** to spec `main`. The tools now track this branch (see below).
- **`tools/`** — five packages: `acal-core`, `acal-convert`, `acal-explain`, `yacal-validator`, `jacal-validator`. **452 tests pass across all five — verified by CI on a clean runner**, not on a warm cache.

**Branch state.** Cedar is merged to `main` (PR #15). The **first CI in the repo** and the spec-#94 alignment are in PR #16 (branch `ci-and-spec-alignment`), CI-green, awaiting merge. Once #16 lands, `main` is again the single source of truth.

**Two optional heavy dependencies** (→ heavy-runtime-dependencies-are-optional-extras): `acal-core[cedar]` (cedarpy, Cedar's parser) and `acal-explain[llm]` (litellm, for live model calls). Both import lazily and the suites mock/skip them. **CI must install `acal-core[dev]`** (which pulls cedarpy) or the Cedar tests silently skip.

**Spec-source coupling to know:** the validator tests and CI now resolve schemas against the **#94 branch** of `oasis-tcs/xacml-spec` (the direction the tools are built for). The `acal-convert`/validator CLIs still default to public spec `main` (pre-#94). This split is deliberate during the transition and resolves when PR #100 merges.

## Most Recent Session (July 15, 2026) — first CI, and the cache that had been lying

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

**Blocking on spec PR #100 (a reminder is set to track it):**

- **When #100 merges to `oasis-tcs/xacml-spec` main**, switch the `ref` in `.github/workflows/ci.yml`
  from `issue-94-notice-id-nonunique` back to the default branch, and re-run CI to confirm.
- **Reconcile the CLI default spec source with the tests.** The validator/convert CLIs default to
  public spec `main` (pre-#94); the tests use the #94 branch. This split is intentional until #100
  merges, then both should point at `main`. A user running the CLI today gets notice-Id uniqueness
  enforced; the tests do not — that is the transition state, not a bug.

**Immediate:**

- **Merge PR #16** (CI + spec-#94 alignment), then `main` is the single source of truth again.
- **AWS IAM JSON** is the next spoke (per ROADMAP), and the second matrix the interactive-decisions
  abstraction should be drawn from before `acal-decisions` starts.
- Retrofit the datatype ladder onto XACML and ALFA — the XACML reader still remaps datatypes by
  unchecked regex passthrough. (→ datatype-resolution-ladder)
- **Consider content-hashing the validators' schema cache** (or a `--refresh` in test setup). The
  current `source@branch` key is what let stale schemas mask real failures for a whole session.
  (→ a-content-blind-cache-makes-a-test-suite-lie)

**Spec:**

- **Issue #99**: normative examples violate the `AttributeAssignmentExpression (AttributeId, Category)` uniqueness constraint and the XSD cannot catch it.

**Known limitations, deferred:**

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
