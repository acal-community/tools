# Session Context

## Current State (July 2026)

Work spans two repos:

- **`xacml-spec/`** (the OASIS spec repo) — spec issue #94 cleanup. Branch `issue-94-notice-id-nonunique` is ready but **unmerged**, pending TC sign-off.
- **`tools/`** — three packages on the `acal-converter` branch (`acal-core` 87 tests, `acal-converter` 20 tests, `acal-explain` 30 tests). All 107 pass. The ALFA reader is aligned with the Axiomatics PDP 7.x dialect per alfa.guide.

## Most Recent Session (July 2026)

### Spec issue #94: reversing the notice-Id uniqueness constraint

**Why this work:** Issue #94 was a batch of UML-vs-prose alignment fixes in the ACAL Core spec. All items closed except one, which had flip-flopped twice. The spec originally declared `NoticeExpression` as `{ordered, nonunique}`; cdanger changed it to `{ordered, unique}` with an `isUnique(Id)` OCL across six artifacts; we then propagated that into the adoption guide. Steven Legg then objected, and he is right — so this session reversed the whole thing.

**The substance of the reversal** is recorded as an architectural decision (→ notice-id-is-a-concept-identifier). In short: a notice `Id` names the obligation's *meaning* (as XACML 3.0's `ObligationId` did), not a particular occurrence, so requiring uniqueness both breaks compatibility with existing obligation definitions and contradicts §8.16's own evaluation model, which passes notices up from rules into a Result where duplicates are unavoidable.

**What changed:** the constraint was removed from all six places it had been encoded — the core spec's UML/OCL and prose (§7.4, §7.12, §7.37), the two XSD `xs:key`s, three YACAL constraint rules, three JACAL `uniqueKeys` TODO comments, and the PlantUML source. A positive note was added to §7.26/§7.29 explaining *why* the Id is a concept identifier, so the constraint doesn't get reintroduced a third time. The adoption guide's "Multiple Notices Sharing an Action Type" example — which existed purely to teach the distinct-Id workaround — was inverted to demonstrate the traditional same-Id pattern instead.

**Verification approach worth reusing:** rather than trusting the edits, I built policies with duplicate notice Ids and confirmed they were *rejected* by the schema before the change and *accepted* after, with a distinct-Id control passing throughout. Probing the neighbouring `AttributeAssignmentExpression` constraint as a control turned up a long-standing enforcement gap (→ xsd10-unique-silently-skips-absent-optional-fields), filed as spec issue #99.

**Status:** the branch is not merged. cdanger had not yet replied to Steven when the work was done, and this is a normative change, so it needs TC agreement before landing.

### alfa.guide audit + ALFA reader alignment (earlier session)

**Why this work:** The user discovered https://alfa.guide/ and asked for a read-only audit of the ALFA reader against it. The audit identified three categories of gaps: missing combining algorithms, incomplete named function map, and unused bag-attribute metadata (`is_bag` tracked but not acted on). After the audit was presented, the user directed a full implementation pass to close all five gap priorities.

**Combining algorithms:** We implemented 6 of 9 documented algorithms. Added `orderedDenyOverrides`, `orderedPermitOverrides`, and `onPermitApplySecond` to `ACAL_COMBINING_ALGO_MAP`. All 9 are now covered — custom/unknown names still warn (or error under `--strict`) and pass through. (→ acal-combining-algo-map-complete)

**Function map expansion:** The previous `_NAMED_FUNCTION_MAP` covered ~20 functions (basic string, integer, boolean). Expanded to all entries from `system.alfa` — the canonical Axiomatics reference. This adds ~150 entries covering: typed equality, arithmetic, string manipulation, date/time comparisons and arithmetic, type conversion, bag one-and-only/bag-size/is-in/constructor, bag set operations, higher-order bag functions (any-of, all-of, map), match functions, and XPath introspection. The Axiomatics XACML version prefix (`xacml:1.0/2.0/3.0`) is always mapped to `acal:1.0`. Unknown functions still warn + pass through. (→ alfa-function-map-sources-from-system-alfa)

**Bag overloading (V2):** The `is_bag` flag was collected in the symbol table but never used during expression generation. Infix `==` on a bag attribute like `roles == "admin"` was incorrectly producing `string-equal(bag, "admin")`. Now it expands to `string-is-in("admin", bag)` (scalar first, bag second). Type-aware: `datatype = integer` → `integer-is-in`, etc. Uses a private `_bag: True` marker on the attribute designator wrapper dict that is consumed and stripped by `cmp_expr`. `!=` expands to `not(string-is-in(...))`. (→ alfa-bag-overloading-private-marker)

**`type = bag` is a cardinality modifier, not a data type:** When an attribute declares `type = bag`, the string "bag" is a cardinality flag — it should not become the `DataType` in the AttributeDesignator. Fixed: `attr_type` is cleared to `""` when `"bag"` is detected, keeping only `is_bag = True`. A separate `datatype = integer` clause (processed only when `attr_type` is empty) then sets the element type correctly. (→ alfa-bag-type-is-cardinality-not-datatype)

**xpath datatype warning:** Attributes declaring `type = xpath` now emit `UserWarning` at symbol-collection time. The `xpath` datatype has no ACAL 1.0 equivalent; the xpathExpression type was not carried into ACAL 1.0.

**Documentation:** Created `acal-converter/docs/policy-language-expressiveness.md` (was missing despite being referenced in the README). Covers both XACML and ALFA with full gap tables, disposition explanations, alfa.guide link, and the bag overloading V2 semantics. Updated `acal-converter/README.md` to add ALFA to the supported conversions table and add a dedicated ALFA input section referencing alfa.guide.

**New fixtures and tests:** `ordered-deny-overrides.alfa`, `ordered-permit-overrides.alfa`, `bag-comparison.alfa` (string-is-in + integer-is-in), `date-comparison.alfa` (dateGreaterThan + dateLessThanOrEqual + dateFromString). Updated the existing `test_alfa_bag_attribute_is_bag_true` test — it now correctly asserts `string-is-in` and argument order, rather than the old (wrong) `string-equal` output.

**portal.alfa zero-warning smoke test:** Added `test_alfa_portal_zero_unknown_function_warnings` — loads portal.alfa with its full include chain and asserts zero "Unknown ALFA function" warnings. This is the regression gate ensuring the expanded function map stays complete.

## Open Items for Next Session

- **Spec issue #94 branch awaiting TC sign-off**: `xacml-spec` branch `issue-94-notice-id-nonunique` removes the notice-Id uniqueness constraint. Steven Legg argued for it; cdanger had not responded when the work was done. Do not merge without TC agreement — it is a normative change.
- **Spec issue #99**: normative examples (core spec §4, `examples/acal-xpath/Rule3.xml`) violate the `AttributeAssignmentExpression (AttributeId, Category)` uniqueness constraint, and the XSD cannot catch it. Needs both an example fix and a decision on how to enforce it (XSD 1.1 `xs:assert`, or document the gap).
- **Tooling impact of #94**: if that branch lands, any validator enforcing notice-Id uniqueness must drop it. Check `yacal-validator`/`jacal-validator` before their PRs go up.
- **README files**: `acal-core/README.md` is still an empty placeholder. `acal-explain/README.md` was populated in a prior session.
- **Nested attribute resolution**: `user.clearance`, `record.department`, `medicalrecord.patientId` etc. still produce unresolved-attribute warnings (22 in current suite) because nested namespace paths aren't walked. Known limitation; tracked in analyzer output as `unresolved_attrs`.
- **Infix comparison type dispatch**: The `>`, `<`, `>=`, `<=` operators default to `integer-*` functions regardless of attribute type. For double/date/time attributes they should dispatch to typed comparisons. The `==` operator similarly defaults to `string-equal` for non-bag scalar attributes; should dispatch to typed equality. Deferred to a follow-on pass.
- **Streaming output for acal-explain**: `--stream` flag or streaming litellm calls.
- **`acal-explain` end-to-end smoke test** with a real LLM (CI-gated).
- **Phase 7**: Run `/code-review` on the ALFA reader diff.
- **Phase 8**: Refine `import-model` skill with lessons from ALFA implementation and this session.
- **Cross-package pytest fix**: Root conftest.py or pytest.ini for tools-root test discovery.
- **Pre-existing open items**:
  - Create PRs for `yacal-validator` and `jacal-validator` branches
  - Delete `acal-validator` branch once merged
  - Populate root `README.md`
  - File upstream spec bugs (5 items)
  - Publish to PyPI when stable

## Key Diary Files

- [architectural_decisions.md](architectural_decisions.md) — design principles and non-negotiable patterns
- [lessons_learned.md](lessons_learned.md) — anti-patterns and hard-won insights (most recent at top)
