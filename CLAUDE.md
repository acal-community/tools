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
