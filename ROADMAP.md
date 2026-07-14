# Roadmap

Where the ACAL tools are going, and why. Near-term work is tracked as GitHub issues; this
file is the 30-second overview and the reasoning that issues are too small to hold.

## Shipped

| Tool | Status |
|---|---|
| `yacal-validator` | YACAL v1.0 (YAML) validator. Gold-standard: no known coverage gaps. |
| `jacal-validator` | JACAL v1.0 (JSON) validator. |
| `acal-core` | Shared library: readers (XACML, YACAL, JACAL, ALFA), writers (YACAL, JACAL), language registry, capability matrices. |
| `acal-convert` | CLI over `acal-core`. Converts any readable source language to YACAL or JACAL. |
| `acal-explain` | Plain-English explanation of any readable source language, with import-fidelity reporting. |

## Next: more imports

The strategy is **import first, export later**. Import is well-understood and each new
language is largely independent work. Export is a single hard problem that gets easier the
more languages we have audited, because each import forces us to write down that language's
capability matrix — and the matrices *are* the export tool's specification.

Order is chosen by how cleanly a language imports, not by popularity:

1. **Cedar (AWS)** — next up. Structured, typed, deliberately simple. Gap analysis already
   drafted in [`acal-core/docs/policy-language-expressiveness.md`](acal-core/docs/policy-language-expressiveness.md).
2. **AWS IAM JSON** — plain JSON, zero parser risk, enormous install base. Gap analysis drafted.
3. **Rego / OPA** — deferred, deliberately. See below.

Each lands via `/import-model <LANGUAGE>` on its own branch.

## Next: an XACML 4.0 writer

**Not** the export tool. XACML 4.0 is the XML *serialization of ACAL 1.0* — one of the three
native encodings alongside YACAL and JACAL — so writing it sits beside the YACAL and JACAL
writers, not in `acal-export`.

It was long believed blocked on Saxon EE licensing. That is a conflation: Saxon EE is needed
to **validate** XML against XSD 1.1, not to **write** it. Emitting XACML 4.0 XML is
`ElementTree`, exactly as reading it is.

It pays for itself twice:

- **Round-trip tests.** `XACML 4.0 → YACAL → XACML 4.0` is the strongest correctness check
  this codebase could have, and it is currently impossible to write.
- **It closes [#1](https://github.com/acal-community/tools/issues/1)** ("Automatic conversion
  from XACML 3.0 to XACML 4.0"), which is simply `load(xacml-3.0) → neutral dict →
  write(xacml-4.0)`: import a spoke, serialize the hub. #1 is not blocked on export at all.

## Long-term

### ACAL export (`acal-export`)

**Tracking: [#10](https://github.com/acal-community/tools/issues/10)**

Every **foreign** language is input-only: ACAL is a superset of the languages we read, so
emitting a policy *into* one of them means deciding what to discard — and discarding
access-control semantics silently is dangerous.

This is about *foreign* targets only. Writing XACML 4.0 is serialization, not export (see
above), and does not belong here.

Export becomes tractable once each language has a capability matrix in
[`acal-core/capabilities/`](acal-core/capabilities/) declaring which ACAL features it can and
cannot express. The export tool's core loop is then: check the document against the target's
matrix, refuse (or explicitly downgrade, under a flag) anything the target cannot hold, and
emit the rest.

`acal-explain` already previews this — it reports which ACAL features in a document the
source language could not express. That reporting path is the same one export will gate on.

This is complex and nuanced work. It is not started, and it should not start until at least
Cedar and IAM have matrices, so the design is drawn from three examples rather than one.

### Rego / OPA import

**Tracking: [#11](https://github.com/acal-community/tools/issues/11)**

Rego is the most-requested language and the least suited to a structural import. It is
Turing-complete, and a Rego module is a **program, not a document**: `allow` is *computed*,
not declared. There is no `PolicyId`, no `Version`, no combining algorithm to recover.

A Rego reader would therefore have to define and enforce a recognized **subset** of the
language, and reject anything outside it. That subset boundary is the entire design problem,
and it is a different kind of problem from every import done so far. It is parked here rather
than dropped: the demand is real.

### Provenance as a spec extension

**Tracking: [#12](https://github.com/acal-community/tools/issues/12)**

`load_with_report()` deliberately returns fidelity information *beside* the document rather
than inside it, because the ACAL schemas set `additionalProperties` / `unevaluatedProperties`
to false in places — a provenance key would make `acal-convert` emit documents that fail our
own validators.

The consequence is that fidelity does not survive a convert-then-explain pipeline across
process boundaries. Fixing that properly means proposing a provenance extension point to the
ACAL spec, not working around the schema.
