---
name: import-model
description: Add a new source policy language to acal-core. Runs a structured gap analysis, documents decisions before writing code, implements the reader, adds tests and CLI integration, then closes with session-historian and a code review. Invoke as `/import-model <LANGUAGE>`.
---

Implement a new source-language reader in `acal-core`. Every tool in this repo
(`acal-convert`, `acal-explain`) consumes readers from `acal-core`, so a language added
here becomes available to all of them at once. Run **inline in the main conversation**
(do not spawn an agent unless a step specifically says to).

## Phase 0: Validate input

If the language name was not given as an argument, use **AskUserQuestion** to ask for it before proceeding.

Perform a **comprehensive existence check** across all integration points:

1. `acal-core/src/acal_core/readers/<lang>.py` — reader file
2. An entry in `LANGUAGES` in `acal-core/src/acal_core/languages.py` — the central registry
3. A dispatch branch in `load()` in `acal-core/src/acal_core/readers/__init__.py`
4. `acal-core/capabilities/<lang>.yaml` — the machine-readable capability matrix
5. A language section in `acal-core/docs/policy-language-expressiveness.md`

Report which of these exist and which do not. If **any** are present, surface this as an issue and **stop processing** until the user clarifies intent. Do not assume a partial implementation should be continued or overwritten.

Note what is **not** on this list: the CLIs. `acal-convert` and `acal-explain` build their
`--from` choices from `LANGUAGES` at import time, so they need no edit. Do not add a format
name to a `click.Choice` by hand — that is the drift bug the registry exists to prevent, and
a parity test in each tool's suite will fail if you do.

## Phase 1: Load context

Before any analysis, read in order:

1. `diary/architectural_decisions.md`
2. `diary/lessons_learned.md`
3. `diary/session_context.md`
4. `acal-core/docs/policy-language-expressiveness.md` — the no-silent-drops requirement and existing gap taxonomy
5. `acal-core/src/acal_core/languages.py` — the central language registry
6. `acal-core/src/acal_core/readers/__init__.py` — detection and dispatch
7. `acal-core/src/acal_core/readers/xacml.py` — the reference reader pattern for a structured format
8. `acal-core/src/acal_core/readers/alfa.py` — the reference reader pattern for a DSL (two-pass, symbol table)

Output 2–3 sentences naming any architectural constraints from the diary or the expressiveness doc that are directly relevant to this language. If nothing applies, proceed silently.

## Phase 2: Gap analysis

Interview the user to build a complete picture of the language before writing any code. Use **AskUserQuestion** for every question — never pose questions as plain text. Ask one question at a time and wait for each answer.

The goal is to resolve every branch of the design tree before Phase 3. These are guiding areas, not a fixed script — follow branches as they open.

**Language nature — resolve this fully before moving to semantic coverage**

The answer to this question determines the entire implementation shape. Do not proceed to semantic coverage until the parser strategy is agreed.

- Is this a structured data format (XML, JSON, YAML, TOML…) or a DSL / programming language with its own syntax?
- If it is a **structured format**: which standard or widely-used Python library handles parsing? Is there anything unusual about the format that a standard library won't handle?
- If it is a **DSL**: does an official grammar exist (ANTLR, EBNF, PEG, etc.)? Is there an existing Python library or runtime that can parse it, and what is the dependency cost and maintenance risk? Explore the concrete options before recommending one — e.g., use the official grammar if one exists, a general-purpose parsing library if not, or a hand-rolled parser only for very simple grammars.
- If it is a **DSL**: does the language allow forward references within a scope (e.g., a rule that references a declaration that appears later in the file)? If yes, a two-pass architecture is needed: a pre-pass to collect all declarations into a symbol table, then a main transformer pass to resolve references against it. Settle this before semantic coverage, because it affects how every mapping decision is implemented.

**Semantic coverage**

Walk through ACAL's key constructs one family at a time. For each, ask whether the source language has an equivalent — and if so, whether the mapping is 1:1 or approximate:

- Policy identity and versioning (`PolicyId`, `Version`)
- Combining algorithms (`CombiningAlgId`)
- Rules and effects (`Rule`, `Effect: Permit/Deny`)
- Condition and expression tree (`Condition`, `Apply`, functions)
- Attribute access (`AttributeDesignator`, `AttributeSelector`)
- Obligation and advice model (`NoticeExpression`, `IsObligation`)
- Policy-scoped and shared variables (`VariableDefinition`, `SharedVariableDefinition`)
- Request and response structures (`RequestEntity`, `ResultEntity`)

For source-language constructs that have **no ACAL equivalent**, surface these explicitly — they require ACAL model extension (disposition e) and are a significant design decision that must be flagged before implementation begins.

**Gap dispositions**

For each identified gap, agree on one disposition:

- **(a) Direct mapping** — 1:1 structural translation
- **(b) Lossy import with warning** — `UserWarning` emitted; conversion proceeds
- **(c) Hard error** — `raise <Lang>UnsupportedFeatureError` unconditionally
- **(d) Supplementary transformation** — additional logic that produces an ACAL equivalent not directly present in the source
- **(e) ACAL model extension required** — stop and flag; do not proceed until this is resolved

For (b) vs. (c): follow the existing project rule — constructs with no effect on policy *evaluation* (response formatting, metadata hints) get warnings; constructs that change evaluation semantics get errors. The `--strict` flag promotes (b) to (c).

**Auto-detection**

- What file extension(s) does this language use?
- What is the leading byte or token signature of a valid document? Is there a content-sniff rule that won't collide with YACAL (which also starts with plain text)?
- If there is no reliable content-sniff, extension-only detection is acceptable — document this limitation.

When all branches are resolved, output the decision summary as a structured table before proceeding to Phase 3. Use exactly four columns — **Source construct | ACAL mapping | Disposition (a–e) | Strict behavior** — because this table feeds directly into Phase 3 and should match the gap table format in the expressiveness doc template.

## Phase 3: Document decisions before writing code

Two artifacts, both written **before** any reader code. They carry the same knowledge in
two forms: one for humans, one for tools.

**1. The capability matrix** — `acal-core/capabilities/<lang>.yaml`. This is the
machine-readable delta list, and it is the artifact the eventual ACAL *export* tool will be
built on. Three consumers read it, so it must be data, not prose:

  - the reader, for its warn-vs-error dispositions
  - `acal-explain`, to report which ACAL features in a document this language could never
    express
  - the future export tool, as its precondition gate

Key it by **ACAL feature**, not by source construct — the question it answers is "what can
this language say about ACAL?", which is the export direction. Record for each: whether it
is exportable (`true` / `false` / `partial`), the disposition code, and a one-line note
explaining the limit. Derive the entries from the Phase 2 gap analysis.

**2. The prose section** — in `acal-core/docs/policy-language-expressiveness.md`, following
the template at the bottom of that file. It must cover:

- Whether the language is input-only or potentially bidirectional, and why
- The no-silent-drops requirement as it applies to this language
- Each gap from Phase 2 with its chosen disposition and the reasoning
- A concrete ACAL policy example that cannot round-trip back to the source language (required for input-only verdicts)
- Which gaps are subject to `--strict` / `--no-strict` and what each mode does

Prose and matrix must agree. If they disagree, the matrix wins — it is the one that
executes.

**Do not proceed to Phase 4 until the user confirms both reflect the decisions from Phase 2.**

## Phase 4: Implement

Work in this order, completing each step before starting the next:

**1. Parser / loader** — if the language is a DSL, install and wire up the chosen parsing approach. Update `acal-core/pyproject.toml` with any new dependencies. Parse errors (syntax errors in the source file) must surface as `<Lang>SyntaxError(ValueError)` — a distinct type from semantic conversion errors. If the Phase 2 analysis determined a two-pass architecture is needed, implement `_collect_symbols(tree) -> _SymbolTable` as a standalone function that runs over the raw parse tree before the main transformer; the main transformer receives the populated symbol table at construction time. `readers/alfa.py` is the worked example.

**2. Reader** — create `acal-core/src/acal_core/readers/<lang>.py`:
   - Define `<Lang>SyntaxError(ValueError)` for parse failures (raised in pass 1 / symbol collection)
   - Define `<Lang>UnsupportedFeatureError(ValueError)` for constructs with disposition (c) (raised in pass 2 / transformation)
   - Both inherit `ValueError` to match the `XACMLUnsupportedFeatureError` precedent
   - Implement `load(path: str, strict: bool = False) -> dict` returning the neutral ACAL dict
   - Every source-language construct must be **explicitly handled** — no silent skips; unrecognised constructs should raise, not pass
   - Warning-eligible constructs (disposition b) emit `UserWarning` in non-strict mode and raise `<Lang>UnsupportedFeatureError` in strict mode. `load_with_report` turns those warnings into structured `ConversionNote`s, which is how `acal-explain` reports import fidelity — so the warning message *is* user-facing copy. Write it accordingly: name the construct and say what the consequence is.
   - Never write provenance or conversion metadata **into** the returned dict. The ACAL schemas set `additionalProperties` / `unevaluatedProperties` to false in places, so an extra key makes our own output fail our own validators. Fidelity travels in the `ConversionReport`, never in the document.

**3. Registry** — `acal-core/src/acal_core/languages.py`:
   - Add one `Language(...)` entry: name, label, extensions, `can_read=True`, `can_write=False`, and `capabilities="<lang>.yaml"`
   - Foreign languages are import-only. Do not set `can_write=True` without a writer and a round-trip test.

   Then `acal-core/src/acal_core/readers/__init__.py`:
   - Extend `detect_format_from_bytes` with a content-sniff rule if one was established in Phase 2
   - Add the format branch to `load()`
   - Re-export `<Lang>UnsupportedFeatureError` so callers can catch it by name

**4. CLI** — nothing to do. Both CLIs derive their `--from` choices from `LANGUAGES`. If you find yourself editing a `click.Choice`, stop: you have missed the registry entry.

## Phase 5: Test

Create test fixtures under `acal-core/tests/fixtures/<lang>/`. Required categories:

- **Valid** — at least one fixture per major construct (simple permit, condition, combining algorithm if supported, obligation if supported, attribute access)
- **Unsupported constructs** — one fixture per disposition-(c) gap; each should trigger `<Lang>UnsupportedFeatureError`
- **Warning-eligible constructs** — one fixture per disposition-(b) gap; confirm the warning fires under `--no-strict` and the error fires under `--strict`
- **Fidelity** — at least one fixture where `load_with_report` returns a non-empty `report.notes`, and one clean fixture where it returns none. A disposition-(b) gap that produces no note is a silent drop.
- **Round-trip** — for any gap confirmed as lossless in Phase 2, a fixture that converts to YACAL/JACAL and back to the neutral dict with no data change

Add tests in `acal-core/tests/test_core.py` (or a dedicated `tests/test_<lang>_reader.py` if volume warrants it). Every fixture must have a corresponding test. Run the full suite after adding each fixture group — don't batch them all and run once at the end.

## Phase 6: Validate

- Run `pytest` from `acal-core/`, `acal-converter/`, **and** `acal-explain/` — a reader change touches all three, and the registry parity tests live in the two tool suites
- Exercise both CLIs end-to-end:
  - `acal-convert <fixture> --from <lang> --to yacal`
  - `acal-explain <fixture>` — must work directly on the source file, with no intermediate policy file written, and must print an Import Fidelity section when the fixture is lossy
- Test `--strict` on a warning-eligible fixture and confirm it errors
- Test `--no-strict` on the same fixture and confirm it warns and converts
- Confirm `detect_format` correctly identifies a sample file by content sniff (if implemented) and by extension

## Phase 7: Wrap up

1. Run `/session-historian` — capture what was built, any architectural decisions made during Phase 2 that aren't already in the diary, and any lessons learned during implementation (parser setup surprises, grammar edge cases, mapping decisions that were harder than expected).
2. Run `/code-review` — perform a final review of the diff against the gap analysis decisions from Phase 3 and the project's no-silent-drops standard.

## Phase 8: Refine this skill

After completing a language with this skill, evaluate before closing the session:

- Were any Phase 2 question areas missing or did they fail to surface an important decision?
- Were the Phase 5 fixture categories the right set for this type of language?
- Did any phase take significantly longer than expected — and if so, should the skill be more prescriptive there?
- Were there any implementation surprises that would help a future language go faster?

Edit this skill file with those refinements so the next language benefits from what ALFA taught us.
