# Session Context

## Current State (July 2026)

Work spans two repos:

- **`xacml-spec/`** (the OASIS spec repo) — spec issue #94 cleanup. Branch `issue-94-notice-id-nonunique` is ready but **unmerged**, pending TC sign-off.
- **`tools/`** — five packages. `acal-core` (99), `acal-converter` (21), `acal-explain` (34), `yacal-validator` (88), `jacal-validator` (90). **332 tests pass.**

**Branch state is the thing to know.** `main` is *behind*. The chain
`main → acal-converter → acal-core → acal-explain` is linear, each containing the last, and
`acal-explain` holds 7 commits that never landed on main — the ALFA reader, the acal-core
extraction, the import-model skill, and this session's work. `acal-converter` and `acal-core`
are stale checkpoints fully contained in `acal-explain`. The merged branches
(`jacal-validator`, `xacml-to-yacal`, `yacal-validator`) were deleted this session.
`origin/revert-7-acal-converter` is a stale remote branch that never merged.

## Most Recent Session (July 13, 2026)

### Direction: the next languages, and why not Rego

A `/grill-me` session set the next phase. The imports are **Cedar, then AWS IAM JSON**. Rego
is deferred, and the reason is worth keeping: the stated criterion was "start with what
imports cleanly," and this project's own expressiveness doc already calls Rego a
Turing-complete *program, not a document* whose parser is "a non-trivial dependency." Rego
lost to our own prior analysis rather than to a preference. A Rego reader would have to
define and police a recognized *subset* of the language — a different kind of problem from
every import so far, and one worth taking deliberately rather than by momentum.

The long-term goal list (ACAL export, Rego, the provenance spec extension) now lives in
`ROADMAP.md` and GitHub issues rather than in this file. The diary is a working log; a
roadmap outside contributors cannot read is not a roadmap.

### The delta list became executable

The plan had been to audit each language for what it can and cannot export, as prose. Prose
cannot gate a tool, and the export tool is the entire point of the audit — so the gap
analysis now lives in `acal-core/capabilities/<lang>.yaml`, keyed by ACAL feature, with three
consumers. Matrices for ALFA and XACML were written from the existing prose; Cedar's gets
authored by `/import-model` before its reader exists.
(→ capability-matrix-is-the-delta-list)

### acal-explain now reads every source language

A user feature request — "explain should not export a file, simply explain" — turned out to
mean: *don't make me materialize a converted `.yaml` just to explain a `.alfa`*. It is now
`acal-explain policy.alfa`, converting in memory and writing nothing but the explanation.
This reverses a deliberate June decision (→ acal-explain-reads-every-source-language), and
explain also gained import-fidelity reporting: what the source language could not express
faithfully in ACAL, surfaced in all three output formats and fed to the LLM so the
observations account for it.

The fidelity information travels *beside* the document, never inside it — stamping provenance
into the ACAL doc would make acal-convert emit output that fails our own validators.
(→ conversion-report-never-enters-the-document)

### Four defects surfaced along the way

- The `/import-model` skill pointed at pre-refactor paths and would have failed its own Phase 0 check on Cedar. Repointed at acal-core; taught about the registry and the capability matrix.
- `policy-language-expressiveness.md` existed twice **and had forked** — each copy held content the other lacked. It was nearly deleted as a duplicate. (→ check-for-fork-before-deleting-a-duplicate)
- A format was declared in five places, which is why the registry now exists. (→ central-language-registry)
- **A real bug:** the ALFA `xpath` datatype is documented as disposition (b) — warn by default, error under `--strict`. It never errored, because the warning fires in symbol collection and `_collect_symbols` never received the `strict` flag. `--strict` is what a user turns on when they need conversion to *fail* rather than approximate; it was silently not keeping that promise. (→ strict-must-be-threaded-through-every-pass)

### Spec issue #94 (earlier in July)

The notice-`Id` uniqueness constraint was reversed across all six artifacts where it had been
encoded. A notice `Id` names the obligation's *meaning*, not an occurrence.
(→ notice-id-is-a-concept-identifier). Branch is unmerged pending TC agreement — it is a
normative change. Probing a neighbouring constraint as a control turned up a long-standing
enforcement gap, filed as spec issue #99.
(→ xsd10-unique-silently-skips-absent-optional-fields)

## Open Items for Next Session

**Immediate — the merge backlog blocks everything:**

- **PR `acal-explain` → main.** Seven commits. Cedar cannot start cleanly until this lands. Then delete the stale `acal-converter` / `acal-core` local branches and `origin/revert-7-acal-converter`.
- Cut a `cedar` branch from the new main and run `/import-model CEDAR`.
- File the ROADMAP long-term items as GitHub issues (export tool, Rego, provenance extension).

**Spec:**

- **Issue #94 branch awaiting TC sign-off.** Do not merge without agreement — normative change.
- **Issue #99**: normative examples violate the `AttributeAssignmentExpression (AttributeId, Category)` uniqueness constraint and the XSD cannot catch it.
- **Tooling impact of #94**: if it lands, any validator enforcing notice-Id uniqueness must drop it. Check `yacal-validator` / `jacal-validator`.

**Known limitations, deferred:**

- **Nested attribute resolution**: `user.clearance`, `medicalrecord.patientId` etc. still produce unresolved-attribute warnings because nested namespace paths aren't walked. Surfaces in analyzer output as `unresolved_attrs`, and now also as import-fidelity notes.
- **Infix comparison type dispatch**: `>`, `<`, `>=`, `<=` default to `integer-*` regardless of attribute type; `==` defaults to `string-equal` for non-bag scalars. Should dispatch on the declared type.
- **Streaming output for acal-explain** (`--stream`).
- **acal-explain end-to-end smoke test** against a real LLM (CI-gated).
- Populate the root `README.md` (still empty). `acal-core/README.md` exists.
- File the upstream schema/catalog bugs (see prior sessions; still unfiled).
- Publish to PyPI when stable.

## Key Diary Files

- [architectural_decisions.md](architectural_decisions.md) — design principles and non-negotiable patterns
- [lessons_learned.md](lessons_learned.md) — anti-patterns and hard-won insights (most recent at top)
