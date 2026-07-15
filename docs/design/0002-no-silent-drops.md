# ADR-0002: No silent drops

**Status:** Accepted · **Applies to:** every reader in `acal-core`

## Context

The output of a converter is access-control policy. A converted policy that silently omits a
constraint — a combining-algorithm parameter, a version restriction, an obligation, an
expression argument — is a *different policy* from the one the author wrote. It may grant access
the original denied, and the user has no way to detect this if the converter produces
structurally valid output without signalling the loss.

Readers are naturally prone to this. A reader assembled from targeted `find()` / lookup calls
silently ignores every element it does not explicitly ask for. This is not hypothetical: the
XACML reader's `_rule()` never read `<Target>`, so a rule scoped to doctors converted into a rule
that permitted **everyone**, in every XACML version, and it shipped. The same shape dropped
`Obligations` from a `<Result>` — an enforcement requirement the PEP would never see.

## Decision

**Every source construct is explicitly handled, and anything unrecognized raises.** Not just
constructs known to be unsupported — *anything* the reader does not have a mapping for, including
valid constructs whose conversion is simply not implemented yet.

Concretely, a reader built from element lookups carries an explicit **known-children allowlist**
and raises on anything outside it. The allowlist is the mechanism that turns "we forgot to handle
X" from a wrong answer into an error message.

Raising on the *unimplemented*, not merely the *invalid*, is the deliberate part. A user who
hits the error files a bug; a user who does *not* hit it gets a policy that means what they wrote.
The error message distinguishes the two cases (a removed construct directs the user to redesign;
an unimplemented one invites a bug report) but both outcomes are an unconditional failure.

## Consequences

- **One narrow, principled exception:** a construct with genuinely no effect on policy
  *evaluation* (a response-formatting hint like XACML's `IncludeInResult`) may warn instead of
  raise. The `--strict` flag promotes every such warning to an error. This is the only category
  allowed to proceed with a warning, and the test is evaluation-effect, not convenience.
- **Convertibility is bounded and honest.** The set of inputs a reader accepts is exactly the set
  it has a mapping for; everything else is a clear error naming the gap. There is no "best-effort"
  middle ground, because best-effort conversion of access-control policy is how a hole ships.
- **Coverage gaps become visible.** A construct with no fixture is a code path that has never run;
  because unrecognized constructs raise, the first real input exercising it fails loudly rather
  than silently mis-converting. (An *empty* fixture directory is the trap this does not catch —
  see the diary lesson `empty-fixture-directory-is-a-coverage-lie`.)
- **Datatype gaps get the same treatment**, via a ladder that resolves a type or hard-errors
  naming the one line that would map it — see [ADR-0005](0005-capability-matrix.md).

## See also

- [ADR-0003](0003-fidelity-over-hardening.md) — the companion rule for constructs we *do* map but
  cannot map faithfully.
- `diary/architectural_decisions.md` → `unconverted-constructs-raise-they-do-not-vanish`.
- `diary/lessons_learned.md` → `find-based-readers-drop-what-they-do-not-ask-for`.
