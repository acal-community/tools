# Session Context

## Current State (June 2026)

Two validator tools are in active development on separate branches:
- `yacal-validator` — YACAL v1.0 (YAML) policy validator; believed complete with tests passing
- `jacal-validator` — JACAL v1.0 (JSON) policy validator; **test suite now complete and passing (78/78)**

Both are in the `/tools/` directory. The `acal-validator` branch (the original XML-aware monolith) is slated for deletion once both tools are verified.

## Most Recent Session (June 2026)

Completed the JACAL validator test suite. The session picked up mid-way through creating the invalid test fixtures and finished everything:

**Why this work matters:** Gold-standard coverage requires demonstrated constraint catalog coverage — not just that valid documents pass, but that each constraint fires on the right invalid document and the right rule ID appears in the error output.

**What was discovered during fixture creation:**

JACAL's JSON Schema structurally enforces several constraints that YACAL only catches semantically. This affects which catalog rules can ever produce errors at the constraint layer:

- `AttributeType.Value[].DataType` — forbidden via `dependentSchemas` in schema
- `SharedVariableReference.Argument.Value.DataType` — forbidden in JACAL (not in YACAL)
- `PolicyReference.Argument.Value.DataType` — forbidden in JACAL
- `Parameter.Expression.Value.DataType` — forbidden in JACAL
- `BundleType.PolicyReference` requires `Policy` — enforced via `dependentRequired` in schema (not just a semantic rule)
- `ShortIdSetReference` has `uniqueItems: true` — duplicate references caught structurally
- `TypedValueType.Value` for boolean must be a raw `true`/`false`, not a number/string — `TypedValueType` only accepts number/string primitive values, not boolean

As a result, these catalog rules always evaluate but never produce constraint-level errors for structurally-valid JACAL documents:
  `attribute-valuetype-datatype-agreement`, `requestattribute-valuetype-datatype-agreement`,
  `attributeassignment-valuetype-datatype-agreement`, `parameter-valuetype-datatype-agreement`,
  `sharedvariablereference-argument-datatype-agreement`, `bundle-policyreference-requires-policy` (partial),
  `shortidset-reference-no-repeat` (duplicate-ref path), `request-defaults-unique-concrete-subtype`,
  `policy-defaults-unique-concrete-subtype`

`policyreference-argument-datatype-agreement` produces a skip warning (exit 2) for external policy references; never errors because the argument DataType itself is forbidden.

**What was built:**
- 36 invalid test fixtures (`err01`–`err36`) covering structural, constraint, and JSON conformance errors
- 2 incomplete fixtures (`inc01`–`inc02`) demonstrating cross-document skip warnings
- `tests/test_fixtures.py` — parametrized fixture tests (48 test cases, 4 categories)
- `tests/test_jacal_validator.py` — 30 unit-level tests (linting, profile detection, path evaluator, exit codes)

**Test summary:** 78 tests, 78 pass, 0 fail.

## Open Items for Next Session

- **File upstream bugs**: `AttributeSelectorType.unevaluatedProperties: false` blocks XPath profile extension in JACAL (workaround in `_patch_core_schema_shape_bugs()` in `validator.py`)
- **Delete `acal-validator` branch** once jacal-validator PR is merged
- **Populate root `README.md`** with project description and tool index (currently empty)
- **Create PRs**: yacal-validator branch → PR, jacal-validator branch → separate PR; both need review before merge to main
- **YACAL test suite**: the yacal-validator `tests/` directory has no Python test files yet — the same fixture + unit test pattern should be applied there

## Key Diary Files

- (→ architectural-decisions) Design principles and why the tool was split from the XML monolith
- (→ lessons-learned) Anti-patterns discovered during JACAL schema investigation
