# Session Context

## Current State (July 2026)

Work spans two repos:

- **`xacml-spec/`** (the OASIS spec repo) — spec issue #94 cleanup. Branch `issue-94-notice-id-nonunique` is ready but **unmerged**, pending TC sign-off.
- **`tools/`** — five packages. `acal-core` (99), `acal-converter` (21), `acal-explain` (34), `yacal-validator` (88), `jacal-validator` (90). **332 tests pass.**

**Branch state is the thing to know.** `main` is *behind*. The chain
`main → acal-converter → acal-core → acal-explain` is linear, each containing the last, and
`acal-explain` holds 7 commits that never landed on main — the ALFA reader, the acal-core
extraction, the import-model skill, and this session's work. `acal-converter` and `acal-core`
are stale checkpoints fully contained in `acal-explain`. The merged branches
(`jacal-validator`, `xacml-to-yacal`, `yacal-validator`) were deleted this session.
`origin/revert-7-acal-converter` is a stale remote branch that never merged.

## Most Recent Session (July 13, 2026)

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

<<<<<<< acal-explain
### Four defects surfaced along the way
=======
## Open Items for Next Session

- **File upstream bugs**: `AttributeSelectorType.unevaluatedProperties: false` blocks XPath profile extension in JACAL (workaround in `_patch_core_schema_shape_bugs()` in `validator.py`)
- **Delete `acal-validator` branch** once jacal-validator PR is merged
- **Populate root `README.md`** with project description and tool index (currently empty)
- **Create PRs**: yacal-validator branch → PR, jacal-validator branch → separate PR; both need review before merge to main
- **YACAL test suite**: the yacal-validator `tests/` directory has no Python test files yet — the same fixture + unit test pattern should be applied there

## Key Diary Files

- (→ architectural-decisions) Design principles and why the tool was split from the XML monolith
- (→ lessons-learned) Anti-patterns discovered during JACAL schema investigation
# Session Context — tools

**Last Updated**: 2026-07-13

---

## Current State

The tools repo has been restructured from a combined multi-format validator into per-language tools. Active branches:

- **`main`** — base branch; diary files, CLAUDE.md, CONTRIBUTING.md, `.gitignore`; `yacal-validator/` directory (merged from PR #3)
- **`xacml-to-yacal`** — new branch (this session); `xacml-converter/` tool, **54 tests passed, 0 skipped**
- **`jacal-validator`** — not yet started (next milestone after xacml-converter)
- **`yacal-validator`** — merged to main via PR #3; self-contained YACAL v1.0 (YAML) validator complete

`xacml-converter` status: **54 passed, 0 skipped** — converts XACML 3.0 and 4.0 XML policies to YACAL v1.0 YAML.
`yacal-validator` status: **88 passed, 0 skipped** (on main).

The tool provides:
- `yacal-validate FILE` CLI (installed via `pip install -e .`)
- `python -m yacal_validator FILE` (no install required, dependencies only)
- Two-layer validation: JSON Schema 2020-12 structural → constraint catalog + supplementary checks
- Full catalog coverage in tests: every current catalog rule has at least one deliberate test path, plus direct coverage for YAML-conformance rules and all supported root document forms
- Constraint coverage reported in every output, including incomplete cross-file cases
- XPath and JSONPath profile auto-detection and composition
- Schema source configurable via `yacal-validator.toml`, cached at `~/.cache/yacal-validator/`
- JSON and human-readable output modes; exit codes 0/1/2

---

## Most Recent Sessions

### July 13, 2026 — Accidental revert PR cleanup

GitHub automatically creates a `revert-<pr-number>-<branch>` branch when you merge a PR (in this case after merging PR #7 "acal-converter"). The user accidentally started a revert PR from this branch.

**Actions taken:**
- Identified the `revert-7-acal-converter` remote branch containing a revert commit.
- Created draft PR #8 from that branch.
- Immediately closed PR #8 with a comment explaining that the original PR #7 was intentionally merged and should remain unchanged.
- No code was reverted on `main`; the original merged changes from PR #7 (the ACAL converter) remain intact.
- Updated session context with today's date.

Original PR #7 stays merged as requested. The `revert-7-acal-converter` branch can safely be deleted later if desired (`git push origin --delete revert-7-acal-converter`).

---

### June 28, 2026 — xacml-converter code review and improvements

**Motivation:** Issue #2 in the GitHub repo (filed by Cyril Dangerville, AuthzForce author) asked for an XSLT stylesheet to convert XACML 4.0 → JACAL 1.0. We extended the scope to YACAL (YAML, not JSON) as output, handled both XACML 3.0 and 4.0 as input, and chose Python instead of XSLT/Java to stay in the project's existing ecosystem.

**Key architectural choices (details in → xacml-converter-pure-python, → xacml-converter-yacal-target):**
- Pure Python (stdlib `xml.etree.ElementTree`) for XML parsing — the Saxon/XSD licensing issue from the yacal-validator work was about XML *schema validation*, not XML *parsing*. A converter only needs to read elements, not validate them against XSD.
- YACAL (YAML) as output rather than JACAL (JSON) — aligns with the existing validator work; the same mapping dict could trivially be serialised as JSON if JACAL is needed later.
- Both XACML 3.0 and 4.0 handled in a single converter class, version-dispatched from the XML namespace.

**What was built (`xacml-converter/`):**
- `_identifiers.py` — regex-based remapping of XACML URNs / XSD type URIs to ACAL 1.0 URNs; safe to call on already-ACAL identifiers (passes through unchanged)
- `converter.py` — core `_Converter` class; version-aware element walking; converts PolicySet → nested Policy, AnyOf/AllOf/Match → Apply boolean trees, ObligationExpression/AdviceExpression → NoticeExpression, RuleId → Id, AttributeValue → Value; DataType omitted when it's the ACAL default (string)
- `cli.py` — `xacml-convert FILE [-o OUTPUT] [--validate]`; `--validate` calls yacal-validator if installed
- `__main__.py` — `python -m xacml_converter` support
- `xacml-convert` wrapper script at project root for convenient invocation with relative `tests/` paths
- 4 XACML fixture files (3 XACML 3.0, 1 XACML 4.0), 4 expected YACAL outputs, 54-test pytest suite

**54 tests pass, 0 skipped.**

---

### June 16, 2026 — Full catalog coverage: 88 tests, 0 skipped; YAML conformance; schema shape fixes

**What was added (by user, reviewed and committed by Claude):**

**`validator.py` — YAML conformance linting (`_lint_yaml_features`):**
Walks the ruamel.yaml parse tree before structural validation. Rejects: YAML tags, anchors/aliases, merge keys (`<<`), null values, octal integers, and multi-document streams. These are all prohibited by YACAL §5.1.4 / §7.4 but invisible to JSON Schema. Errors fire with `yaml:*` rule IDs.

**`validator.py` — `_patch_core_schema_shape_bugs` (additional schema normalizations):**
Beyond the three `_patch_schema` fixes already in place, a second pass normalizes:
- `AttributeSelectorTypeTree` / `EntityAttributeSelectorTypeTree` — rewired to use wrapper-key forms (`AttributeSelector`, `EntityAttributeSelector`) with `$dynamicRef`
- `StatusDetailTypeExtensionsDisabled` — cleared to remove the blanket `not: true` that made all StatusDetail content structurally invalid
- `PolicyDefaults` / `RequestDefaults` in PolicyType/RequestType — corrected from single-object to array shape
- `IdReferenceType` / `ExactMatchIdReferenceType` — rebuilt to fix malformed allOf that made `ApplicablePolicyReference` untestable
- `AttributeSelectorCoreType` / `EntityAttributeSelectorCoreType` — injected as missing definitions referenced by profile schemas

**`validator.py` — profile composition `$dynamicRef` target name fixes:**
All five `$dynamicAnchor` entries in `_composed_root` corrected from `*TypeTree` to `*TypeExtension` (e.g., `XPathPolicyDefaultsTypeTree` → `XPathPolicyDefaultsTypeExtension`). The old names matched no anchor in the XPath/JSONPath schemas, silently disabling profile validation.

**`validator.py` — JSONPath profile detection:**
Extended `_JSONPATH_INDICATORS` to recognize `MediaType: application/json` and `Path: $` patterns, which are the surface forms actually used in YACAL JSONPath selectors.

**`constraints.py` — `_conditional_presence` extended for StatusDetail allowlists:**
New `AllowedStatusDetailKeys` field recognized in catalog rules. When `WhenPropertyEquals` condition fires and `StatusDetail` is present, validates it is a mapping and contains only allowed keys.

**`constraints.py` — expression-path reference extraction in graph checkers:**
`_graph_acyclic` and `_graph_no_repeat` extended with `ReferenceExpressionPath`/`ReferenceWrapperKey`/`ReferenceIdProperty` fields to handle graph rules where references are inside nested expression trees (not flat property arrays). Used for `sharedvariablereference` graph traversal.

**`constraints.py` — `_walk_policies` + `_check_policy_variable_scope` supplementary check:**
Walks all nested Policy objects collecting ancestor VariableDefinition IDs, then enforces that VariableId is unique within scope (no shadowing). Covers both policy-level and rule-level duplicate variable IDs.

**New fixtures (all passing):**
- `ex11–ex17` — valid: Request/MultiRequests, Response, standalone ShortIdSet, XPath defaults, JSONPath selector, full Response result, expanded MultiRequests
- `err11–err49` — invalid: covers every catalog rule plus all YAML conformance rules (tags, anchors, merge keys, nulls, octals, multi-doc)

**Test suite:** 88 passed, 0 skipped.

---

### June 16, 2026 — Additional graph, expression, and request/response coverage

**Completed:** Strengthened several non-critical but worthwhile coverage edges in the YACAL suite:
- added a more explicit indirect-repeat short-id graph case to exercise `shortidset-reference-no-repeat` on a larger acyclic graph
- added a nested prohibited-expression case so `shared-variable-definition-no-variable-reference` is covered below the top level, not just as a direct expression wrapper
- added a structural invalid Boolean-expression case (`Condition` using a literal `Value`)
- added richer positive `Response` and `MultiRequests` fixtures beyond the earlier minimum-valid examples

**Result:** The suite now runs as `88 passed, 0 skipped`.

### June 16, 2026 — Local XPath tests replace upstream example dependency

**Completed:** Replaced the two legacy XPath tests that depended on upstream `examples/acal-xpath/Rule1.yaml` and `Rule2.yaml` files with self-contained local tests in `tests/test_yacal_validator.py`.

**What changed:**
- one test now validates the local XPath policy fixture `tests/fixtures/valid/ex14-policy-xpath-defaults.yaml`
- one test now validates an inline local `EntityAttributeSelector` XPath policy document
- the unused `xpath_examples` fixture was removed from `tests/conftest.py`

**Result:** The `yacal-validator` suite no longer depends on missing upstream YAML example artifacts and now runs cleanly as `83 passed, 0 skipped`.
>>>>>>> main

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

**Immediate — the merge backlog blocks everything:**

- **PR `acal-explain` → main.** Seven commits. Cedar cannot start cleanly until this lands. Then delete the stale `acal-converter` / `acal-core` local branches and `origin/revert-7-acal-converter`.
- Cut a `cedar` branch from the new main and run `/import-model CEDAR`.
- File the ROADMAP long-term items as GitHub issues (export tool, Rego, provenance extension).

**Spec:**

- **Issue #94 branch awaiting TC sign-off.** Do not merge without agreement — normative change.
- **Issue #99**: normative examples violate the `AttributeAssignmentExpression (AttributeId, Category)` uniqueness constraint and the XSD cannot catch it.
- **Tooling impact of #94**: if it lands, any validator enforcing notice-Id uniqueness must drop it. Check `yacal-validator` / `jacal-validator`.

<<<<<<< acal-explain
**Known limitations, deferred:**
=======
- ~~**Phase 2**: Add `--include FILE` CLI flag~~ ✓ Done
- ~~`yacal-validator` merged to main via PR #3~~ ✓ Done
- **Submit `xacml-to-yacal` branch as a PR** for independent review
- Create `jacal-validator` branch from `main` (next milestone)
- Delete `acal-validator` branch once `jacal-validator` is verified
- Populate root `README.md` with project description and tool index
- File upstream bugs against the spec repo:
  1. Original three YAML authoring bugs in `acal-core-yaml-v1.0-structure.schema.yaml` (properties: null, bare list in $defs, required: scalar)
  2. Additional schema defects found during coverage expansion (`PolicyDefaults` / `RequestDefaults` cardinality, selector hook wiring, `StatusDetailTypeExtensionsDisabled`, malformed Id reference defs)
  3. Missing Rule ID uniqueness constraint in `acal-core-yaml-v1.0-constraints.yaml`
  4. Wrong path for `shortidset-shortid-name-unique` in constraint catalog
  5. Root-element prose omits standalone `ShortIdSet` even though the structural schema allows it
- Publish to PyPI when both tools are stable
>>>>>>> main

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
