# ADR-0006: Conversion decisions are data, not flags

**Status:** Accepted · **Applies to:** `acal-core/capabilities/`, the CLIs, and the planned `acal-decisions` / `acal-web`

## Context

Converting from a spoke involves genuine judgment calls with no universally correct answer —
they depend on the deployment. Two real examples from Cedar:

- **Missing-attribute presence.** Cedar fails open on a missing attribute (see
  [ADR-0003](0003-fidelity-over-hardening.md)). Reproduce that faithfully, or harden it so a
  `forbid` with a missing attribute denies?
- **Approximate datatypes.** Cedar `decimal` is fixed-point; ACAL `double` is IEEE-754 binary
  float. A comparison at a precision boundary can decide differently. Convert with a warning, or
  refuse?

Cedar alone produced several such decisions; ALFA and XACML have their own, and each new language
adds more. Expressed as CLI flags this becomes
`--strict --fail-closed --allow-approximate …` — a matrix no one can hold in their head, with
undefined interactions between flags, and, worst of all for access control, **no record of what
was chosen and why**.

## Decision

Each judgment call a *user* may legitimately make is enumerated **as data**, in the `decisions:`
block of the dialect's capability matrix: the question, the options, the consequence of each, a
default, the flag that sets it, and a `triggers` condition. One definition drives three
front-ends — `--profile` (replay saved answers), `--interactive` (prompt for the unanswered), and
a web form — with no second implementation.

The `triggers` field is what makes this better than flags rather than merely different: **a
decision is raised only if the document being converted actually reaches it.** A Cedar policy with
no decimals and no attribute access asks the user nothing.

The durable artifact is the **decision profile**: an organization answers once, replays across
every conversion, and can later answer *"why was this policy converted this way?"* For access
control, that provenance is worth more than the convenience.

## What is *not* a decision

Correctness requirements are not offered as choices. The Cedar combining encoding (an outer
`deny-unless-permit` wrapping an inner `deny-overrides`) is not selectable, because the
alternatives are simply wrong — offering "flat `deny-unless-permit`" would be offering the user a
way to silently disable every `forbid` in their policy.

The test is sharp: **a decision point is where a reasonable person could differ, not where one
answer is a bug.** A tool that lets you choose a broken semantics is not flexible; it is
dangerous.

## Consequences

- **The CLI stays small as coverage grows.** New judgment calls are new matrix entries, not new
  flags; the interaction surface does not explode.
- **One knowledge source, three interfaces.** Because the decision, its consequences, and its flag
  live together in the matrix, the CLI flag, the interactive prompt, and the web form cannot
  present different information — the drift that a wall of independently-documented flags invites.
- **Batch falls out of the interactive design.** The planned `acal-web` is a thin, stateless skin
  over an `acal-decisions` library; the endpoint the web form posts to is the batch API, so batch
  conversion is not a second implementation. (Tracked as issue #13.)
- **Provenance is designed in, not bolted on.** A conversion carries its resolved profile, so an
  auditor can reconstruct every decision that shaped the result.

## See also

- `diary/architectural_decisions.md` → `conversion-decisions-are-data-not-flags`, `acal-web-is-stateless`.
- [ADR-0003](0003-fidelity-over-hardening.md) — the presence decision that motivated this.
- [ADR-0005](0005-capability-matrix.md) — the file these decisions live in.
- [`../../ROADMAP.md`](../../ROADMAP.md) — the `acal-decisions` + `acal-web` milestone.
