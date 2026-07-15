# ACAL tools — design

This directory explains the **structural decisions** behind the ACAL toolchain: the choices
that define how conversion works, why it works that way, and what each choice commits us to.
It is written for someone evaluating or contributing to the project, not for the person who
made the decision.

Three kinds of design record live in this repo, and they are deliberately different:

| Record | Audience | Question it answers |
|---|---|---|
| **These ADRs** (`docs/design/`) | contributors, evaluators | *What structural decisions define this toolchain, and what do they commit us to?* |
| Inline comments | the next person editing that function | *Why is this line the way it is?* |
| The diary (`diary/`) | future working sessions | *What happened, when, and what did we learn?* |

The diary is a working log; these ADRs are the durable, public statement of the design. Where
a diary entry records a structural decision, it points here rather than restating it, so the
two cannot drift.

## The frame in one page

**ACAL is a hub, not a dialect of XACML.** The hub is the neutral ACAL model in its three
serializations — XACML 4.0 (XML), YACAL (YAML), JACAL (JSON). Every other policy language —
XACML 2.0 and 3.0, ALFA, Cedar, and whatever comes next — is a *spoke* that imports into the
hub. Conversion between hub serializations is lossless; conversion from a spoke is not, and
that asymmetry shapes everything else. **([ADR-0001](0001-acal-is-a-hub.md))**

Because ACAL is a superset of the languages it reads, importing from a spoke means the source
cannot say everything ACAL can, and exporting to one means ACAL can say things the target
cannot. The toolchain's core commitment is to **never lose or change policy meaning silently**,
because the artifact is access-control policy: a converted policy that quietly drops a
constraint or flips a decision can grant access the original denied. This produces four
structural rules:

- **No silent drops.** Every source construct is explicitly handled; anything unrecognized —
  including valid constructs not yet implemented — raises, never passes.
  **([ADR-0002](0002-no-silent-drops.md))**
- **Fidelity over hardening.** A reader reproduces the source language's *real runtime
  behaviour*, even where that behaviour is permissive, and reports the consequence. It does not
  silently "improve" a policy, because a converter that changes decisions is not a converter.
  **([ADR-0003](0003-fidelity-over-hardening.md))**
- **Output must be semantically unambiguous, not merely schema-valid.** A document that passes
  the schema but whose evaluation is ambiguous, or that our own validator rejects, is a bug.
  **([ADR-0004](0004-unambiguous-output.md))**
- **Every ACAL-facing document stays pure.** Conversion metadata travels beside the document,
  never inside it. **([ADR-0004](0004-unambiguous-output.md))**

The knowledge that drives all of this is not scattered through code — it is **data**:

- Each spoke has one **capability matrix** (`acal-core/capabilities/<dialect>.yaml`) that is the
  single machine-readable source of truth for what it can express, how its datatypes map, and
  which conversion decisions it raises. Readers, `acal-explain`, and the future export tool all
  read the same file. **([ADR-0005](0005-capability-matrix.md))**
- Conversion involves genuine judgment calls (reproduce a fail-open or harden it? accept a
  lossy datatype mapping or refuse it?). These are captured **as data, not as a growing wall of
  CLI flags**, so one definition drives a flag, an interactive prompt, and a web form alike.
  **([ADR-0006](0006-decisions-as-data.md))**

## Index

| ADR | Decision |
|---|---|
| [0001](0001-acal-is-a-hub.md) | ACAL is a hub, not a dialect of XACML |
| [0002](0002-no-silent-drops.md) | No silent drops |
| [0003](0003-fidelity-over-hardening.md) | Fidelity over hardening |
| [0004](0004-unambiguous-output.md) | Output must be semantically unambiguous, not merely schema-valid |
| [0005](0005-capability-matrix.md) | The capability matrix is the single source of truth |
| [0006](0006-decisions-as-data.md) | Conversion decisions are data, not flags |

## Related

- [`../../acal-core/docs/policy-language-expressiveness.md`](../../acal-core/docs/policy-language-expressiveness.md) — the per-language gap analyses these principles produce.
- [`../../acal-core/capabilities/README.md`](../../acal-core/capabilities/README.md) — the capability-matrix schema and the datatype ladder.
- [`../../ROADMAP.md`](../../ROADMAP.md) — where the toolchain is going.
