# Lessons Learned

## converter-output-must-be-fed-to-our-own-validator (July 2026)

**Rule**: A converter that has a validator in the same repo must be tested by *piping its
output into that validator*, on ordinary inputs — not just by asserting on the intermediate
dict. Passing unit tests on the dict prove nothing about whether the emitted document is
valid.

**Why**: `acal-convert` was emitting YACAL that `yacal-validate` **rejects**, for an input as
ordinary as an XACML 3.0 policy with no `Version` attribute (optional in XACML). Two distinct
faults stacked: the builders assigned `elem.get("Version")` straight into a dict literal, so an
absent attribute became `None` and serialized as a YAML null — which YACAL prohibits outright;
and even omitting it left the document invalid, because ACAL *requires* Version. The faithful
answer was neither: XACML 2.0/3.0 declare `Version` optional **with a schema default of
"1.0"**, so the absent attribute *means* 1.0.

Every unit test passed throughout. The `--validate` flag existed and nobody had pointed it at
a versionless policy. The invariant now has a test that sweeps every fixture through its reader
asserting no nulls anywhere, which will protect Cedar and IAM before their readers are written.

---

## capability-claims-must-be-checked-against-the-reader (July 2026)

**Rule**: When authoring a capability/gap matrix from a prose design doc, verify each claim
against the *code that actually parses the language*. Prose describes intent; the reader
describes reality, and where they differ the reader is what ships.

**Why**: I wrote `capabilities/xacml.yaml` from the expressiveness doc and asserted
`SharedVariableDefinition: exportable: false` — "XACML has no cross-policy variable sharing."
The reader parses `<Bundle><SharedVariableDefinition>` and emits it correctly. The claim was
false for XACML 4.0, and the matrix is supposed to be the *export tool's precondition gate*,
so the error would have silently mis-gated export later.

The deeper cause was a modelling error, not a typo: one matrix was being asked to answer for
XACML 2.0, 3.0, and 4.0 at once, and those are not one language.
(→ acal-is-a-hub-not-a-xacml-dialect). A matrix keyed on something coarser than the thing whose
capability varies will be wrong, and wrong *silently*, because nothing executes prose.

## find-based-readers-drop-what-they-do-not-ask-for (July 2026)

**Rule**: A reader built from targeted `find()` / `findall()` calls silently ignores every
element it does not explicitly look for. Pair every such reader with an explicit
known-children allowlist that **raises** on anything unrecognised. Do not rely on "we handle
all the elements" — rely on the parser refusing the ones you don't.

**Why**: `_rule()` in the XACML reader read `Description`, `VariableDefinition`, `Condition`,
and the notice elements — and never read `<Target>`. A Rule's Target scopes *when the rule
applies*, so a rule that permitted only doctors converted into a rule that permits
**everyone**. This affected XACML 2.0, 3.0, and 4.0, and had shipped.

Two things kept it invisible. First, the `Policy` element already had a
`_POLICY_NON_COMBINER_CHILDREN` allowlist that raises on unknown children — so the codebase
*looked* like it enforced no-silent-drops, and the missing guard on `Rule` did not stand out.
Second, not one XACML fixture had a Rule-level Target: every rule in the suite was either
bare or condition-only, so the whole class of bug was invisible to a passing test suite.

The lesson generalises past XACML. Any `find`-based reader is a silent-drop machine by
default; the allowlist is not a nicety, it is the only thing that converts "we forgot to
handle X" from a wrong answer into an error message. Found only because a *fixture-coverage*
gap (an empty `xacml4/` directory) was being closed — the bug was in 3.0, not 4.0.
(→ empty-fixture-directory-is-a-coverage-lie)

---

## empty-fixture-directory-is-a-coverage-lie (July 2026)

**Rule**: An empty fixture directory, or a supported format with no test referencing it, is
an untested code path wearing the costume of a tested one. Check that every value in a
version/format enum has at least one fixture exercising its *distinctive* branches — not just
the branches it shares with its siblings.

**Why**: `XACMLVersion` declared `V2_0`, `V3_0`, and `V4_0`, and the reader had genuine
4.0-only branches (no identifier remapping, `Target` as a BooleanExpression, unified
`NoticeExpression`, `PolicyReference`, no `PolicySet`). `tests/fixtures/xacml4/` was an
**empty directory** and no test mentioned 4.0. XACML 4.0 support was claimed in the README,
the docs, and the capability matrix — and never once executed.

It happened to work, which is the trap: a 4.0 document using only constructs shared with 3.0
converts correctly through the shared paths and looks fine, so nobody notices that the
4.0-specific paths have never run. The failure mode is not "the feature is broken", it is
"nobody knows whether the feature is broken." Writing the missing fixtures immediately
surfaced a shipped security-relevant bug in a *different* version.
(→ find-based-readers-drop-what-they-do-not-ask-for)

---

## strict-must-be-threaded-through-every-pass (July 2026)

**Rule**: In a multi-pass reader, `strict` must reach *every* pass. A disposition-(b)
construct whose warning fires in a pass that never received the flag will warn correctly and
then silently fail to escalate under `--strict`. Grep for `warnings.warn` and confirm each
call site can see `strict`.

**Why**: The ALFA `xpath` datatype is documented as "(b) warning / error under `--strict`" in
the gap table. It never errored. The warning is emitted during symbol collection (pass 1), and
`_collect_symbols(tree)` took no `strict` argument — only `AlfaTransformer` (pass 2) had
`_strict` and a `_warn_or_raise` helper. The escalation path did not exist for anything pass 1
detects, and the gap table's claim had been false since the feature shipped.

This is exactly the failure the project's no-silent-drops rule exists to prevent, and it hid
in plain sight because the *warning* worked perfectly — the default path behaved as
documented, so nothing looked broken. Only exercising `--strict` end-to-end on a
warning-eligible fixture exposed it. `--strict` is a security-relevant promise here: it is
what a user turns on when they need conversion to fail rather than approximate. Test the
escalation, not just the warning. (→ dsl-vs-format-is-the-first-fork-for-new-readers)

---

## check-for-fork-before-deleting-a-duplicate (July 2026)

**Rule**: Two files with the same name in two directories are not necessarily a duplicate and
an original. Before deleting the "copy", diff them *both ways* — list the headings unique to
each. If each side has content the other lacks, it is a fork, and deleting either loses work.

**Why**: `policy-language-expressiveness.md` existed in both `acal-converter/docs/` and
`acal-core/docs/` after the acal-core extraction. The obvious move was to delete the stale
converter copy. It was not stale: it held the July alfa.guide alignment (all 9 combining
algorithms, the full function map, bag overloading V2) that the core copy had never received,
while the core copy held the Cedar/IAM/Rego gap analyses the converter copy lacked. The
converter copy was also *smaller* (125 lines vs 500), which made it look obviously like the
lesser one.

A one-way `diff` showed only what core added and reinforced the wrong conclusion. `comm` on
the two heading lists showed the fork immediately. The cost of getting this wrong is silent:
the deleted content does not come back, and nothing fails.

---

## a-restriction-may-be-a-decision-not-a-bug (July 2026)

**Rule**: Before calling a narrow allowlist "drift" and widening it, search the diary for a
decision that put it there. Reversing a deliberate decision is fine; reversing it while
believing it was an accident means the original reasoning never gets addressed.

**Why**: `acal-explain` accepted XACML/YACAL/JACAL but not ALFA, even though
`acal_core.readers.load()` supported ALFA. This looked exactly like registry drift — one of
five declaration sites had been missed — and it was reported as such. It was not: it was
`acal-explain-acal-only-input`, a deliberate decision with a written rationale.

The decision was still worth reversing (the user's feature request overturned it), and the
central registry was still worth building. But the diary entry needed to be *superseded* with
an explanation of which premise was wrong, not silently contradicted by code. The tell was
that the rejection had a helpful, hand-written error message pointing at `acal-convert` —
drift does not write itself a good error message.

---

## xsd10-unique-silently-skips-absent-optional-fields (July 2026)

**Rule**: An `xs:unique`/`xs:key` whose field list includes an **optional** attribute does not constrain elements where that attribute is absent. XSD 1.0 treats a field matching nothing as an incomplete key-sequence and skips the tuple entirely — no error, no duplicate detection. Never assume a declared identity constraint is actually enforcing the OCL it was generated from.

**Why**: `NoticeExpression_AttributeAssignmentExpression_AttributeId-Category` in the core XSD declares fields `@AttributeId` + `@Category`, intending to enforce `self->isUnique(Sequence{AttributeId, Category})`. Because `Category` is optional, two `AttributeAssignmentExpression`s with the same `AttributeId` and **no** `Category` validate cleanly — while the same pair *with* `Category` present is correctly rejected. The gap is why two normative examples (the spec's own §4 example and `examples/acal-xpath/Rule3.xml`) have shipped for a long time violating a constraint the schema supposedly enforces (filed as spec issue #99).

I only found this because I probed the *adjacent* constraint as a control while removing a different one — if I had only tested the constraint I was changing, I'd have missed it. When removing a constraint, test the neighbouring constraints too: it both proves you didn't over-remove and occasionally exposes a constraint that was never working.

Also relevant when validating this schema at all: it is XSD 1.1 (`xs:assert` with `vc:minVersion="1.1"`), so `xmllint` cannot compile it directly. Strip the 1.1-only constructs first (the repo ships `xsd1.1-to-1.0.xsl` for exactly this); identity constraints are a 1.0 feature and survive the downgrade.

---

## alfa-bag-type-not-a-datatype (July 2026)

**Rule**: In ALFA attribute declarations, `type = bag` is a cardinality modifier, not an XSD datatype — clear `attr_type` to `""` when `"bag"` is detected; do not store it in the AttributeDesignator's `DataType` field.

**Why**: The existing code set `attr_type = "bag"` and then passed it to `DataType` via `if decl.type: desig["DataType"] = decl.type`. The downstream `_TYPE_IS_IN_MAP.get("bag")` returned `None`, so the bag-is-in expansion silently fell through to `string-equal` — wrong function, wrong argument order, no error. The failure was invisible because the neutral dict writer accepted any `DataType` string. Discovered only when writing a type-aware bag test and inspecting the output. The fix is in `_process_attribute` — one extra line that clears `attr_type` after setting `is_bag = True`. The lesson: DSL type keywords often have dual semantics (type vs. cardinality modifier) — verify against real attribute files before assuming a type field maps directly to a data type.

---

## litellm-module-level-import-for-mocking (June 2026)

**Rule**: Import `litellm` (and any other third-party library you need to mock in tests) at module level, not inside the function that uses it. Use a try/except at the top of the module to handle the not-installed case.

**Why**: `unittest.mock.patch("acal_explain.llm.litellm")` requires `litellm` to exist as a module-level attribute of `acal_explain.llm`. When the import was inside the `explain()` function body, `patch` raised `AttributeError: module does not have the attribute 'litellm'` — even though the function would have imported it correctly at call time. Moving to module level with `try: import litellm / except ImportError: litellm = None` gives the mock a stable target without losing the graceful-degradation behaviour for users who don't have it installed.

---

## real-world-files-expose-synthetic-fixture-blind-spots (June 2026)

**Rule**: Import real-world source files as test fixtures as early as possible — synthetic fixtures cover only the grammar paths the writer thought of, not the ones a real tool vendor chose.

**Why**: The ALFA grammar built against synthetic fixtures had six gaps that would have failed on any real Axiomatics policy file: missing `target clause` keyword, `apply` inside body rather than before `{`, `and`/`or` as keyword operators, inline `{ }` advice blocks, bare policyset cross-references, and system.alfa-style declarations. None of these were invented by Axiomatics — they are all in the ALFA spec or common tooling conventions. Discovering them only requires running the converter on a real file. The cost of not importing real files early was building and debugging a grammar that was functionally useless on real input.

---

## lark-visit-error-wrapping (June 2026)

**Rule**: In Lark Transformers, any exception raised inside a transformer method is caught by Lark and re-raised wrapped in `lark.exceptions.VisitError`. Catch `VisitError` in the `load()` entry point and unwrap the inner exception before propagating.

**Why**: `ALFAUnsupportedFeatureError` raised inside `applying_kw()` surfaced to callers as `VisitError`, not as the expected exception type. The `strict=True` test that called `pytest.raises(ALFAUnsupportedFeatureError)` would have failed silently — the exception IS raised but under a different type. The fix is a single try/except around `transformer.transform(tree)` that checks `exc.__context__` for known application exception types and re-raises them directly. Without this unwrap, every downstream caller (CLI, tests, external code) would need to know about `VisitError` — a Lark implementation detail that should not leak.

---

## lark-rule-alias-passthrough-trap (June 2026)

**Rule**: In a Lark rule with alternation aliases (`rule: A -> alias_a | B`), the alternative WITHOUT an alias (`| B`) still invokes the method named after the RULE, not after B. Check for the distinguishing token in the items list rather than assuming the method is only called for the primary alternative.

**Why**: `not_expr: NOT_OP not_expr -> not_expr | cmp_expr` — when `| cmp_expr` matches (no `NOT_OP`), Lark still calls the `not_expr()` transformer method with `items = [cmp_expr_result]`. The method was unconditionally wrapping the result in `{"Apply": {"FunctionId": "not", ...}}`, producing `not(not(string-equal(...)))` for any comparison expression. The bug was invisible until inspecting the full output dict because parse and transform both completed without error. Fix: `has_not = any(isinstance(i, Token) and i.type == "NOT_OP" for i in items)`.

---

## lark-symbol-collection-use-token-type-not-position (June 2026)

**Rule**: When walking a raw Lark parse tree (before a Transformer runs), find Token children by `.type` attribute rather than by index position.

**Why**: In the symbol collection pre-pass (`_collect_symbols`), the initial code used `node.children[0]` to get the namespace name, expecting the first child to be DOTTED_ID. But grammar terminals appear in children in definition order — `namespace_decl: _NAMESPACE_KW DOTTED_ID "{" ...` — so with `_NAMESPACE_KW` NOT yet discarded (the raw tree includes all tokens regardless of `_` prefix), `children[0]` was the keyword token `Token('_NAMESPACE_KW', 'namespace')` and `children[1]` was the DOTTED_ID. Position-based access breaks whenever the grammar is reordered. Using `next(c for c in node.children if isinstance(c, Token) and c.type == 'DOTTED_ID')` is robust to grammar changes.

---

## dsl-vs-format-is-the-first-fork-for-new-readers (June 2026)

**Rule**: When adding a new source language to `acal-converter`, the first question must be "is this a structured data format or a DSL?" — this determines the entire dependency and parsing strategy before any semantic analysis is useful.

**Why**: Structured formats (XML, JSON, YAML) delegate parsing to a standard library and the reader's job is purely semantic mapping. DSLs require an actual parser (tokenizer + grammar), which introduces a new dependency, a new error type, and a fundamentally different implementation shape (grammar file + Transformer class vs. a few library calls). Starting the gap analysis with semantic coverage questions before settling this produces a detailed mapping that then needs to be rebuilt around whichever parser is chosen. The `import-model` skill now explicitly surfaces this as Phase 2's first question and branches the interview accordingly.

---

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

## xml-parsing-vs-xml-schema-validation (June 2026)

**Rule:** Do not conflate "Python can't validate XML against XSD 1.1" with "Python can't parse XACML XML." They are completely separate operations. Use Python's stdlib for conversion; reserve the Saxon/Java discussion for validation.

**Why:** The yacal-validator work established that Saxon EE (commercial) is required for XSD 1.1 schema validation, and `saxonche` (HE) cannot do it. When designing the XACML converter, this memory made Java/XSLT seem necessary — but it isn't. A converter parses XML element trees; it does not validate input against an XSD. `xml.etree.ElementTree` handles any well-formed XACML document, any namespace, any version, with zero licensing risk. The false generalisation "Python can't do XACML" would have added a Java runtime dependency to an otherwise pure-Python project. (→ xacml-converter-pure-python)

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
