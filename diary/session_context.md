# Session Context — tools

**Last Updated**: June 16, 2026

---

## Current State

The tools repo is being split into per-language tools. Three branches exist:

- **`main`** — base branch; diary files, CLAUDE.md, CONTRIBUTING.md only
- **`acal-validator`** — the original combined XML+JSON+YAML validator (pre-split); kept until `yacal-validator` and `jacal-validator` are both validated, then to be deleted
- **`yacal-validator`** — new single-purpose YACAL v1.0 (YAML) validator; currently active; tests passing (8 passed, 2 skipped)

The `yacal-validator` branch contains `tools/yacal-validator/`, a self-contained Python package (src layout, `pyproject.toml`, Python ≥3.11) with:
- CLI command: `yacal-validate`
- Two-layer validation: JSON Schema 2020-12 structural validation → constraint catalog
- `$dynamicRef`/`$dynamicAnchor` profile composition for XPath and JSONPath profiles
- Schema source configurable via `yacal-validator.toml`, cached in `~/.cache/yacal-validator/`
- No Saxon dependency; no XML validation; no migration hints

---

## Most Recent Sessions

### June 16, 2026 — architectural pivot: split acal-validator into per-language tools

**Trigger**: `/grill-me` session established that Saxon EE (commercial license) is required for XSD 1.1 schema validation, and Saxon HE (the free tier) provides zero schema validation capability. Since the `tools` repo is open source, a commercial license dependency is unacceptable. XML/XACML validation will be handled separately (potentially in Java by another team member).

**Decision**: Split `acal-validator` into independent per-language tools:
- `yacal-validator` (this branch) — YAML only
- `jacal-validator` (next branch, from `main`) — JSON only
- `acal-validator` branch to be deleted once both are verified

**Architecture of yacal-validator**:
- Flat module layout under `src/yacal_validator/`: `validator.py`, `constraints.py`, `schemas.py`, `base.py`, `cli.py`, `output.py`, `config.py`
- No `validators/` subdir; no format detector (single-format tool)
- `.json` input → immediate error with "use jacal-validate" message
- No shared library with jacal-validator; each tool is self-contained
- No migration hints (clean slate; no XACML 3.0 → ACAL 1.0 migration guidance)
- Dependencies: `click`, `httpx`, `jsonschema[format-nongpl]`, `referencing`, `ruamel.yaml`

**Status**: `yacal-validator` branch complete and tests passing. Next step: create `jacal-validator` branch from `main`.

### June 15–16, 2026 — acal-validator built, debugged, corrected

Designed and built `acal-validator` in a single session. The tool was subjected to a code review that identified five issues, all of which were fixed before the first commit. Key fixes:

1. **YAML no-profile crash**: `_composed_root()` omitted `$id` in the base (no profile) case.
2. **Incomplete YACAL profile hooks**: Missing `XPathEntityAttributeSelector`, `JSONPathEntityAttributeSelector`, and `$dynamicAnchor` entries.
3. **`propertyAgreement` rules silently not enforced**: Fields read from wrong level (top vs. `AppliesTo`).
4. **Test suite tied to one machine**: Added `ACAL_SPEC_DIR` env var override and auto-skip.
5. **Extension-first format detection**: Changed to content-sniff-first.

---

## Open Items

- Create `jacal-validator` branch from `main` (next step after this session).
- Delete `acal-validator` branch once `jacal-validator` is verified.
- Populate root `README.md` with project description and tool index.
- Rule*.json example files in the spec repo use `Apply.Expression` instead of `Apply.Argument` — worth filing upstream once reviewed.
- The 2 skipped XPath example tests in `yacal-validator` require `.yaml` example files in the spec repo (currently only `.xml` examples exist); revisit when spec adds YAML examples.

---

## Key Diary Files

- [architectural_decisions.md](architectural_decisions.md) — design principles, non-negotiable patterns
- [lessons_learned.md](lessons_learned.md) — anti-patterns and hard-won insights (most recent at top)
