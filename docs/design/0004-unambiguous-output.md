# ADR-0004: Output must be semantically unambiguous, not merely schema-valid

**Status:** Accepted · **Applies to:** every reader in `acal-core`

## Context

Passing the ACAL schema is necessary but not sufficient. A document can be structurally valid and
still be *wrong*: ambiguous about which policy actually decides, carrying a value the schema
tolerates but a validator rejects, or polluted with metadata that makes it fail elsewhere. The
schema checks shape; it does not check that the emitted policy evaluates to what the source meant.

Three concrete failures drove this out, all of which produced schema-valid-but-wrong output:

1. **Nulls.** An XACML policy with no `Version` attribute (optional in XACML) converted to
   `Version: null`. YACAL prohibits nulls, so `acal-convert` was emitting documents that our own
   `yacal-validate` rejected — the flagship `--validate` pipeline was broken for an ordinary input.
2. **Ambiguous decision root.** Converting a Cedar policy set to an ACAL `Bundle`, the reader
   emitted several policies in `Bundle.Policy[]` with **no** `Bundle.PolicyReference`. The schema
   permits that (the reference is optional), but semantically `Bundle.Policy[]` is a *definition
   pool* and `Bundle.PolicyReference` names the *entry point that decides*. With no entry point,
   which policy is the decision was undefined.
3. **Provenance in the document.** The obvious way to make conversion fidelity survive a pipeline
   is to stamp the source language and a report into the ACAL document. But the ACAL schemas set
   `additionalProperties` / `unevaluatedProperties` to false in places, so an extra key makes the
   converter emit documents that fail our own validators.

## Decision

**The reader is responsible for the evaluation semantics of what it emits, not just its shape.**
In practice:

- **Never emit a null.** An absent optional field is either omitted or filled with the source
  language's real default (an absent XACML `Version` becomes `"1.0"`, its schema default — the
  faithful value, since ACAL requires `Version`). A cross-reader invariant test sweeps every
  fixture and fails on any null.
- **Emit a decision root explicitly.** When output is a multi-policy `Bundle`, the active policy
  is named by `Bundle.PolicyReference`; the pool is everything else. When a single policy suffices,
  emit a bare top-level `Policy` and no Bundle at all — no pool, no ambiguity.
- **Conversion metadata travels beside the document, never inside it** — in the `ConversionReport`
  from `load_with_report()`, so the ACAL document stays pure and passes our own validators.
- **Test against our own validator.** A converter that has a validator in the same repo is tested
  by piping its output through that validator on ordinary inputs, not merely by asserting on the
  intermediate dict.

## Worked example: Cedar templates and the Bundle entry point

A Cedar *template link* — the binding that fills a `?principal` slot — is a runtime instantiation
supplied through Cedar's policy-set/entities API. It is **never present in policy text**:
`policies_to_json_str` on a `.cedar` file always returns `templateLinks: []`. So a template in a
file is uninstantiated — dormant, deciding nothing until linked elsewhere.

Getting this right required distinguishing schema-validity from semantic-validity:

- An uninstantiated template converts to a parameterized `Policy` placed **inert in the Bundle's
  definition pool**, reachable only by reference (which text links never provide), and carries a
  fidelity note that it is uninstantiated (error under `--strict`).
- The output shape is chosen so the active policy is never ambiguous: static policies only → a
  bare `Policy`; templates + active policy → a `Bundle` whose `PolicyReference` names the active
  policy as the entry point; templates only → an inert `Bundle` with no entry point and a warning
  that the document expresses no active policy.

An earlier version emitted the template among the Bundle's policies with no entry point. It passed
`yacal-validate`. It was still wrong, because validation exercises structure, not evaluation — the
exact gap this ADR exists to close.

## Consequences

- **Structural validity is a floor, not the bar.** Green from the validator does not end a
  reader's responsibility; the reader must be able to state what the document *decides*.
- **Fidelity's reach is bounded, honestly.** Because provenance stays out of the document,
  conversion fidelity is available only while the importing process holds it; it does not survive
  a convert-then-explain across process boundaries. Carrying it properly needs a provenance
  extension point in the ACAL spec, which is on the roadmap rather than hacked past the schema.

## See also

- [ADR-0003](0003-fidelity-over-hardening.md) — why the report exists and stays external.
- `diary/architectural_decisions.md` → `conversion-report-never-enters-the-document`.
- `diary/lessons_learned.md` → `converter-output-must-be-fed-to-our-own-validator`,
  `verify-the-input-can-reach-the-code-path`.
- `acal-core/docs/policy-language-expressiveness.md` → the Cedar "Templates, and the shape of the
  output" section.
