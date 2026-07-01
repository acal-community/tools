# Session Context

## Current State (July 2026)

Three packages on the `acal-converter` branch (includes all `acal-core` and `acal-explain` work):

- **`acal-core/`** — shared library with all format readers, writers, and detection logic. 87 tests.
- **`acal-converter/`** — thin CLI wrapper (`acal-convert`) over `acal-core`. 20 tests.
- **`acal-explain/`** — standalone policy explanation tool. 30 tests.

All 107 tests pass (acal-core: 87, acal-converter: 20). The ALFA reader is now fully aligned with the Axiomatics PDP 7.x dialect as documented on alfa.guide.

## Most Recent Session (July 2026)

### alfa.guide audit + ALFA reader alignment

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
