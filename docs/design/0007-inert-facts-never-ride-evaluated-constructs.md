# ADR-0007: Inert facts never ride evaluated constructs

**Status:** Accepted · **Applies to:** `acal-core/metadata.py`, `acal-convert --provenance`,
and the schema proposal in [`docs/proposals/metadata/`](../proposals/metadata/)

## Context

[ADR-0004](0004-unambiguous-output.md) committed the toolchain to keeping the conversion
report *outside* the document, and named the cost honestly: fidelity information lives only
as long as the importing process, so it does not survive a convert-then-explain across a
process boundary. Carrying it properly needed an extension point ACAL 1.0 did not have.

The obvious way to get one without waiting is to reuse a property that already exists and
is loosely enough specified to hold anything. ACAL offers two candidates, and both are
traps.

**`PolicyIssuer`** is structurally perfect: an `EntityType`, so it already holds arbitrary
named attributes and content in every serialization. It is also disqualified by its own
normative text — a PDP that does not implement the Administration and Delegation profile
MUST report an error or return `Indeterminate` on encountering it (§7.4). That obligation
attaches to the property being *populated*, not to what is inside it. Annotating a document
this way stops it evaluating anywhere the profile is absent.

**`SharedVariableDefinition`** is the same trap one level down, and it was proposed in
earnest for a real problem: an ALFA attribute declaration binds a `category` and a `type`
that `ShortIdType` (`Name` → `Value`) cannot hold, and modelling each declaration as a
shared variable wrapping an `AttributeDesignator` needs no schema change at all. But a
`SharedVariableDefinition` is normative and evaluable. The document gains N variables its
author never wrote, every attribute reference becomes a `VariableReference`, and no later
reader can tell a converter-synthesised variable from an intended one.

## Decision

**A fact the PDP must ignore is never stored in a construct the PDP evaluates**, however
convenient the shape.

Annotation goes in a property whose defining rule is that it is ignored:

> A `Metadata` property is non-normative. Its content MUST NOT affect policy evaluation,
> and a PDP encountering a `Metadata` property MUST evaluate the enclosing object exactly
> as if the property were absent.

That MUST-ignore rule is the entire substance. ACAL 1.0 has nothing like it anywhere:
`Description` is silent on evaluation, and `PolicyIssuer` carries the opposite rule. The
container itself is deliberately unremarkable — `MetadataType` is shaped as `EntityType`,
so no serialization gains new grammar.

Two rules follow from the same principle:

- **The proposal stays as small as the principle allows.** `Metadata` attaches to
  `BundleType` and `PolicyType` and nothing else. Extending `ShortIdType` to hold ALFA's
  `category` and `type` was dropped; the declarations ride as the source language's symbol
  table inside the document-level `Metadata` instead. Adding a property to a type the PDP
  resolves, in order to store facts it must not resolve, is the same mistake in miniature.
- **Unadopted means unadopted.** Stamping is opt-in (`acal-convert --provenance`), and the
  validators admit `Metadata` only under an explicit `--proposal metadata`, naming the
  proposal on their outcome line. A tool that quietly validated against a change the TC has
  not made would be lying about what ACAL says — which is a variant of the same failure:
  letting convenience overwrite a normative fact.

## Consequences

- **ADR-0004's bound is lifted, on the record rather than around it.** Fidelity can now
  survive a process boundary, because there is a sanctioned place to put it — not because
  the schema was worked around.
- **A structural defect in `Metadata` is an error; unreadable content in it is not.**
  `acal_core.metadata` raises `MetadataError` on a non-object `Metadata`, an empty one, or
  a duplicate `(AttributeId, Issuer)` — the shape is the thing being proposed, and emitting
  it wrongly is a bug worth surfacing. A payload that will not parse degrades to absent: it
  is opaque by design and the enclosing policy is unaffected either way.
- **The proposal and the demonstration cannot drift.** The schema fragments the TC reviews
  are the same files `--proposal` applies. A validator that hardcoded the proposed shape in
  Python would diverge from the written proposal silently, with the demonstration still
  passing.
- **Round-tripping is preservation, not restoration.** The ALFA symbol table records what a
  writer back to ALFA would need. There is no ALFA writer, and this does not create one.

## See also

- [ADR-0004](0004-unambiguous-output.md) — the bound this lifts.
- [`../proposals/metadata/`](../proposals/metadata/) — the proposal and its schema fragments.
- [acal-community/tools#12](https://github.com/acal-community/tools/issues/12) — the discussion.
