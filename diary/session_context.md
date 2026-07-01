# Session Context

## Current State (June 2026)

The `acal-core` branch is in active development, branched from `acal-converter`. It introduces a new shared library package `acal-core/` containing all format readers and writers, and rewires `acal-converter` as a thin CLI wrapper that imports from it. 81 tests pass in `acal-core/tests/`, 20 CLI plumbing tests pass in `acal-converter/tests/`. `acal-explain` tooling has not yet been started.

**ALFA import: Multi-file support, Axiomatics real-world fixtures, debug tooling complete. 101 tests passing across both packages.**

## Most Recent Session (June 2026)

### acal-core extraction

**Why this work:** The `/grill-me` interview for the new `acal-explain` tool surfaced that both `acal-converter` and `acal-explain` need the same readers and format detection logic. Rather than duplicating, we extracted everything into a shared `acal-core/` library. This is the first time the per-tool-directory pattern has a shared dependency — and the decision included writers as well, because future bidirectional conversion work (ACAL → source language) will need shared writers too. (→ acal-core-as-shared-library)

**What was moved:**
- All readers (`xacml`, `yacal`, `jacal`, `alfa`) → `acal-core/src/acal_core/readers/`
- All writers (`yacal`, `jacal`) → `acal-core/src/acal_core/writers/`
- All test fixtures (alfa, xacml2, xacml3, yacal, jacal) → `acal-core/tests/fixtures/`
- `policy-language-expressiveness.md` → `acal-core/docs/`
- The `convert()` convenience function → `acal_core/__init__.py`

**Test split:** Deep reader/writer/format-detection tests moved to `acal-core/tests/test_core.py`. `acal-converter` now has `tests/test_cli.py` with only CLI plumbing tests (argument handling, --strict/--debug/--include wiring, output-to-file). CLI tests reference fixtures via a cross-package relative path (`../../../acal-core/tests/fixtures/`) — intentional monorepo coupling since acal-converter is explicitly a thin wrapper.

**acal-converter after extraction:** `pyproject.toml` depends on `acal-core` + `click` only (no more lark/ruamel.yaml). `cli.py` imports from `acal_core.readers` and `acal_core.writers`. `__init__.py` re-exports `convert`, `detect_format`, `load` from `acal_core` for backward compatibility.

## Open Items for Next Session

- **Build `acal-explain`** (branch `acal-explain` from `acal-core`):
  1. `acal-explain/` directory with own `pyproject.toml` depending on `acal-core` + `litellm` + `click`
  2. Structured policy analyzer: default-deny gap detection, shadowed rule detection, obligation completeness, attribute assumption gaps
  3. `litellm`-based LLM abstraction with config file (`~/.config/acal-explain/config.toml` + env var overrides)
  4. Two-call prompting strategy: (1) structural summary, (2) observations/nuances
  5. CLI: `acal-explain <file> [--format text|markdown|json] [--output file]`
  6. Input restricted to XACML/YACAL/JACAL (ALFA must be converted first via acal-convert)
- **Nested attribute resolution for dotted paths**: `user.clearance`, `record.department` etc. still produce unresolved-attribute warnings because the resolver doesn't walk nested namespace declarations. Known limitation, not blocking.
- **Phase 7**: Run `/code-review` on the ALFA reader diff
- **Phase 8**: Refine `import-model` skill with lessons from ALFA implementation
- **Existing open items** (pre-this-session):
  - Create PRs for `yacal-validator` and `jacal-validator` branches
  - Delete `acal-validator` branch once `jacal-validator` PR is merged
  - Populate root `README.md`
  - File upstream spec bugs (5 items from prior sessions)
  - Publish to PyPI when stable

## Key Diary Files

- [architectural_decisions.md](architectural_decisions.md) — design principles and non-negotiable patterns
- [lessons_learned.md](lessons_learned.md) — anti-patterns and hard-won insights (most recent at top)
