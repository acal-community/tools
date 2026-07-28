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
<!-- memtoad:version:2 -->
- [`diary/session_context.md`](diary/session_context.md) — current state and recent work
- [`diary/architectural_decisions.md`](diary/architectural_decisions.md) — design principles and non-negotiable patterns
- [`diary/lessons_learned.md`](diary/lessons_learned.md) — anti-patterns and hard-won insights

**Before any git commit**, run `/committer` — it updates the diary and crafts the commit message in one step.

Commit workflow:
1. Tests pass
2. `/committer` — updates diary + commits

The skills behind this (`/committer`, `/session-historian`, `/startup`, `/grill-me`,
`/bootstrap`) come from the **memtoad** plugin — <https://github.com/humantypo/memtoad> — not
from files in this repo. `.claude/settings.json` enables it; install it with
`claude plugin install memtoad@memtoad`. Nothing under `.claude/skills/` or `.claude/commands/`
should ever be committed here, with the single exception of this project's own
[`import-model`](.claude/skills/import-model/) skill.

**Diary tracking is hybrid.** `architectural_decisions.md` and `lessons_learned.md` are tracked
and shared. `session_context.md` is **gitignored** — it is volatile working state, private to
each contributor's checkout, and not backed up by git. Don't `git add -f` it.

The diary is a working log, not a roadmap. Long-term goals — the ACAL export tool, future
language imports, spec extensions — belong in [`ROADMAP.md`](ROADMAP.md) and GitHub issues,
where outside contributors can see them.

## This repo is independent of the upstream specification effort

This repo lives beside a checkout of the upstream OASIS specification repository, and reading
across the two is encouraged — it is how compatibility drift gets caught early, and why CI
validates against the upstream `main`.

**Reading across is encouraged. Writing across is forbidden.** Nothing originating in the
specification effort belongs in this repo's diary, docs, or commit messages: no upstream issue
or PR numbers, no committee member names, no committee deliberations or positions, no quotations
from unpublished drafts, no line-number citations into spec documents. Describe upstream changes
by what they *did* ("an upstream change flattened `RequestEntityReference`"), not by their issue
number. Spec observations worth raising go **on the upstream issue tracker**, not into this
diary.

This is a correctness rule, not a style preference — this project's contributors are not all
participants in that effort, and material that is routine on one side is not ours to republish.

`/committer` and `/session-historian` write to **this repo's** `diary/` only. If a session
touched both repos, write two entries — one in each — each describing only its own repo's work.
Never one entry covering both.

**Note on diary history**: entries committed before 2026-07-28 contain material from that
upstream effort. The working files have been cleaned; the git history has not. Do not add to it,
and do not treat those old entries as a precedent.

## Adding a policy language

Use `/import-model <LANGUAGE>`. Readers live in `acal-core`, and every language is
registered exactly once in `acal-core/src/acal_core/languages.py` — both CLIs derive their
`--from` choices from it. If you are hand-editing a `click.Choice`, you have missed the
registry.
