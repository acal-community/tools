# ADR-0003: Fidelity over hardening

**Status:** Accepted · **Applies to:** every reader in `acal-core`

## Context

[ADR-0002](0002-no-silent-drops.md) covers constructs a reader cannot map. This ADR covers a
subtler case: constructs it *can* map, but where the faithful mapping preserves behaviour that is
permissive or surprising. The temptation is to "fix" the policy during conversion — to make it
safer than the original. That temptation must be resisted.

The motivating case is missing-attribute behaviour. Cedar's own evaluator, asked directly, does
this: a `forbid` whose attribute is absent **errors, is skipped, and the request is allowed**.
Cedar fails open. Its compensating control is a schema validator that catches the missing
attribute at authoring time — a control that does not exist on the ACAL side. It is tempting to
convert Cedar's designators with `MustBePresent: true` so a missing attribute *denies* instead.
That is safer than Cedar — and therefore **not Cedar**. It changes the decision on that path.

The same issue had already shipped, silently, in the ALFA reader: it omitted `MustBePresent`
entirely, so a converted deny rule's behaviour fell back to a schema default that reflected
nothing ALFA meant, and could fail open with no diagnostic at all.

## Decision

**A reader reproduces the source language's real runtime behaviour, and reports the consequence.
It does not silently change the decision.** The guiding line: *a converter that changes decisions
is not a converter.*

Applied to presence semantics, this became a project-wide rule: **every reader emits
`MustBePresent` explicitly on every attribute designator it synthesizes**, set to whatever
reproduces the source's real behaviour (Cedar → `false`; ALFA → `false`, faithful to its XACML
3.0 lineage; XACML → whatever the source stated). Never omit it (that defers to a schema default
that means nothing) and never silently harden it.

Where the faithful value means the policy can fail open, that is surfaced as a fidelity note the
user sees. Hardening is offered as an explicit, opt-in deviation — `--fail-closed` rewrites
synthesized designators to `MustBePresent: true` — never imposed by default.

## Consequences

- **Fidelity information is first-class output.** `load_with_report()` returns the neutral
  document *and* a structured report of what the conversion compromised on; `acal-explain`
  surfaces it as an "Import Fidelity" section, and `--strict` turns any such note into an error.
- **The user, not the tool, owns the safety/faithfulness trade.** The default is faithful; the
  hardened variant is one flag away and is itself reported as a deviation. A security team can
  read a conversion and see exactly which decisions were reproduced and which were changed.
- **One deliberate exception, and it is not a hole:** inside a `has`-style presence test,
  `MustBePresent` stays `false` even under `--fail-closed`, because "is this attribute present?"
  is precisely the question being asked; hardening it would make the guard itself Indeterminate.
- **This generalizes the earlier datatype decision.** A datatype mapping that is usable but not
  exact (Cedar `decimal` → ACAL `double`, fixed-point vs IEEE-754) is marked `approximate` and
  warns rather than being silently accepted — same principle, different construct. See
  [ADR-0005](0005-capability-matrix.md).

## See also

- `diary/architectural_decisions.md` → `presence-semantics-must-be-explicit`.
- [ADR-0004](0004-unambiguous-output.md) — the related rule that conversion metadata never enters
  the document it describes.
