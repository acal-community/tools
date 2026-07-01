# Policy Language Expressiveness

This document records the design decisions for each source language supported by `acal-converter`: what it can and cannot express in ACAL 1.0, and why the converter behaves the way it does at the boundaries.

---

## XACML 2.0–4.0

**Input-only.** XACML has no first-class output format in this converter because ACAL 1.0 is XACML 4.0 with a simplified structure — XACML-to-ACAL is a projection, not a lossless round-trip.

**No-silent-drops requirement**: every XACML element is either fully converted to its ACAL equivalent or explicitly fails with `XACMLUnsupportedFeatureError`. There is no case where an element is silently omitted.

### Gap table (constructs with disposition other than direct mapping)

| Construct | Disposition | Reason |
|-----------|------------|--------|
| `<CombinerParameters>` | (c) hard error | Removed in ACAL 1.0 |
| `<RuleCombinerParameters>` | (c) hard error | Removed in ACAL 1.0 |
| `<PolicyCombinerParameters>` | (c) hard error | Removed in ACAL 1.0 |
| `EarliestVersion` / `LatestVersion` on `<PolicyIdReference>` | (c) hard error | Removed in ACAL 1.0; use explicit version or encoded URI |
| `<XPathVersion>` in `<PolicyDefaults>` | (c) hard error | XPath profile conversion not implemented |
| `IncludeInResult="true"` | (b) warning + `--strict` error | Response-formatting hint with no evaluation semantics |
| Unrecognised expression/policy child elements | (c) hard error | Unknown → potential silent semantic change |
| XACML 2.0/3.0 `<Request>` body | (c) hard error | Not yet implemented |

Dispositions: **(a)** direct mapping, **(b)** warning (promoted to error under `--strict`), **(c)** hard error always, **(d)** supplementary transformation, **(e)** ACAL model extension required.

---

## Axiomatics PDP 7.x ALFA dialect (as documented on alfa.guide)

**Input-only.** See https://alfa.guide/ for the authoritative Axiomatics PDP 7.x dialect reference.

ALFA (Abbreviated Language for Authorization) was submitted to OASIS as a contribution to the XACML TC in March 2014 but was never published as a formally versioned standard. The de-facto reference implementation is the Axiomatics PDP 7.x dialect, which adds extensions beyond the original OASIS submission. This converter targets that dialect.

**Reader**: `acal-core/src/acal_core/readers/alfa.py`  
**Grammar**: Lark-based custom grammar (not ANTLR) — see `alfa-reader-uses-lark-not-antlr` in the diary.  
**Strategy**: Two-pass — symbol collection (attribute/obligation/advice declarations), then transformation.

### Why input-only

ALFA cannot be a round-trip target because:
1. ALFA requires explicit attribute declarations with categories; the ACAL neutral dict does not guarantee these are preserved with original short names.
2. ALFA's combining algorithm short names (`denyOverrides`) do not cover all ACAL 1.0 algorithms (e.g., `deny-unless-permit` has no ALFA keyword equivalent in all PDP versions).
3. ALFA policy identifiers are inferred from the namespace hierarchy at conversion time; the original namespace cannot be reliably reconstructed from a flat `PolicyId`.

### Alignment with alfa.guide

#### Combining algorithms (all 9 covered as of July 2026)

| ALFA name | ACAL 1.0 URN |
|-----------|-------------|
| `denyOverrides` | `…:combining-algorithm:deny-overrides` |
| `permitOverrides` | `…:combining-algorithm:permit-overrides` |
| `firstApplicable` | `…:combining-algorithm:first-applicable` |
| `orderedDenyOverrides` | `…:combining-algorithm:ordered-deny-overrides` |
| `orderedPermitOverrides` | `…:combining-algorithm:ordered-permit-overrides` |
| `denyUnlessPermit` | `…:combining-algorithm:deny-unless-permit` |
| `permitUnlessDeny` | `…:combining-algorithm:permit-unless-deny` |
| `onlyOneApplicable` | `…:combining-algorithm:only-one-applicable` |
| `onPermitApplySecond` | `…:combining-algorithm:on-permit-apply-second` |

Unknown algorithm names: disposition (b) warning / `--strict` error, passed through as-is.

#### Datatypes

All 17 datatypes listed on alfa.guide pass through from attribute declarations to the neutral dict. Exception: `xpath` (no ACAL 1.0 equivalent) produces a `UserWarning` at attribute-declaration parse time.

#### Functions

All `function` entries from `system.alfa` are mapped to ACAL 1.0 URNs in `_NAMED_FUNCTION_MAP`. The mapping covers: equality, arithmetic, string manipulation, type conversion, logical operators, typed comparisons, date/time arithmetic, all bag one-and-only/bag-size/is-in/bag-constructor forms, bag set operations (at-least-one-member-of, subset, set-equals, intersection, union), higher-order bag functions (`any-of`, `all-of`, etc.), match functions, and XPath introspection functions.

Unknown function names: disposition (b) warning / `--strict` error, mapped to `urn:custom:function:<name>`.

#### Bag overloading (V2, July 2026)

When an attribute is declared with `type = bag` (optionally with `datatype = <type>`), the infix `==` operator expands to `<type>-is-in(scalar, bag)` rather than `<type>-equal(bag, scalar)`. The expansion is type-aware: a `bag` attribute with `datatype = integer` uses `integer-is-in`; an untyped bag defaults to `string-is-in`.

`!=` expands to `not(<type>-is-in(...))`.

If the bag's element type has no `is-in` function entry, disposition (b) warning is emitted and `string-equal` is used as a fallback.

### Gap table (ALFA)

| Construct | Disposition | Notes |
|-----------|------------|-------|
| Standard combining algorithms (9) | (a) direct mapping | All 9 from alfa.guide |
| Custom combining algorithm names | (b) warning / `--strict` error | Passed through as-is |
| All `system.alfa` named functions | (a) direct mapping | XACML URN → ACAL 1.0 URN prefix substitution |
| Unknown function names | (b) warning / `--strict` error | Mapped to `urn:custom:function:<name>` |
| Infix `==` / `!=` on bag attributes | (d) bag expansion | `<type>-is-in(scalar, bag)` / negated |
| Infix `==` / `!=` on scalar attributes | (a) direct mapping | `string-equal` (current default; type dispatch planned) |
| Infix `>` `<` `>=` `<=` | (a) direct mapping | Default: integer comparisons; explicit typed functions available via named calls |
| `xpath` attribute datatype | (b) warning | No ACAL 1.0 equivalent |
| `import` statement | (d) no-op | Runtime PDP hint; symbol loading handled by `--include` |
| `system.alfa` declarations | (d) discard | PDP runtime config; no ACAL equivalent |
| Attribute path `Attributes.<cat>.<id>` | (a) direct mapping | Canonical form |
| Attribute shorthand (declared `attribute {}`) | (a) direct mapping | Resolved via symbol table |
| Unresolvable attribute path | (b) warning / `--strict` error | Empty category in output |
| Undeclared obligation/advice URN | (b) warning / `--strict` error | Short name passed through |

### Structural elements (all fully supported)

`namespace` (nested), `policyset`, `policy`, `rule`, `target clause`, `condition`, `on permit/deny`, `obligation`, `advice`, `attribute`, `import`, `var`, `variable()`, `system.alfa` declarations, infix operators (`==`, `!=`, `>`, `<`, `>=`, `<=`, `&&`, `||`, `!`, `and`, `or`), policy cross-references (`ref_stmt`).

### `--strict` / `--no-strict` behaviour

Under `--no-strict` (default): custom combining algorithms, unknown functions, unresolvable attributes, undeclared obligation URNs, and `xpath` type declarations emit `UserWarning` and conversion proceeds.

Under `--strict`: all of the above raise `ALFAUnsupportedFeatureError`.

### Example: policy that cannot round-trip

```alfa
namespace com.example {
    policy MyPolicy apply denyOverrides {
        rule allow {
            permit
            condition Attributes.subject.role == "editor"
        }
    }
}
```

After conversion to YACAL, the `PolicyId` becomes `com.example.MyPolicy`. Round-tripping back to ALFA would require reconstructing the `namespace com.example { policy MyPolicy ... }` nesting from the flat `PolicyId` — this is not generally possible for arbitrary URN-style IDs, so ALFA is input-only.
