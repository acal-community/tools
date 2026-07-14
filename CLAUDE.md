## First principle: ACAL is a hub, everything else is a spoke

Read this before designing anything. It is the frame the whole toolchain is built on, and
getting it wrong has already produced real bugs.

**The hub is ACAL itself** — the neutral model, in all of its serializations, present and
future:

| Hub (native) | |
|---|---|
| **XACML 4.0** | the XML serialization of ACAL 1.0 |
| **YACAL 1.0** | the YAML serialization |
| **JACAL 1.0** | the JSON serialization |
| *future ACAL versions and serializations* | also hub, by definition |

**Everything else is a spoke.** XACML 2.0, XACML 3.0, ALFA, Cedar, AWS IAM, Rego — all of
them, permanently. A spoke is a foreign language that imports *into* the hub. Age and
lineage are irrelevant: **XACML 1–3 are spokes**, not "older versions of the hub." ACAL is a
new, independent endpoint that happens to have an XML serialization; it is not a dialect of
XACML.

What follows from this, and is not optional:

- **Native dialects have no capability matrix.** They express the whole model by
  construction — there is nothing they cannot say. Only spokes declare gaps, in
  [`acal-core/capabilities/`](acal-core/capabilities/).
- **Capability is a property of the dialect, not the file extension.** An `.xml` file may be
  a foreign XACML 3.0 policy or the native ACAL XML serialization. See `DIALECTS` in
  `acal-core/src/acal_core/languages.py`.
- **Writing a hub serialization is *serialization*, not export.** An XACML 4.0 writer belongs
  beside the YACAL and JACAL writers. `acal-export` exists for the genuinely hard problem of
  emitting into *less expressive* spoke languages.
- **Conversion between hub serializations is lossless. Conversion from a spoke is not**, and
  the loss must be reported, never swallowed.

Violating this frame is not a style error. A single `xacml` capability matrix spanning
2.0–4.0 asserted that XACML "cannot express SharedVariableDefinition" — true of the 3.0 spoke,
false of the 4.0 hub — and would have silently mis-gated the export tool.

(→ `acal-is-a-hub-not-a-xacml-dialect` in [`diary/architectural_decisions.md`](diary/architectural_decisions.md))

## Project Memory

Cross-project decisions, lessons, and current work live in [`diary/`](diary/):
- [`diary/session_context.md`](diary/session_context.md) — current state and recent work
- [`diary/architectural_decisions.md`](diary/architectural_decisions.md) — design principles and non-negotiable patterns
- [`diary/lessons_learned.md`](diary/lessons_learned.md) — anti-patterns and hard-won insights

## Commit Discipline

**Before making any git commit**, always run `/session-historian` first. This updates the diary with what was accomplished, any architectural decisions made, and any lessons learned. The diary is committed to git and is the primary context source for future sessions and for `/grill-me`. Skipping this step means the next session starts blind.

The correct order is always:
1. Tests pass
2. `/session-historian` — update diary
3. `git commit`

The diary is a working log, not a roadmap. Long-term goals — the ACAL export tool, future
language imports, spec extensions — belong in [`ROADMAP.md`](ROADMAP.md) and GitHub issues,
where outside contributors can see them.

## Adding a policy language

Use `/import-model <LANGUAGE>`. Readers live in `acal-core`, and every language is
registered exactly once in `acal-core/src/acal_core/languages.py` — both CLIs derive their
`--from` choices from it. If you are hand-editing a `click.Choice`, you have missed the
registry.
