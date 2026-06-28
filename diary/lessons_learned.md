# Lessons Learned

## supplementary-shortidset-check-dead-for-bundles (June 2026)

**Rule**: When adding a supplementary Python check that mirrors a catalog-level rule, verify that the path filter (`if sid_path != "ShortIdSet": continue`) actually matches real documents — otherwise the supplementary check is silently skipped on every input.

**Why**: The `_check_shortidset_reference_graph` supplementary check has `if sid_path != "ShortIdSet": continue`. Since `_find_all(document, "ShortIdSet")` returns `("Bundle.ShortIdSet", ...)` for Bundle documents, the filter never matches and the check never runs. The catalog-level `_graph_no_repeat` (at `$.Bundle.ShortIdSet[]`) is the real enforcement path. The backtracking bug in the supplementary `walk()` went unnoticed for this reason. Discovering it required tracing the path string construction in `_find_all` — the mismatch between `"ShortIdSet"` and `"Bundle.ShortIdSet"` is easy to miss.

## entity-attribute-selector-requires-expression (June 2026)

**Rule**: `EntityAttributeSelectorType` requires BOTH `Path` (inherited from `BaseAttributeSelectorType`) AND `Expression` (added by `EntityAttributeSelectorType` itself) — unlike `AttributeSelectorType` which only needs `Path` and `Category`.

**Why**: When building an `XPathEntityAttributeSelector` fixture, omitting `Expression` produces a top-level `jsonschema:anyOf` failure with no direct pointer to the missing field. The distinction from `AttributeSelector` is easy to overlook since both descend from `BaseAttributeSelectorType` and look structurally similar at the property level.

## typed-value-boolean-is-not-valid (June 2026)

**Rule**: In JACAL `TypedValueType`, `Value` must be a number or string — boolean `true`/`false` are NOT valid. Use the raw boolean `true`/`false` (PrimitiveValueType) instead of `{"DataType": "{boolean}", "Value": true}`.

**Why**: `TypedValueType` in the JACAL schema uses `{"type": ["number", "string"]}` for primitive Value. Boolean values always have a fixed DataType (`{boolean}`) so they don't need one specified; the schema comment says "Boolean values not included here because they have a fixed DataType: ACAL Boolean." Writing `{DataType: "{boolean}", Value: true}` causes `jsonschema:anyOf` failures that look like top-level document errors, making it very hard to diagnose without inspecting sub-errors.

## schema-dependent-required-vs-constraint (June 2026)

**Rule**: When building JACAL test fixtures for constraints that the schema also enforces structurally (e.g., via `dependentRequired`, `uniqueItems`, `dependentSchemas`), the constraint catalog rule will never fire — the schema catches it first. Categorize these fixtures as "structural" in the test suite rather than "constraint."

**Why**: Several constraints from the ACAL catalog were implemented twice: once in the JSON Schema (as structural enforcement) and once in the constraint catalog (as a semantic rule). Examples: `bundle-policyreference-requires-policy` uses both `dependentRequired` in schema and a `nonEmptyWhenPresent` catalog rule; `shortidset-reference-no-repeat` (duplicate path) is caught by `uniqueItems: true`. Discovering this required validating the same fixture in multiple ways and examining sub-errors, not just top-level error messages. The fixture still demonstrates "invalid document" behavior; it just isn't a constraint-layer test.

## expression-value-datatype-is-context-dependent (June 2026)

**Rule**: In JACAL, whether `Expression.Value.DataType` is allowed depends on WHERE in the schema the expression appears, not on the ExpressionTypeTree definition itself. Always test the specific container type before assuming TypedValueType works.

**Why**: `ExpressionTypeTree` includes `TypedValueType` as a valid option at the schema level. But many container types add `dependentSchemas` that forbid `DataType` in the Value when the parent already declares DataType. Affected containers: `ParameterType.Expression`, `AttributeType.Value[]`, `SharedVariableReferenceType.Argument.Value`, `PolicyReferenceType.Argument.Value`. Writing fixtures with `{Value: {DataType: "...", Value: ...}}` in these containers produces top-level `jsonschema:anyOf` errors that give no direct hint about which nested `dependentSchemas.DataType: {not: true}` triggered.

## debugging-nested-jsonschema-anyof-errors (June 2026)

**Rule**: When a JACAL document fails with `jsonschema:anyOf` at `$`, always inspect `err.context` sub-errors to find the real failure path — the top-level message just says "not valid under any of the given schemas."

**Why**: The JACAL top-level schema is `anyOf: [PolicyWrapper, BundleWrapper, RequestWrapper, ResponseWrapper]`. ANY structural error anywhere in the document surfaces as a top-level `anyOf` failure because all four branches fail. The actual error (e.g., `dependentRequired: Policy required when PolicyReference present`) is buried several levels deep in `err.context`. The `validate()` function currently only reports the top-level error; investigating requires either `--output json` with post-processing, or direct `jsonschema` API usage with `err.context` traversal.
Anti-patterns, failure modes, and hard-won rules. Most recent at top. Add an entry only when
a lesson is non-obvious — if it's standard practice or documented in the framework, skip it.

Cross-references use (→ slug-name) notation.

---

## yacal-profile-and-statusdetail-hooks-need-local-normalization (June 2026)

**Rule:** Treat the upstream YACAL structural schemas as close to normative intent, not as perfectly executable artifacts. Before relying on profile selectors, defaults arrays, `StatusDetail`, or exact-match ID references, normalize the schema locally in `validator.py`.

**Why:** Full coverage work exposed several issues that do not show up in policy-only smoke tests:
- `PolicyDefaults` / `RequestDefaults` were modeled as single objects even though the spec and constraint catalog treat them as collections
- selector profile composition was wired to inner selector types rather than the wrapper-key forms actually used in YACAL (`AttributeSelector`, `EntityAttributeSelector`)
- `StatusDetailTypeExtensionsDisabled: not: true` made even core `MissingAttributeDetail` values structurally invalid
- `IdReferenceType` / `ExactMatchIdReferenceType` were malformed, which made `ApplicablePolicyReference` effectively untestable

Without local normalization, entire rule families appear "covered" in theory but are unreachable in practice. For a gold-standard validator, unreachable rules are defects, not acceptable caveats.

---

## yacal-policy-reference-catalog-paths-do-not-cover-bundle-nested (June 2026)

**Rule:** The catalog paths `$.Policy.CombinerInput[].PolicyReference` and `$.Bundle.PolicyReference` do NOT cover `PolicyReference` inside `$.Bundle.Policy[i].CombinerInput[j].PolicyReference`. Test fixtures exercising `policyreference-argument-datatype-agreement` must use a standalone PolicyDocument (root key `Policy`), not a Bundle.

**Why:** The eval_path evaluator matches exact absolute paths. A PolicyReference nested two levels deep inside a Bundle's Policy's CombinerInput is at `$.Bundle.Policy[0].CombinerInput[0].PolicyReference`, which matches neither catalog location. Discovered when Phase 2 test fixtures produced 0 skips instead of 1 because the checker never visited the PolicyReference.

---

## yacal-constraint-catalog-AppliesTo-nesting (June 2026)

**Rule:** In `acal-core-yaml-v1.0-constraints.yaml`, path fields for non-graph constraint kinds (`uniqueByProperty`, `uniqueByConcreteSubtype`, `nonEmptyWhenPresent`, `conditionalPresence`, `referenceMustResolve`, `uniqueByDerivedSet`, `noNestedExpressionKind`) live under `rule["AppliesTo"]`, not at `rule` top level.

**Why:** Reading from the wrong level caused all 7 non-graph checkers to emit `Path must start with '$'` warnings and skip every document silently. The constraint catalog documentation is not explicit about this nesting. Always use `rule.get("AppliesTo", {}).get("CollectionPath", "")` etc., not `rule.get("CollectionPath", "")`.

---

## yacal-graph-checker-seed-bug (June 2026)

**Rule:** In `_graph_no_repeat`, seed `visited` as an empty set `set()`, NOT `set(refs)` where `refs` is the current node's direct outbound edges.

**Why:** Pre-populating `visited` with the node's own refs caused the traversal to immediately flag any first-hop neighbor that appeared in the starting node's ref list as a "revisit" — producing false-positive cycle detection on valid documents (specifically ex09-bundle-shared-variable). The correct invariant is: mark a node visited only when the DFS actually visits it, not when it's queued.

---

## yacal-spec-schema-has-three-yaml-bugs (June 2026)

**Rule:** Patch `acal-core-yaml-v1.0-structure.schema.yaml` before handing it to the `referencing` library. Three YAML authoring bugs cause crashes:
1. `ExactMatchIdReferenceType.allOf[1]` has `properties: null` — strip the key
2. `$defs.QuantifiedExpressionTypeTree` is a bare YAML list — wrap it in `{"oneOf": [...]}`
3. `ArgumentTypeTree.oneOf[1].required` is a scalar string — promote to `[string]`

**Why:** These bugs exist in the upstream spec repo. The `referencing` library raises `AttributeError: 'NoneType' object has no attribute 'values'` (or similar) when it encounters them during schema resolution. The fix lives in `_patch_schema()` in `validator.py`. These have been filed upstream; remove the patches when the spec repo fixes them.

---

## yacal-catalog-gaps-must-be-patched-locally (June 2026)

**Rule:** When the upstream constraint catalog is wrong or incomplete, implement supplementary checks in `constraints.py` and increment `constraints_total`/`constraints_evaluated`. Never document a silent false negative as a "known gap."

**Why:** yacal-validator is positioned as the gold-standard reference implementation. Two catalog defects were found: (1) no rule for duplicate Rule IDs within a Policy CombinerInput, (2) `shortidset-shortid-name-unique` has path `$.ShortIdSet[].ShortId` matching no real document form. Both were implemented locally. Coverage reporting must stay accurate — supplementary checks must increment counters. (→ gold-standard-yacal-validation)

---

## bash-quoted-script-hash-corruption (June 2026)

**Rule:** Never pass multi-line Python (or any script) to `python3 -c "..."` with `#` comment lines inside the double-quoted argument. Write to a temp file and execute that instead.

**Why:** Bash's path validation warns "Newline followed by # inside a quoted argument can hide arguments from path validation." The `#` after a newline inside a double-quoted string can be silently stripped or misinterpreted by the shell. This corrupted debug scripts in this session, producing inconsistent results that looked like validation logic bugs and contributed to an extended debug loop. The fix is to write `script.py` to `/tmp/` and run `python3 /tmp/script.py`. This session discovered this the hard way after several rounds of `python3 -c "..."` scripts giving wrong answers.

---

## saxon-he-schema-not-licensed (June 2026)

**Rule:** `saxonche` (the pip package) provides Saxon HE. Saxon HE does NOT include XML Schema validation. `proc.new_schema_validator()` raises a license exception at runtime.

**Why:** Saxon's product tiers are not obvious from the package name. Saxon HE = XSLT 3.0 + XQuery 3.1 only. Schema-aware processing (XSD 1.0/1.1 validation) requires Saxon PE or EE. The tool was designed around `proc.new_schema_validator()` before this was verified, requiring a graceful-degradation path to be added after the fact. Lesson: verify that a specific Saxon API method is available in HE before building around it. (→ saxonche-for-xml-xsd11)

---

## yacal-constraint-catalog-fields-under-appliesTo (June 2026)

**Rule:** When reading fields from the YACAL constraint catalog, `propertyAgreement` rule fields (`ContainerLocations`, `ParentProperty`, `ChildCollectionPath`, `ChildProperty`, `ChildExpressionPath`) live under `AppliesTo`, not at the rule's top level.

**Why:** The catalog structure is not uniform across rule kinds. Most rule kinds (`uniqueByProperty`, `referenceMustResolve`, etc.) have their configuration at the rule's top level. `propertyAgreement` rules wrap everything under `AppliesTo`. Reading from the wrong level caused all four `propertyAgreement` rules to silently return without checking anything — a false PASS for every document. The silent failure was particularly dangerous because no exception was raised, making it invisible until a deliberate review of the checker code.

---

## empty-combinerinput-masks-as-profile-bug (June 2026)

**Rule:** When a JACAL root-level `anyOf` fails, check required cardinality constraints on top-level arrays before assuming the failure is in deep schema composition.

**Why:** `CombinerInput: []` (an empty array) violates a `minItems` constraint in `CombinerInputType`. This produces a root-level `anyOf` failure with the entire document reported as the failing instance — which looks exactly like a schema composition or `$dynamicRef` failure. In this session, this caused the `$dynamicRef` profile-composition mechanism to be suspected as broken for several debug cycles. The `$dynamicRef` was working correctly all along.

---

## spec-examples-may-predate-schema (June 2026)

**Rule:** Treat spec example files as documentation, not ground truth for schema conformance. Validate them rather than assuming they are correct.

**Why:** The JACAL example files (`Rule1.json`, `Rule2.json`, `Rule3.json`) use `Apply.Expression` but the normative schema defines `Apply.Argument` with `additionalProperties: false`. The examples predate a field rename. A test that validated these files against the schema would fail correctly — but if the test was written to assert PASS, it would hide the validator's correct rejection as a false failure. The adoption guide (not the examples) is authoritative for intended usage.
