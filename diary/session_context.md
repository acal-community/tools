# Session Context

## Current State (June 2026)

Three packages are now in active development on the `acal-explain` branch (which includes all `acal-core` work):

- **`acal-core/`** — shared library with all format readers, writers, and detection logic. 81 tests.
- **`acal-converter/`** — thin CLI wrapper (`acal-convert`) over `acal-core`. 20 tests.
- **`acal-explain/`** — new standalone tool (`acal-explain`) that loads an ACAL policy, runs structural analysis, and calls an LLM (via litellm) to produce a plain-English explanation. 30 tests.

All 131 tests pass. Each package runs its own pytest suite in isolation from its own directory (per-tool-directory pattern). The cross-package run from the tools root has a conftest naming collision due to multiple packages sharing the same test file names — each tool is intended to be tested independently.

## Most Recent Session (June 2026)

### acal-explain implementation

**Why this work:** The grill-me interview from the previous session established that explaining ACAL policies in plain English would be a standalone tool, not a flag on `acal-convert`. It needs the same readers as `acal-converter` (now shared via `acal-core`), an LLM abstraction, and a structured analysis pass that gives the LLM factual grounding rather than asking it to reason cold from raw JSON.

**Structured analyzer (`analyzer.py`):** Computes deterministic, LLM-free observations from the loaded neutral dict: default effect given the combining algorithm, shadowed/unreachable rules (firstApplicable with unconditional Permit before Deny; denyOverrides with unconditional dominant rule), obligation/advice gaps (effects with rules but no associated notices), and unresolved attribute designators (no Category declared). These facts feed both LLM calls as grounding context. (→ acal-explain-two-call-llm)

**LLM layer (`llm.py`):** Two separate `litellm.completion` calls — call 1 (structural summary) receives the full neutral dict serialized as JSON alongside metadata; call 2 (observations) receives only the structured analysis findings. Keeping them separate means the first call can focus on "what does this policy do" while the second focuses on "what should a reviewer care about." litellm is imported at module level (not inside the function) so tests can mock it cleanly. (→ litellm-module-level-import-for-mocking)

**Config (`config.py`):** Reads `~/.config/acal-explain/config.toml` for `[llm]` (model, api_key, api_base) and `[output]` (format). Environment variables `ACAL_EXPLAIN_MODEL`, `ACAL_EXPLAIN_API_KEY`, `ACAL_EXPLAIN_API_BASE` take precedence. Model strings follow litellm's `provider/model` convention (e.g. `anthropic/claude-sonnet-4-6`, `ollama/llama3`). No model versions are hardcoded — the config file is the source of truth. (→ acal-explain-config-file)

**CLI (`cli.py`):** `acal-explain <file> [--from xacml|yacal|jacal] [--format text|markdown|json] [--output file] [--model string]`. ALFA input is explicitly rejected with a clear error message directing the user to convert first — ALFA is a source format, not an ACAL policy language, so the tool only explains what the ACAL family is expressing. (→ acal-explain-acal-only-input)

**Tests:** Analyzer tests cover combining-algorithm semantics, shadow detection, obligation gaps, unresolved attrs, and bundle documents — all without LLM calls. CLI tests mock `litellm.completion` using `unittest.mock.patch` against the module-level import.

## Open Items for Next Session

- **README files**: `acal-core/README.md` and `acal-explain/README.md` are empty placeholders. Populate once the feature set is stable enough to document.
- **Nested attribute resolution for dotted paths**: `user.clearance`, `record.department` etc. still produce unresolved-attribute warnings in the ALFA reader because nested namespace declarations aren't walked. Known limitation, tracked in analyzer output as `unresolved_attrs`.
- **Streaming output**: Large policies produce slow LLM responses with no feedback. A `--stream` flag or streaming litellm calls would improve UX for interactive use.
- **`acal-explain` end-to-end smoke test** with a real LLM (CI-gated behind an env var check).
- **Phase 7**: Run `/code-review` on the ALFA reader diff.
- **Phase 8**: Refine `import-model` skill with lessons from ALFA implementation.
- **Cross-package pytest**: Running all tests from the tools root fails due to conftest naming collision. Consider adding a root `conftest.py` or `pytest.ini` that namespaces test discovery per package.
- **Existing open items** (pre-this-session):
  - Create PRs for `yacal-validator` and `jacal-validator` branches
  - Delete `acal-validator` branch once `jacal-validator` PR is merged
  - Populate root `README.md`
  - File upstream spec bugs (5 items from prior sessions)
  - Publish to PyPI when stable

## Key Diary Files

- [architectural_decisions.md](architectural_decisions.md) — design principles and non-negotiable patterns
- [lessons_learned.md](lessons_learned.md) — anti-patterns and hard-won insights (most recent at top)
