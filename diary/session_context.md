# Session Context — tools

**Last Updated**: June 16, 2026

---

## Current State

The tools repo has been restructured from a combined multi-format validator into per-language tools. Three branches:

- **`main`** — base branch; diary files, CLAUDE.md, CONTRIBUTING.md, `.gitignore` only
- **`acal-validator`** — the original combined XML+JSON+YAML validator (pre-split); kept until `jacal-validator` is ready, then to be deleted
- **`yacal-validator`** — active development branch; self-contained YACAL v1.0 (YAML) validator, functionally complete

`yacal-validator` status: **12 passed, 2 skipped** (the 2 skipped are XPath example tests that need `.yaml` fixture files not yet in the spec repo).

The tool provides:
- `yacal-validate FILE` CLI (installed via `pip install -e .`)
- `python -m yacal_validator FILE` (no install required, dependencies only)
- Two-layer validation: JSON Schema 2020-12 structural → constraint catalog (34/36 rules enforced; 2 permanently skipped due to cross-document reference lookup)
- Constraint coverage reported in every output: `Constraints: 34/36 evaluated · 2 skipped (cross-document reference lookup — not supported in single-file mode)`
- XPath and JSONPath profile auto-detection and composition
- Schema source configurable via `yacal-validator.toml`, cached at `~/.cache/yacal-validator/`
- JSON and human-readable output modes; exit codes 0/1/2

---

## Most Recent Sessions

### June 16, 2026 — Saxon pivot, yacal-validator built, constraint transparency added

**Trigger:** A `/grill-me` session on Saxon EE licensing established that Saxon EE (commercial) is required for XSD 1.1 schema processing. The `saxonche` pip package (Saxon HE) cannot perform schema validation at all, making the original `acal-validator` XML path permanently broken for an open-source tool.

**Architectural pivot:** Split `acal-validator` into per-language tools. XML validation deferred to a separate effort. `yacal-validator` branch created from `main`, containing only YACAL code carved from `acal-validator` with XML/hint cruft stripped. Flat module layout (`src/yacal_validator/validator.py`, `constraints.py`, `schemas.py`, etc.); no `validators/` subdir; no migration hints; no Saxon dependency. (→ per-language-tools-no-xml)

**`__main__.py` + README:** Added `python -m yacal_validator` support. README documents three invocation modes (run from source, install locally, install from PyPI) and walks through the full PyPI publishing workflow step-by-step for first-time publishers.

**Constraint coverage transparency:** The catalog has 36 rules. Two require cross-document lookup and are permanently skipped. Before this change, skips were buried as individual WARNING issues; users had no summary-level signal that semantic validation was partial. `evaluate()` now returns `(issues, total, evaluated, skipped)`. `ValidationResult` carries the counters. Both human and JSON output surfaces coverage on every run. Multi-file batch validation stays external (shell loops) — the tool delivers a complete verdict on one file; orchestration is the caller's job. (→ constraint-coverage-always-surfaced)

---

## Open Items

- Create `jacal-validator` branch from `main` (next milestone after this session)
- Delete `acal-validator` branch once `jacal-validator` is verified
- Populate root `README.md` with project description and tool index
- The 2 permanently-skipped constraints (`sharedvariablereference-argument-datatype-agreement`, `policyreference-argument-datatype-agreement`) cannot be evaluated without multi-file support — document them prominently in the README as a known limitation
- The 2 skipped XPath example tests require `.yaml` fixture files in the spec repo (currently only `.xml` examples exist); revisit when spec adds YAML examples
- Rule*.json example files in the spec repo use `Apply.Expression` instead of `Apply.Argument` — worth filing upstream once reviewed
- Publish to PyPI when both tools are stable

---

## Key Diary Files

- [architectural_decisions.md](architectural_decisions.md) — design principles, non-negotiable patterns
- [lessons_learned.md](lessons_learned.md) — anti-patterns and hard-won insights (most recent at top)
