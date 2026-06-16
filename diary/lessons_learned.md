# Lessons Learned

Anti-patterns, failure modes, and hard-won rules. Most recent at top. Add an entry only when
a lesson is non-obvious — if it's standard practice or documented in the framework, skip it.

Cross-references use (→ slug-name) notation.

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
