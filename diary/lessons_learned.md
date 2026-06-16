# Lessons Learned

Anti-patterns, failure modes, and hard-won rules. Most recent at top. Add an entry only when
a lesson is non-obvious — if it's standard practice or documented in the framework, skip it.

Cross-references use (→ slug-name) notation.

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
