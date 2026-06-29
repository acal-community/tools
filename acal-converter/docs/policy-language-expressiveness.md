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

### Why XACML is input-only

XACML output would require generating well-formed XML against the XACML 4.0
schema. In Python, that is straightforward for simple documents but becomes
entangled with OASIS licensing requirements for full schema-aware validation and
serialization. The toolchain recommended by the XACML TC for authoritative XML
generation (Saxon EE) is commercially licensed and not available as a Python
library.

This is a **toolchain constraint**, not a semantic one. XACML 4.0 and ACAL share the same data model. XACML 2.0 and 3.0 require additional
identifier remapping. Round-tripping is lossless in principle for supported constructs.
If a fully open Python XML serializer satisfying OASIS licensing becomes available,
XACML output can be added without changes to the neutral ACAL dict.

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

### Cedar (AWS)

*Reader: not yet implemented. This section documents the expressiveness analysis
that will inform the implementation.*

Cedar is Amazon's policy language for fine-grained authorization. It uses a
typed, attribute-based model and is designed to be analyzable (policies can be
formally verified). It is deliberately simple.

**What Cedar can express (maps to ACAL)**

| Cedar concept | ACAL equivalent |
|---|---|
| `permit` / `forbid` with `when` clause | `Rule` with `Effect: Permit` / `Effect: Deny` and `Condition` |
| Entity type hierarchy (`principal is User`) | `AttributeDesignator` with type-filtered category |
| Attribute access (`principal.role`) | `AttributeDesignator` |
| Set membership (`resource.tags.contains(...)`) | `Apply` with `string-is-in` or similar function |
| Namespace scoping | `PolicyId` URI prefix conventions |

**What Cedar cannot express**

| Missing concept | ACAL feature | Example |
|---|---|---|
| Combining algorithms | `CombiningAlgId` | Cedar uses an implicit `forbid`-overrides-`permit` ordering; ACAL allows `permit-unless-deny`, `first-applicable`, custom algorithms, etc. |
| Obligation / notice expressions | `NoticeExpression` | Cedar has no post-decision side-effect model; ACAL can mandate that a PEP perform an action (log, notify, redact) as a condition of enforcement |
| Policy-scoped variables | `VariableDefinition` | Cedar has no let-binding for reusing expressions inside a policy |
| Quantified expressions | `ForAny`, `ForAll`, `Map`, `Select` | Cedar's set operations are limited; ACAL can universally or existentially quantify over attribute collections |
| Shared variable definitions | `SharedVariableDefinition` in `Bundle` | Cedar has no cross-policy variable sharing |
| Nested policies with independent combining | `Policy` with nested `CombinerInput` | Cedar has flat policy sets; the combining semantics of nested policies cannot be expressed |

**Example: an ACAL policy that cannot round-trip back to Cedar**

```yaml
Policy:
  PolicyId: urn:example:rationale:cedar-gap
  Version: '1.0'
  CombiningAlgId: urn:oasis:names:tc:acal:1.0:combining-algorithm:permit-unless-deny
  CombinerInput:
    - Rule:
        Id: permit-doctors
        Effect: Permit
        Condition:
          Apply:
            FunctionId: urn:oasis:names:tc:acal:1.0:function:string-is-in
            Argument:
              - Value: doctor
              - AttributeDesignator:
                  Category: urn:oasis:names:tc:acal:1.0:subject-category:access-subject
                  AttributeId: urn:example:attribute:role
    - Rule:
        Id: deny-after-hours
        Effect: Deny
        Condition:
          Apply:
            FunctionId: urn:oasis:names:tc:acal:1.0:function:integer-greater-than
            Argument:
              - AttributeDesignator:
                  Category: urn:oasis:names:tc:acal:1.0:attribute-category:environment
                  AttributeId: urn:oasis:names:tc:acal:1.0:environment:current-time
              - Value: 17
  NoticeExpression:
    - Id: urn:example:notice:audit-log
      IsObligation: true
      AppliesTo: Permit
      AttributeAssignmentExpression:
        - AttributeId: urn:example:attribute:decision-reason
          Expression:
            Value: permitted-by-role
```

This policy cannot be expressed in Cedar because:

1. `CombiningAlgId: permit-unless-deny` — Cedar only supports its built-in
   `forbid`-overrides ordering. There is no way to express "permit unless
   explicitly denied" as a combining strategy.

2. `NoticeExpression` with `IsObligation: true` — Cedar has no obligation model.
   The audit-log requirement would have to be handled by the application layer,
   outside the policy, losing the enforceable guarantee.

**Verdict:** Cedar is input-only. The combining-algorithm and obligation gaps
are not edge cases — they are central to Cedar's design philosophy of keeping
the policy language simple and analyzable. ACAL accepts this tradeoff going the
other way: richer semantics at the cost of more complex formal analysis.

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
