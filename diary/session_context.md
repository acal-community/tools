# Session Context — tools

**Last Updated**: June 16, 2026

---

## Current State

The tools repo has been restructured from a combined multi-format validator into per-language tools. Three branches:

- **`main`** — base branch; diary files, CLAUDE.md, CONTRIBUTING.md, `.gitignore` only
- **`acal-validator`** — the original combined XML+JSON+YAML validator (pre-split); kept until `jacal-validator` is ready, then to be deleted
- **`yacal-validator`** — active development branch; self-contained YACAL v1.0 (YAML) validator, **complete with spec-driven fixture and unit tests**

`yacal-validator` status: **88 passed, 0 skipped**.

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

### June 16, 2026 — YACAL conformance coverage expanded to full catalog + YAML rules

**Completed:** Expanded the fixture suite from policy-centric examples into a conformance-oriented suite covering:
- all supported root document forms (`Policy`, `Bundle`, `Request`, `Response`, standalone `ShortIdSet`)
- YAML prohibited features (tags, anchors/aliases, merge keys, nulls, octal integers, multi-document streams)
- all current catalog rule families, including request/multi-request integrity, response/result uniqueness, status detail rules, parameter/name uniqueness, datatype agreement, short-id graph rules, shared-variable graph rules, and profile-default subtype uniqueness
- profile-aware validation for XPath and JSONPath fixtures

**Test status at that milestone:** `81 passed, 2 skipped`.

**Validator/schema work required to make spec-aligned coverage possible:**
- Added YAML feature linting before schema validation (`yaml:*` rule ids)
- Added local support for `AllowedStatusDetailKeys` in `conditionalPresence`
- Patched additional upstream schema defects at load time:
  1. `PolicyDefaults` / `RequestDefaults` cardinality corrected to arrays
  2. selector extension hooks corrected so wrapper-key forms (`AttributeSelector`, `EntityAttributeSelector`) compose through `$dynamicRef`
  3. missing core selector defs (`AttributeSelectorCoreType`, `EntityAttributeSelectorCoreType`) synthesized
  4. `StatusDetailTypeExtensionsDisabled` neutralized so core `MissingAttributeDetail` is structurally valid
  5. malformed `IdReferenceType` / `ExactMatchIdReferenceType` repaired so `ApplicablePolicyReference` is testable

**Coverage outcome:** the suite now exercises every current catalog rule directly, including the previously unreachable `statusdetail-missing-attribute-shape` rule via a constraint-level unit test. The two remaining skips at that milestone were later removed by replacing the upstream-dependent XPath tests with local fixtures.

### June 16, 2026 — Phase 2: --include flag; three-way exit codes; INCOMPLETE output state

**Added `--include FILE`** (repeatable) to CLI. Loads additional YACAL files into the resolution index before constraint evaluation. Required when a document has `PolicyReference` or `SharedVariableReference` pointing to definitions in external files.

**Three-way exit codes:**
- `0` — valid AND fully evaluated (no skipped constraints)
- `1` — validation failed (one or more errors)
- `2` — incomplete (cross-file references could not be resolved, provide `--include`)
         OR tool error (missing schemas, bad input, etc.)

**Output state `INCOMPLETE`** — `human()` now shows `INCOMPLETE  YACAL v1.0 (YAML) — file.yaml  (N constraint(s) not evaluated — use --include)` when `result.incomplete` is True. Previously valid-with-skips fell through to the advisory-warnings PASS branch.

**`result.incomplete`** property on `ValidationResult` — `True` when `constraints_skipped > 0`. Surfaced in JSON output as `"incomplete": true`.

**Architecture:**
- `_merge_from_document()` — extracts SharedVariableDefinition and Policy entries from any document form (Bundle or standalone PolicyDocument)
- `_build_resolution_index(document, extra_docs=None)` — runs `_merge_from_document` over primary + extras and merges into shared context dict
- `evaluate(document, catalog, extra_docs=None)` — passes extra_docs to index builder
- `validate(..., include_paths=None)` — loads and parses include files via `_load_include_docs()`

**Key lesson:** The catalog paths `$.Policy.CombinerInput[].PolicyReference` and `$.Bundle.PolicyReference` do NOT cover `PolicyReference` nested inside `$.Bundle.Policy[].CombinerInput[]`. The Phase 2 test fixture must be a standalone PolicyDocument, not a Bundle, to exercise the catalog path.

**Test suite:** 36 passed, 2 skipped (permanent XPath). Three new Phase 2 tests (without include → exit 2, with matching include → exit 0, with mismatched include → exit 1).

---

### June 16, 2026 — Phase 1 within-Bundle resolution; 38/38 constraints evaluated

**Implemented:** Within-document resolution for the two formerly-skipped cross-document constraints (`sharedvariablereference-argument-datatype-agreement` and `policyreference-argument-datatype-agreement`).

Before Phase 1, both constraints blanket-skipped every document with advisory warnings. After Phase 1, for any document whose references resolve within the same Bundle, both constraints are fully evaluated — no skip warnings emitted.

**Mechanism:** `_build_resolution_index(document)` scans a Bundle and builds two indexes:
- `shared_vars: {Id → [ParameterType]}`  (from `Bundle.SharedVariableDefinition[]`)
- `policies: {PolicyId → [ParameterType]}` (from `Bundle.Policy[]`)

`evaluate()` builds the index before running catalog rules and passes it to `_property_agreement` via `context=`. For each `SharedVariableReference`/`PolicyReference` found in the document, the checker resolves it in the index. If found: runs `_check_argument_datatype_agreement()` which matches positional and named arguments against parameter DataType declarations. If not found (cross-file, Phase 2 territory): emits a per-reference skip warning with hint "Use --include to provide the definition file."

**Output change:** All valid fixtures now show `Constraints: 38/38 evaluated` with no skip annotation (was `34/36 evaluated · 2 skipped`).

**Test suite:** 33 passed, 2 skipped (permanent XPath). Two new fixtures added:
- `ex10-bundle-parameterized-sharedvar.yaml` — valid; exercises DataType agreement check
- `err10-sharedvar-datatype-mismatch.yaml` — invalid; `{integer}` passed where `{string}` required

**Phase 2 (next):** Add `--include FILE` CLI flag to load external definition files into the resolution index, enabling full evaluation for cross-file references.

---

### June 16, 2026 — Fixture test suite complete; gold-standard validation enforced

**Completed:** Added `tests/fixtures/valid/` (7 adoption guide examples, ex01–ex09) and `tests/fixtures/invalid/` (9 error cases). Created `tests/test_fixtures.py` with 19 parametrized and targeted tests. All 31 tests pass (2 permanent XPath skips unchanged).

**Gold-standard requirement:** yacal-validator must have NO known gaps. Two upstream catalog defects were found and remedied by supplementary constraint checks in `constraints.py` rather than documenting them as acceptable gaps:

1. **Missing catalog rule** — duplicate Rule IDs within a Policy CombinerInput had no catalog entry. Added `_check_rule_id_unique_within_policy()`.
2. **Wrong catalog path** — `shortidset-shortid-name-unique` uses path `$.ShortIdSet[].ShortId` which matches no real YACAL document form (ShortIdSet appears only at document root). Added `_check_shortid_name_unique()` with recursive traversal.

Both supplementary checks increment `constraints_total`/`constraints_evaluated` so coverage reporting stays accurate. Counter is now `38/38 evaluated · 2 skipped` for valid documents.

**Spec schema bugs fixed** (in `_patch_schema()` in validator.py):
1. `ExactMatchIdReferenceType.allOf[1].properties: null` — removes null properties key
2. `$defs.QuantifiedExpressionTypeTree` — bare list wrapped in `{"oneOf": [...]}`
3. `ArgumentTypeTree.oneOf[1].required` — scalar string promoted to array

**Constraint catalog path bug fixed** — All 7 non-graph checkers were reading path fields from rule top level; the catalog nests them under `AppliesTo`. Fixed systematically.

**False-positive in graph checker fixed** — `_graph_no_repeat` seeded `visited` with the node's own refs before traversal, causing immediate false-positive on first-hop edges. Fixed by initializing `visited` as empty set.

---

### June 16, 2026 — Saxon pivot, yacal-validator built, constraint transparency added

**Trigger:** A `/grill-me` session on Saxon EE licensing established that Saxon EE (commercial) is required for XSD 1.1 schema processing. The `saxonche` pip package (Saxon HE) cannot perform schema validation at all, making the original `acal-validator` XML path permanently broken for an open-source tool.

**Architectural pivot:** Split `acal-validator` into per-language tools. XML validation deferred to a separate effort. `yacal-validator` branch created from `main`, containing only YACAL code carved from `acal-validator` with XML/hint cruft stripped. Flat module layout (`src/yacal_validator/validator.py`, `constraints.py`, `schemas.py`, etc.); no `validators/` subdir; no migration hints; no Saxon dependency. (→ per-language-tools-no-xml)

**`__main__.py` + README:** Added `python -m yacal_validator` support. README documents three invocation modes (run from source, install locally, install from PyPI) and walks through the full PyPI publishing workflow step-by-step for first-time publishers.

**Constraint coverage transparency:** The catalog has 36 rules. Two require cross-document lookup and are permanently skipped. Before this change, skips were buried as individual WARNING issues; users had no summary-level signal that semantic validation was partial. `evaluate()` now returns `(issues, total, evaluated, skipped)`. `ValidationResult` carries the counters. Both human and JSON output surfaces coverage on every run. Multi-file batch validation stays external (shell loops) — the tool delivers a complete verdict on one file; orchestration is the caller's job. (→ constraint-coverage-always-surfaced)

---

## Open Items

- ~~**Phase 2**: Add `--include FILE` CLI flag~~ ✓ Done
- Create `jacal-validator` branch from `main` (next milestone after Phase 2)
- Delete `acal-validator` branch once `jacal-validator` is verified
- Populate root `README.md` with project description and tool index
- File upstream bugs against the spec repo:
  1. Original three YAML authoring bugs in `acal-core-yaml-v1.0-structure.schema.yaml` (properties: null, bare list in $defs, required: scalar)
  2. Additional schema defects found during coverage expansion (`PolicyDefaults` / `RequestDefaults` cardinality, selector hook wiring, `StatusDetailTypeExtensionsDisabled`, malformed Id reference defs)
  3. Missing Rule ID uniqueness constraint in `acal-core-yaml-v1.0-constraints.yaml`
  4. Wrong path for `shortidset-shortid-name-unique` in constraint catalog
  5. Root-element prose omits standalone `ShortIdSet` even though the structural schema allows it
- Publish to PyPI when both tools are stable

---

## Key Diary Files

- [architectural_decisions.md](architectural_decisions.md) — design principles, non-negotiable patterns
- [lessons_learned.md](lessons_learned.md) — anti-patterns and hard-won insights (most recent at top)
