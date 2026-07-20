# Policy Language Expressiveness: Why Some Conversions Are One-Way

This document explains the design decisions behind which conversions `acal-convert`
supports in each direction, and why ACAL is a more expressive target than most
other policy languages. It is intended to grow: each new language reader should
add a section following the template below.

---

## The core principle

**ACAL is a superset.** It was designed to capture everything that XACML 3.0 and
4.0 can express, while also addressing gaps and inconsistencies those languages
accumulated over time. As a result, any policy language that is less expressive
than XACML can represent only a subset of ACAL concepts. Converting *to* such a
language means deciding what to discard — and discarding policy semantics silently
is dangerous.

The `acal-convert` tool therefore expresses this asymmetry directly:

- Languages that cannot represent all ACAL concepts are **input-only**.
- For each such language, this document explains *what* is lost and *why*, with
  concrete examples.
- The loss is not incidental. It reflects deliberate design choices in those
  languages. Understanding those choices is part of understanding why ACAL has
  the structure it does.

---

## XACML 2.0–4.0

### XACML 4.0 is the hub. XACML 2.0 and 3.0 are spokes.

These are not three versions of one input language. They are two different things that
happen to share a file extension:

- **XACML 4.0 is the XML serialization of ACAL 1.0 itself.** It is *native*: it expresses the
  whole ACAL model by construction, identifiers are already ACAL URNs (the reader does no
  remapping), and it carries `Bundle` and `SharedVariableDefinition` natively. It has no
  capability matrix, because there is nothing it cannot say.
- **XACML 2.0 and 3.0 are foreign dialects**, in exactly the sense ALFA and Cedar are. They
  predate ACAL, their identifiers are remapped on import, and each has its own capability
  matrix under [`../capabilities/`](../capabilities/).

Capability is a property of the **dialect**, not the file extension. Treating "XACML" as one
language produced a matrix asserting that XACML cannot express `SharedVariableDefinition` —
true of 3.0, false of 4.0.

### Why there is no XACML *writer* (yet)

Only that XACML 4.0 output has not been built. It is **not** blocked, and it is **not** the
hard export problem.

An earlier version of this document said XACML output was blocked because the toolchain for
authoritative XML generation (Saxon EE) is commercially licensed. That repeats a conflation
this project has already caught once (→ `xml-parsing-vs-xml-schema-validation` in the diary):
**Saxon EE is required to *validate* XML against XSD 1.1, not to *write* it.** Generating
XACML 4.0 XML is `xml.etree.ElementTree`, exactly as reading it is.

Because XACML 4.0 is a serialization of the hub rather than a foreign target, an
`writers/xacml.py` belongs beside the YACAL and JACAL writers — not in the `acal-export` tool,
which exists to solve the genuinely hard problem of emitting into *less expressive* languages.

Writing it would also settle GitHub issue #1 ("Automatic conversion from XACML 3.0 to XACML
4.0"), which is just `load(xacml-3.0) → neutral dict → write(xacml-4.0)`: import a spoke,
serialize the hub. Tracked in [`../../ROADMAP.md`](../../ROADMAP.md).

### The no-silent-drops requirement

**Every element in an XACML input document must be explicitly accounted for.
No element may be silently ignored.**

This is a hard requirement, not a style preference. The output of `acal-convert`
is access-control policy. A converted policy that silently omits a constraint —
a combining-algorithm parameter, a version restriction, an obligation, or an
expression argument — is a *different policy* from the one the author wrote.
It may grant access that the original denied. The user has no way to detect this
if the converter produces structurally valid output without signalling the loss.

The converter enforces this in two ways:

1. **Removed constructs raise immediately.** If an XACML element or attribute
   was explicitly removed in ACAL 1.0, the converter raises
   `XACMLUnsupportedFeatureError` with a message explaining the removal and
   offering alternatives. There is no "best-effort" fallback.

2. **Unrecognised constructs also raise.** If the converter encounters an element
   name it does not recognise — including elements that are valid XACML but whose
   conversion is not yet implemented — it raises rather than skipping. This
   applies at every level: expression arguments inside `<Apply>` or `<Condition>`,
   structural children of `<Policy>` or `<PolicySet>`, and request body structures
   that differ from the expected XACML version.

The distinction between "removed" and "unimplemented" matters for the error
message (one directs users to redesign; the other invites a bug report) but not
for the outcome: both categories produce an unconditional failure.

**The one exception is `IncludeInResult`.** This XACML 2.0/3.0 request attribute
flag has no effect on policy *evaluation* — it only influenced response formatting.
ACAL 1.0 replaced it with the more explicit `ResultEntity` model.

Behavior is controlled by the `--strict` / `--no-strict` CLI flag (and the
`strict=` parameter on `convert()` and `load()`):

- `--strict` (or `strict=True`): Raises `XACMLUnsupportedFeatureError`
- `--no-strict` (default): Emits a `UserWarning`

The surrounding XACML 2.0/3.0 `<Attributes>` request body still raises as
unimplemented, so in practice a warning is usually followed by an error — but
the two concerns are kept separate because they describe different problems.

Version handling is implemented via the `XACMLVersion` enum (in `readers/xacml.py`).
Namespace detection selects the correct version; the internal neutral ACAL dict
remains version-agnostic (with optional `SourceVersion` metadata for provenance).

### Removed XACML constructs and why they are errors

#### `CombinerParameters`, `RuleCombinerParameters`, `PolicyCombinerParameters`

These elements allowed passing arbitrary parameters to a combining algorithm.
ACAL 1.0 removed them because no standard combining algorithm ever used them,
and they created undefined behavior when a PDP did not recognize the parameters.
No ACAL-equivalent construct exists.

**Disposition:** Error. The error message directs users to the XACML TC and
suggests re-designing the combining algorithm without parameters — for example,
by using a policy-level variable or a custom combining algorithm identified by a
distinct URN that encodes its parameterization.

#### `EarliestVersion` / `LatestVersion` on `PolicyIdReference`

These attributes allowed a policy set to reference a range of acceptable policy
versions rather than a single version. ACAL 1.0 removed them because version
ranges create non-determinism: different PDPs may resolve the same reference to
different policy versions, depending on which versions they have cached.

**Disposition:** Error. The error message offers three concrete alternatives:

1. **Explicit version:** pin to a specific `Version` attribute. This is the
   most common replacement and works for any PDP.

2. **Version pattern:** ACAL's `Version` attribute supports glob-like patterns
   (e.g. `1.*`) for matching a family of minor versions while still constraining
   the major version. This is a more precise replacement for simple range cases.

3. **URI-encoded version:** include version information in the `PolicyId` URI
   itself using query parameters or path segments (e.g.
   `urn:example:policy:access-control?minVersion=1.0`). This delegates version
   resolution logic to the policy management layer, where it belongs.

#### `XPathVersion` in `PolicyDefaults`

This element specified which XPath version (1.0 or 2.0) should be used when
evaluating XPath expressions in `AttributeSelector` elements. ACAL 1.0 moved
XPath support into a dedicated *XPath Profile*, separating it from core so that
PDPs that do not support XPath do not need to implement it.

**Disposition:** Error. XPath profile conversion is not yet implemented in this
tool. The error message invites the user to contact the XACML TC or remove the
element if their policy does not actually use XPath selectors. A future
`--xpath-profile` option could enable conversion of XPath-related elements when
the profile mapping is fully implemented.

#### `IncludeInResult` on request `<Attribute>`

This attribute asked the PDP to echo a specific request attribute back in its
response. ACAL 1.0 removed it because the response format was redesigned: the
`ResultEntity` construct gives the policy author explicit control over which
attributes appear in results, making the per-attribute flag unnecessary and
redundant.

**Disposition:** Warning (not error). `IncludeInResult` has no effect on policy
*evaluation* — it only affects response formatting. Aborting the conversion
would be disproportionate: the converted ACAL policy evaluates identically to
the original. The warning names the offending attribute so the user can decide
whether to re-express the intent using `ResultEntity` in their ACAL policy.

---

## ALFA (Abbreviated Language for Authorization)

*Reader: `acal-core/src/acal_core/readers/alfa.py`. Aligned with alfa.guide as of July 2026.*

ALFA is a DSL developed within the OASIS XACML ecosystem as a human-readable alternative to XACML 3.0 XML. It uses a C/Java-like syntax with braces, keywords, and dot-notation attribute access. ALFA compiles conceptually to XACML 3.0 — meaning its semantic model aligns closely with XACML 3.0, not ACAL 1.0 directly. The ALFA reader translates the ALFA tree into the ACAL neutral dict, with remapping handled by the same patterns used in the XACML 3.0 reader where applicable.

ALFA was submitted to OASIS as a contribution to the XACML TC in March 2014 but was never published as a formally versioned standard. The de-facto reference implementation is the **Axiomatics PDP 7.x dialect**, documented at <https://alfa.guide/>, which adds extensions beyond the original OASIS submission. This reader targets that dialect.

### Why ALFA is input-only

ALFA output would require generating valid ALFA syntax from the ACAL neutral dict. Several ACAL 1.0 features introduced after XACML 3.0 — most notably `SharedVariableDefinition` in a `Bundle`, combining algorithm URNs not in ALFA's keyword set, and arbitrary `RequestEntity`/`ResultEntity` structures — have no ALFA syntax equivalent. Round-tripping is lossless in principle only for the subset of ACAL expressible in ALFA. Because that subset is not the full ACAL model, ALFA output is not implemented; the conversion is one-way.

### The no-silent-drops requirement

As with all readers, every ALFA construct encountered must be explicitly handled. Unrecognised tokens or constructs that the reader does not know how to map must raise `ALFAUnsupportedFeatureError`, not silently pass. The two-pass architecture (symbol table collection → expression resolution) must not allow any path or identifier to fall through unresolved without a warning or error.

### Parser and error types

ALFA is a DSL, not a structured data format. The reader uses the `lark` parsing library with a custom ALFA grammar. Two exception types are defined, both inheriting from `ValueError` (matching the `XACMLUnsupportedFeatureError` precedent):

- `ALFASyntaxError(ValueError)` — raised when the input is not valid ALFA syntax (parse failure). Raised in pass 1 (symbol collection) for structurally malformed declarations. Inherits `ValueError` rather than stdlib `SyntaxError` because it is application-level input validation, not an interpreter error.
- `ALFAUnsupportedFeatureError(ValueError)` — raised when a syntactically valid ALFA construct has no ACAL equivalent, or when a warning-eligible construct is encountered under `--strict`. Re-exported from `readers/__init__.py` so callers can catch it by name without importing the reader module directly.

### Gap table

| ALFA Construct | ACAL Mapping | Disposition | Strict behavior |
|---|---|---|---|
| `namespace` + element name | `PolicyId` synthesized as dot-joined namespace hierarchy + element name | (d) Supplementary | N/A |
| No version field | `Version` absent in output (ACAL field is optional) | — no gap | N/A |
| Standard `apply` keywords | `CombiningAlgId` URN via static keyword lookup table | (a) Direct | N/A |
| Custom `apply` identifier | Bare string in `CombiningAlgId` + `UserWarning` | (b) Lossy/warn | Error under `--strict` |
| Anonymous rule | `Id` synthesized as `{parent-policy-id}:rule_{n}` | (d) Supplementary | N/A |
| `permit` / `deny` | `Effect: Permit` / `Effect: Deny` | (a) Direct | N/A |
| `target` and `condition` coexist | Both translated independently | (a) Direct | N/A |
| `Attributes.subject.*` etc. canonical paths | `AttributeDesignator` via reserved category URN lookup | (a) Direct | N/A |
| Shorthand attribute paths | Resolved via symbol table from `attribute { category=... }` blocks | (d) Supplementary | N/A |
| Unresolvable attribute paths | `UserWarning` naming the path | (b) Lossy/warn | Error under `--strict` |
| Infix operators (`==`, `!=`, `>`, `<`, `&&`, `\|\|`, `!`) | `Apply` with `FunctionId` URN from operator map | (d) Supplementary | N/A |
| Named function calls (`stringContains(...)` etc.) | `Apply` with `FunctionId` URN from function name map | (d) Supplementary | N/A |
| Unknown function names | `Apply` with `urn:custom:function:{name}` + `UserWarning` | (b) Lossy/warn | Error under `--strict` |
| Infix `==` / `!=` on **bag** attributes | `<type>-is-in(scalar, bag)`, negated for `!=` | (d) Supplementary | N/A |
| Bag element type with no `is-in` function | Falls back to `string-equal` + `UserWarning` | (b) Lossy/warn | Error under `--strict` |
| `xpath` attribute datatype | Passed through; no ACAL 1.0 equivalent | (b) Lossy/warn | Error under `--strict` |
| `import` statement | No-op; symbol loading is handled by `--include` | (d) Supplementary | N/A |
| `system.alfa` declarations | Discarded — PDP runtime config, no ACAL equivalent | (d) Supplementary | N/A |
| `obligation` in `on permit` / `on deny` | `NoticeExpression { IsObligation: true, AppliesTo: Permit/Deny }` | (a) Direct | N/A |
| `advice` in `on permit` / `on deny` | `NoticeExpression { IsObligation: false, AppliesTo: Permit/Deny }` | (a) Direct | N/A |
| Obligation/advice URN (from namespace declaration) | Resolved from symbol table | (d) Supplementary | N/A |
| `variable` declaration (policy-scoped) | `VariableDefinition` within enclosing policy | (a) Direct | N/A |
| `variable(name)` reference | `VariableReference` | (a) Direct | N/A |
| `SharedVariableDefinition` | No ALFA equivalent in V1 — deferred | — future | N/A |
| Request / response structures | Not part of ALFA — reader produces policy side only | — N/A | N/A |

### Two-pass architecture and symbol table

ALFA attribute access uses both a canonical form (`Attributes.subject.role`) and a shorthand form (`user.role` where `user` is bound to `category = subjectCat` in an `attribute` block). A single-pass translator cannot resolve shorthand paths without first knowing the declarations.

The reader operates in two passes over the Lark parse tree:

1. **Symbol table pass** — `_collect_symbols(tree)` walks the raw Lark `Tree` before any `Transformer` runs. It populates a `_SymbolTable` with:
   - `namespace_parts: list[str]` — the nested namespace hierarchy, used to synthesize `PolicyId`
   - `attributes: dict[str, _AttributeDecl]` — local alias → `{ id, category, type, is_bag }`; used to resolve shorthand paths and determine bag-ness for `==` expansion
   - `obligations: dict[str, str]` — local name → URN; declared at namespace level
   - `advice: dict[str, str]` — local name → URN; declared at namespace level
   - Malformed declarations raise `ALFASyntaxError` immediately.
2. **Resolution pass** — `AlfaTransformer(symbols, strict)` runs as a standard Lark `Transformer`. It holds the `_SymbolTable` as `self._symbols` and resolves paths, names, and type-dependent operator expansions during tree transformation. Policy-scoped variables are tracked in `self._current_vars` (a `dict` reset at each `policy_declaration` entry).

**Unresolvable references:** attribute paths or obligation/advice names not found in the symbol table emit `warnings.warn(..., UserWarning)` in non-strict mode and `raise ALFAUnsupportedFeatureError(...)` in strict mode.

Paths that remain unresolvable after both passes write the raw path string into the output and emit a `UserWarning` (or raise under `--strict`).

### Bag overloading (V2, July 2026)

When an attribute is declared with `type = bag` (optionally with `datatype = <type>`), the
infix `==` operator expands to `<type>-is-in(scalar, bag)` rather than
`<type>-equal(bag, scalar)`. The expansion is **type-aware**: a `bag` attribute with
`datatype = integer` uses `integer-is-in`; an untyped bag defaults to `string-is-in`.

`!=` expands to `not(<type>-is-in(...))`.

If the bag's element type has no `is-in` entry in the function map, a `UserWarning` is
emitted — disposition (b) — and `string-equal` is used as a fallback.

### Combining algorithm keyword map

All 9 algorithms on alfa.guide are covered (July 2026). Every URN below is prefixed
`urn:oasis:names:tc:acal:1.0:combining-algorithm:`.

| ALFA keyword | ACAL 1.0 suffix |
|---|---|
| `denyOverrides` | `deny-overrides` |
| `permitOverrides` | `permit-overrides` |
| `firstApplicable` | `first-applicable` |
| `orderedDenyOverrides` | `ordered-deny-overrides` |
| `orderedPermitOverrides` | `ordered-permit-overrides` |
| `denyUnlessPermit` | `deny-unless-permit` |
| `permitUnlessDeny` | `permit-unless-deny` |
| `onlyOneApplicable` | `only-one-applicable` |
| `onPermitApplySecond` | `on-permit-apply-second` |

Unknown algorithm names are passed through as-is with a `UserWarning` — disposition (b),
promoted to `ALFAUnsupportedFeatureError` under `--strict`.

### Datatypes

All 17 datatypes listed on alfa.guide pass through from attribute declarations to the
neutral dict. The one exception is `xpath`, which has no ACAL 1.0 equivalent (ACAL 1.0
does not include the `xpathExpression` data type) and emits a `UserWarning` at
attribute-declaration parse time — disposition (b).

### Functions

All `function` entries from `system.alfa` are mapped to ACAL 1.0 URNs in
`_NAMED_FUNCTION_MAP`. The map covers equality, arithmetic, string manipulation, type
conversion, logical operators, typed comparisons, date/time arithmetic, every bag
one-and-only / bag-size / is-in / bag-constructor form, bag set operations
(at-least-one-member-of, subset, set-equals, intersection, union), higher-order bag
functions (`any-of`, `all-of`, …), match functions, and XPath introspection functions.

Unknown function names map to `urn:custom:function:<name>` with a `UserWarning` —
disposition (b).

### Category URN map

```python
ACAL_CATEGORY_MAP = {
    "subject":     "urn:oasis:names:tc:acal:1.0:subject-category:access-subject",
    "resource":    "urn:oasis:names:tc:acal:1.0:attribute-category:resource",
    "action":      "urn:oasis:names:tc:acal:1.0:attribute-category:action",
    "environment": "urn:oasis:names:tc:acal:1.0:attribute-category:environment",
}
```

### Structural elements (all fully supported)

`namespace` (nested), `policyset`, `policy`, `rule`, `target clause`, `condition`,
`on permit` / `on deny`, `obligation`, `advice`, `attribute`, `import`, `var`,
`variable()`, `system.alfa` declarations, the infix operators (`==`, `!=`, `>`, `<`,
`>=`, `<=`, `&&`, `||`, `!`, `and`, `or`), and policy cross-references (`ref_stmt`).

### `--strict` / `--no-strict` behaviour

Under `--no-strict` (the default), all disposition-(b) constructs emit a `UserWarning`
and conversion proceeds: custom combining algorithms, unknown functions, unresolvable
attribute paths, undeclared obligation/advice URNs, `xpath` type declarations, and
bag-fallback comparisons.

Under `--strict`, every one of them raises `ALFAUnsupportedFeatureError` instead.

### Auto-detection

- **Content sniff:** reads up to 256 bytes, skips leading UTF-8 BOM and whitespace, skips leading C-style comments (`// ...` lines and `/* ... */` blocks), then inspects the first keyword token. If the token is `namespace` or `import` **and** the character immediately following it (after optional whitespace) is `{` or a letter (not `:`), the file is identified as ALFA. The two-token check (`namespace {` vs `namespace:`) prevents misidentification of YAML files that use `namespace` as a key. Valid ACAL YACAL documents are further distinguished because their root keys are a closed capitalized set (`Policy`, `Bundle`, `Request`, `Response`, `ShortIdSet`) — none of which collide with ALFA keywords.
- **Extension fallback:** `.alfa` → `alfa`.
- **Explicit override:** `--from alfa` / `from_fmt="alfa"` always takes precedence over both.

### Example: an ACAL policy that cannot round-trip back to ALFA

```yaml
Bundle:
  BundleId: urn:example:bundle:shared
  SharedVariableDefinition:
    - Id: urn:example:shared:editor-check
      Expression:
        Apply:
          FunctionId: urn:oasis:names:tc:acal:1.0:function:string-contains
          Argument:
            - AttributeDesignator:
                Category: urn:oasis:names:tc:acal:1.0:subject-category:access-subject
                AttributeId: urn:example:attribute:role
            - Value: editor
  Policy:
    - PolicyId: urn:example:policy:doc-access
      CombiningAlgId: urn:oasis:names:tc:acal:1.0:combining-algorithm:permit-unless-deny
      CombinerInput:
        - Rule:
            Id: permit-editors
            Effect: Permit
            Condition:
              SharedVariableReference:
                VariableId: urn:example:shared:editor-check
```

This ACAL policy cannot be expressed in ALFA because:

1. `SharedVariableDefinition` in a `Bundle` — ALFA has no cross-policy variable sharing. Variables are strictly scoped to the enclosing `policy` block. A shared variable accessible to multiple policies requires either duplicating the `variable` declaration in each policy or restructuring the policy set.

2. `urn:oasis:names:tc:acal:1.0:combining-algorithm:permit-unless-deny` — this is an ACAL 1.0 combining algorithm. While `permitUnlessDeny` is in ALFA's keyword set and maps to the same URN, the reverse is only true for the exact standard set. Any ACAL policy that uses a combining algorithm URN without a matching ALFA keyword cannot round-trip.

**Verdict:** ALFA is input-only. The ALFA semantic model is a proper subset of ACAL 1.0: every policy expressible in ALFA can be converted to ACAL, but not every ACAL policy can be expressed in ALFA.

---

## Cedar (AWS)

*Reader: `acal-core/src/acal_core/readers/cedar.py`. Capability matrix and datatype map:
[`../capabilities/cedar.yaml`](../capabilities/cedar.yaml).*

Cedar is Amazon's policy language for fine-grained authorization. It is typed, attribute-based,
and deliberately kept simple so that policies can be formally analyzed. That simplicity is the
source of every gap below: the things Cedar cannot say, it declines to say *on purpose*.

**Parser**: Cedar's own. `cedarpy` wraps the upstream Rust `cedar-policy` crate and exposes
`policies_to_json_str()`, which produces Cedar's official JSON AST (the EST). We map that AST;
we do not parse Cedar ourselves. This is a deliberate correctness choice — a hand-written
grammar's idea of Cedar can drift from Cedar's as the language evolves, and it would drift
*silently*. Cedar parses; we only translate.

### Why Cedar is input-only

Two of the gaps are not edge cases, they are central to Cedar's design:

- **No combining algorithms.** Cedar has exactly one, implicit strategy — forbid overrides
  permit, and anything unmatched is denied. ACAL's `permit-overrides`, `first-applicable`,
  `only-one-applicable` and custom algorithm URNs have no Cedar expression at all.
- **No obligations.** Cedar has no post-decision side-effect model. An ACAL policy that
  *mandates* the PEP log, notify, or redact as a condition of enforcement cannot carry that
  requirement into Cedar; the obligation would have to move into application code, losing the
  enforceable guarantee.

### Combining semantics — the exact encoding

Cedar allows a request iff **some `permit` matches and no `forbid` matches**; otherwise it
denies. Reproducing that faithfully takes two nested policies:

```yaml
Policy:                                    # outer
  CombiningAlgId: '{deny-unless-permit}'
  CombinerInput:
    - Policy:                              # inner
        CombiningAlgId: '{deny-overrides}'
        CombinerInput:
          - Rule: { Effect: Deny,   ... }  # forbid
          - Rule: { Effect: Permit, ... }  # permit
```

| Cedar situation | inner (`deny-overrides`) | outer (`deny-unless-permit`) | Cedar |
|---|---|---|---|
| a `forbid` matches | Deny | **Deny** | Deny |
| a `permit` matches, no forbid | Permit | **Permit** | Permit |
| nothing matches | NotApplicable | **Deny** | Deny |

The naive choice — a single `deny-unless-permit` policy — is **wrong**: it returns Permit if
*any* permit applies, even when a `forbid` also applies, which silently turns every `forbid`
into a no-op. The naive alternative — a single `deny-overrides` policy — is *nearly* right but
returns `NotApplicable` where Cedar returns Deny, leaving the default-deny to the PEP's bias
rather than stating it in the policy.

### Entity model — a PDP attribute contract

Cedar has typed entities and an entity hierarchy (`principal == User::"alice"`,
`principal is User`, `principal in Group::"doctors"`). ACAL has flat attribute categories: no
entity types, no hierarchy. The import maps them onto three reserved attributes:

| Cedar | ACAL attribute | Function |
|---|---|---|
| `principal == User::"alice"` | `urn:cedar:1.0:entity-uid` | `{string-equal}` |
| `principal is User` | `urn:cedar:1.0:entity-type` | `{string-equal}` |
| `principal in Group::"doctors"` | `urn:cedar:1.0:entity-ancestors` (bag) | `{string-is-in}` |

### Missing attributes — Cedar fails open, and so do we

This was settled by asking Cedar's own evaluator rather than by reasoning about it:

```
forbid (principal, action, resource) when { principal.banned == true };
   ...evaluated against a principal with no `banned` attribute

Cedar's decision:  ALLOW
Cedar's diagnostic: error while evaluating policy `policy1`:
                    `User::"alice"` does not have the attribute `banned`
```

**Cedar skips a policy it cannot evaluate.** A `forbid` that references an absent attribute
does not fire, and the request is allowed. Cedar's compensating control is its *schema
validator*, which catches the missing attribute at authoring time — and that control does not
exist on the ACAL side.

Every synthesized `AttributeDesignator` is therefore emitted with **`MustBePresent: false`**,
which reproduces Cedar exactly: an absent attribute yields an empty bag, the condition is
false, the rule does not fire. Setting `true` would be *safer* than Cedar — an absent attribute
would become Indeterminate and deny — but it would also **change the decision**, and a
converter that changes decisions is not a converter. The deviation is offered, not imposed:

- **default** — faithful. The conversion emits a fidelity note stating that the policy inherits
  Cedar's fail-open behaviour on missing attributes and should be paired with a PDP that
  populates every attribute the policy reads.
- **`--fail-closed`** — rewrites every synthesized designator to `MustBePresent: true`, so a
  `forbid` whose attribute is missing **denies** instead of being skipped. A deliberate,
  declared deviation from the source.

One exception, and it is not a safety hole: inside a `has` operand, `MustBePresent` is always
`false` even under `--fail-closed`, because "is this attribute present?" is precisely the
question `has` asks. Making it Indeterminate would break the guard that Cedar policies use to
*avoid* the missing-attribute error in the first place.

This generalizes past Cedar (→ `presence-semantics-must-be-explicit`): every reader states
`MustBePresent` explicitly and sets it to reproduce the source language's real runtime
behaviour. Leaving it unstated — as the ALFA reader did — makes the converted policy's
behaviour depend on a schema default rather than on anything the source language meant.

### Datatypes — the resolution ladder

Cedar's extension types (`decimal`, `ipaddr`, `datetime`) are a different type system from
ACAL's, and this is where a careless converter does real damage. Resolution walks a ladder
defined in [`../capabilities/cedar.yaml`](../capabilities/cedar.yaml):

1. a **built-in direct mapping** exists (`bool`, `long`, `string`, `set`) → proceed, exact;
2. else a **`datatypes:` entry** exists → proceed; if `fidelity: approximate`, warn (b);
3. else → **hard error** (c), naming the missing entry.

One type ships deliberately **unmapped**, and the reasoning matters more than the verdict:

- **`ipaddr`** — ACAL 1.0 has no IP-address datatype and no CIDR/range function. Mapping
  `isInRange` onto string comparison would silently turn a subnet check into a text match: a
  different policy, and one that fails open. We decline to guess. Supply an `acal_type` and a
  `functions:` map and the reader will use it.

**`record` — reading vs. constructing.** *Reading* a nested attribute chain (`principal.a.b`,
and bracket-index `a["k"]`, which Cedar's EST represents identically to `.b`) flattens into one
compound dotted AttributeId — `AttributeId: "a.b"` — exactly as the single-level case already
flattens `resource.owner` into `AttributeId: "owner"`; a deeper path just needs one more flat
value from the PDP, not a new kind of risk. This unlocked the majority of the real-world
cedar-examples corpus (sales_orgs, streaming_service, tags_n_roles, github's nested
`resource.repo.readers`), all of which only ever *read* through a record/entity chain. Warned
once per document (b), since the dotted-path naming is a project convention, not a Cedar
concept the PDP already knows.

*Constructing* a Record as a value — an inline `{ organization: ..., location: ... }` literal,
as tax_preparer builds to pass to `.contains(...)` — remains a hard error (c): ACAL has no
composite Value type, so there is nowhere for an ad-hoc, unnamed structural value to land. This
is the one gap left in the corpus.

**`decimal` maps to `double` but is marked `approximate`**, and warns on every use: Cedar
decimal is fixed-point to 4 places, ACAL double is IEEE-754 binary float. A comparison at a
precision boundary can decide differently — which, in an authorization policy, means someone
gets access they should not. `--strict` turns it into a hard error.

### Templates, and the shape of the output

A Cedar *template link* — the thing that binds `?principal` to a concrete entity — is a
**runtime instantiation**, supplied through Cedar's policy-set / entities API. It is never
present in policy *text*: `policies_to_json_str` on a `.cedar` file always returns
`templateLinks: []`. So a template in a file is **uninstantiated** — it binds to nothing and,
in Cedar, participates in no decision until a link is created elsewhere.

The reader reproduces exactly that. A template converts to a parameterized `Policy` (its
`?slot` becomes a `Parameter`, referenced by a `VariableReference`), but it is placed **inert
in the Bundle's definition pool** — reachable only by reference, and nothing in a text file
ever references it. It carries a disposition-(b) warning that it is uninstantiated; `--strict`
rejects it.

This drives the output shape, which is chosen so the *active* policy is never ambiguous:

| Input | Output |
|---|---|
| static policies only | a single top-level `Policy` (the combining wrapper) — no Bundle, no pool |
| templates + static policies | a `Bundle` whose `PolicyReference` **names the active policy as the entry point**; templates sit inert in `Bundle.Policy[]` |
| templates only | a `Bundle` of inert definitions with **no entry point**, plus a warning that the document expresses no active policy |

The entry point matters: `Bundle.Policy[]` is a *definition pool*, not a set of independently
active policies, and `Bundle.PolicyReference` names the one that decides. Emitting a multi-policy
Bundle without it would leave the decision root ambiguous.

### Gap table

| Source construct | ACAL mapping | Disposition | Strict behavior |
|---|---|---|---|
| `permit` / `forbid` | `Rule` with `Effect: Permit` / `Deny` | (a) Direct | N/A |
| Cedar policy-set semantics | outer `deny-unless-permit` ▸ inner `deny-overrides` | (d) Supplementary | N/A |
| `@id("x")` | `Rule.Id` / `PolicyId` | (a) Direct | N/A |
| Any other `@annotation` | none — no evaluation semantics | (b) Lossy/warn | Error |
| Scope `op: All` | no Target contribution | (a) Direct | N/A |
| Scope `== Entity::"x"` | `{string-equal}` on `entity-uid`, `MustBePresent: false` | (d) Supplementary | N/A |
| Scope `is Type` | `{string-equal}` on `entity-type`, `MustBePresent: false` | (d) Supplementary | N/A |
| Scope `in Entity::"x"` / `in [Entity::"x", Entity::"y"]` | `{string-is-in}` over `entity-ancestors`, OR'd across every listed entity, `MustBePresent: false` | (d) Supplementary | N/A |
| Expr `X in Y` (`principal in resource.readers`, `in [..]`, `in Var`) | same `entity-ancestors` translation as scope `in`, requiring the left operand to be `principal`/`action`/`resource` directly | (d) Supplementary | N/A |
| Expr `X is Type` / `X is Type in Y` | same `entity-type` (and `entity-ancestors` if combined with `in`) translation as scope `is`, same left-operand requirement | (d) Supplementary | N/A |
| `when { … }` | `Condition` | (a) Direct | N/A |
| `unless { … }` | `Condition` wrapped in `{not}` | (d) Supplementary | N/A |
| `&&` `\|\|` `!` | `{and}` / `{or}` / `{not}` | (a) Direct | N/A |
| `==` `!=` | `{<type>-equal}`, type inferred from the literal operand | (d) Supplementary | N/A |
| `<` `<=` `>` `>=` | `{integer-*}` comparisons | (a) Direct | N/A |
| `+` `-` `*` | `{integer-add}` / `{integer-subtract}` / `{integer-multiply}` | (a) Direct | N/A |
| `.attr` | `AttributeDesignator` | (a) Direct | N/A |
| `.attr.attr` / `["key"]` chain (any depth) | `AttributeDesignator` on one compound dotted `AttributeId` | (b) Lossy/warn | Error |
| `has attr` (bare or chained) | `{<type>-bag-size}(…) > 0` | (d) Supplementary | N/A |
| `contains` | `{<type>-is-in}` | (a) Direct | N/A |
| `containsAll` | `{<type>-subset}` | (d) Supplementary | N/A |
| `containsAny` | `{<type>-at-least-one-member-of}` | (a) Direct | N/A |
| `like "a*"` | `{string-regexp-match}`, glob translated to an anchored regex | (d) Supplementary | N/A |
| Set literal | `Apply {<type>-bag}` | (a) Direct | N/A |
| Template + `?slot` | inert parameterized `Policy` in the Bundle pool + warning | (b) Lossy/warn | Error |
| `if-then-else` (boolean position) | `(c && t) \|\| (!c && e)` | (d) Supplementary | N/A |
| `if-then-else` (non-boolean) | none | (c) Hard error | Error |
| `decimal` and its functions | `{double}` family | (b) Lossy/warn | Error |
| Record *literal* (`{a: 1, b: "x"}`) as a value | none — ACAL has no composite Value type | (c) Hard error | Error |
| `ipaddr`, unmapped extension fns | none — see the ladder | (c) Hard error | Error |
| Missing attribute at evaluation | `MustBePresent: false` — reproduces Cedar's fail-open | (b) Lossy/warn | Error |

### Auto-detection

- **Extension**: `.cedar`.
- **Content sniff**: a Cedar document's first significant token is `permit`, `forbid`, or an
  `@annotation`, after optional `//` comments. None of those collide with YACAL, whose root
  keys are a closed capitalized set (`Policy`, `Bundle`, `Request`, `Response`, `ShortIdSet`),
  nor with ALFA, which opens with `namespace` or `import`.

### Example: an ACAL policy that cannot round-trip back to Cedar

```yaml
Policy:
  PolicyId: urn:example:rationale:cedar-gap
  Version: '1.0'
  CombiningAlgId: '{permit-unless-deny}'
  CombinerInput:
    - Rule:
        Id: permit-doctors
        Effect: Permit
        Condition:
          Apply:
            FunctionId: '{string-is-in}'
            Argument:
              - Value: doctor
              - AttributeDesignator:
                  Category: '{access-subject}'
                  AttributeId: urn:example:attribute:role
  NoticeExpression:
    - Id: urn:example:notice:audit-log
      IsObligation: true
      AppliesTo: Permit
      AttributeAssignmentExpression:
        - AttributeId: urn:example:attribute:decision-reason
          Expression:
            Value: permitted-by-role
```

Cedar cannot express this, for two independent reasons:

1. **`CombiningAlgId: permit-unless-deny`** — Cedar has one implicit strategy and no way to
   select another. There is no Cedar text that means "permit unless explicitly denied."
2. **`NoticeExpression` with `IsObligation: true`** — Cedar has no obligation model. The
   audit-log requirement would have to be re-implemented in the application layer, where it is
   no longer enforced by the policy.

**Verdict:** Cedar is input-only. The gaps are not oversights to be patched; they are the
deliberate cost Cedar pays for being analyzable. ACAL takes the opposite trade — richer
semantics, harder formal analysis — and that asymmetry is exactly why the conversion is
one-way.

---

## Future languages

Each section below follows this template:

```
### <Language name>

**What it can express** (mapped to ACAL concepts)
**What it cannot express** (ACAL features with no equivalent)
**Example: an ACAL policy that cannot round-trip back**
**Verdict**
```

Sections are added here as each reader is implemented in `acal-convert`.

---




---

### AWS IAM JSON

*Reader: not yet implemented.*

AWS IAM policies use a JSON format with `Effect`, `Action`, `Resource`, and
`Condition` keys. They are role-based at the top level and add attribute
conditions as an overlay.

**What IAM can express (maps to ACAL)**

| IAM concept | ACAL equivalent |
|---|---|
| `Effect: Allow` / `Effect: Deny` | `Rule` with `Effect: Permit` / `Effect: Deny` |
| `Action: ["s3:GetObject"]` | `AttributeDesignator` on action category |
| `Resource: ["arn:aws:s3:::bucket/*"]` | `AttributeDesignator` on resource category |
| `Condition` block (`StringEquals`, `IpAddress`, etc.) | `Apply` expression tree |
| `NotAction` / `NotResource` | Negation via `Apply` with `not` function |

**What IAM cannot express**

| Missing concept | ACAL feature |
|---|---|
| Combining algorithms | IAM uses implicit deny-by-default with explicit allow; no way to express `permit-unless-deny` or `first-applicable` |
| Obligations | No post-decision enforcement model |
| Policy-scoped variables | No let-binding |
| Quantified expressions | No ForAny/ForAll over attribute sets |
| Delegation depth | No `MaxDelegationDepth` equivalent |
| Arbitrary attribute categories | IAM is fixed to principal/action/resource/condition; ACAL supports arbitrary category URNs |

**Verdict:** Input-only. IAM's implicit deny model and fixed category structure
make it structurally incompatible with ACAL's general combining algorithm model.

---

### Rego / Open Policy Agent (OPA)

*Reader: not yet implemented. Parsing Rego requires a full Rego evaluator or
grammar implementation; this is a non-trivial dependency.*

Rego is a logic-programming language used by OPA. It is Turing-complete and
considerably more expressive than ACAL in some dimensions (general recursion,
arbitrary data joins, rule composition), but it lacks the *structured policy
document model* that ACAL provides.

**What Rego can express (maps to ACAL)**

| Rego concept | ACAL equivalent |
|---|---|
| `allow = true if ...` rules | `Rule` with `Effect: Permit` and `Condition` |
| Attribute access via `input.*` | `AttributeDesignator` |
| Set operations (`x in set`) | `Apply` with membership functions |
| Logical conjunction / disjunction | `Apply` with `and` / `or` functions |

**What Rego cannot express as structured ACAL**

| Missing concept | ACAL feature |
|---|---|
| Combining algorithms | Rego has no combining-algorithm concept; `allow` is a single boolean; multiple rules contributing to `allow` are implicitly ORed |
| Obligation expressions | Rego can produce arbitrary output, but there is no standardized enforcement hook equivalent to ACAL's `NoticeExpression IsObligation` |
| Structured policy identity | Rego modules have no equivalent to `PolicyId`, `Version`, or `CombiningAlgId`; policies are not self-describing documents |
| Delegation depth | No equivalent |

**Verdict:** Input-only, and conversion is inherently lossy in the other
direction because Rego policies are not structured documents — they are programs.
Converting an ACAL policy to Rego would produce code that *computes the same
result* for the expressed rules but would discard all structural metadata
(identity, version, combining algorithm) and would not be able to express
obligations in a portable way.

---

## Template for new languages

```markdown
### <Language name>

*Reader: [not yet implemented | implemented in version X.Y].*

<One-paragraph summary of the language, its primary use case, and its design goals.>

**What <Language> can express (maps to ACAL)**

| <Language> concept | ACAL equivalent |
|---|---|
| ... | ... |

**What <Language> cannot express**

| Missing concept | ACAL feature | Notes |
|---|---|---|
| ... | ... | ... |

**Example: an ACAL policy that cannot round-trip back to <Language>**

```yaml
# Minimal ACAL policy that uses a feature <Language> cannot represent
Policy:
  ...
```

Explanation of why each gap in the table above makes this policy
non-representable.

**Verdict:** Input-only / Bidirectional (with caveats: ...).
```
