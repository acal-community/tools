# Session Context — tools

**Last Updated**: June 16, 2026

---

## Current State

The tools repo has been restructured from a combined multi-format validator into per-language tools. Three branches:

- **`main`** — base branch; diary files, CLAUDE.md, CONTRIBUTING.md, `.gitignore` only
- **`acal-validator`** — the original combined XML+JSON+YAML validator (pre-split); kept until `jacal-validator` is ready, then to be deleted
- **`yacal-validator`** — active development branch; self-contained YACAL v1.0 (YAML) validator, **complete with fixture-based tests**

`yacal-validator` status: **31 passed, 2 skipped** (the 2 skipped are XPath example tests that need `.yaml` fixture files not yet in the spec repo).

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

### June 16, 2026 — Phase 2: --include flag; three-way exit codes; INCOMPLETE output state

**Added `--include FILE`** (repeatable) to CLI. Loads additional YACAL files into the resolution index before constraint evaluation. Required when a document has `PolicyReference` or `SharedVariableReference` pointing to definitions in external files.

**Three-way exit codes:**
- `0` — valid AND fully evaluated (no skipped constraints)
- `1` — validation failed (one or more errors)
- `2` — incomplete (cross-file references could not be resolved, provide `--include`)
         OR tool error (missing schemas, bad input, etc.)

**Output state `INCOMPLETE`** — `human()` now shows `INCOMPLETE  YACAL v1.0 (YAML) — file.yaml  (N constraint(s) not evaluated — use --include)` when `result.incomplete` is True. Previously valid-with-skips fell through to the advisory-warnings PASS branch.

**`result.incomplete`** property on `ValidationResult` — `True` when `constraints_skipped > 0`. Surfaced in JSON output as `"incomplete": true`.

**Architecture:**
- `_merge_from_document()` — extracts SharedVariableDefinition and Policy entries from any document form (Bundle or standalone PolicyDocument)
- `_build_resolution_index(document, extra_docs=None)` — runs `_merge_from_document` over primary + extras and merges into shared context dict
- `evaluate(document, catalog, extra_docs=None)` — passes extra_docs to index builder
- `validate(..., include_paths=None)` — loads and parses include files via `_load_include_docs()`

**Key lesson:** The catalog paths `$.Policy.CombinerInput[].PolicyReference` and `$.Bundle.PolicyReference` do NOT cover `PolicyReference` nested inside `$.Bundle.Policy[].CombinerInput[]`. The Phase 2 test fixture must be a standalone PolicyDocument, not a Bundle, to exercise the catalog path.

**Test suite:** 36 passed, 2 skipped (permanent XPath). Three new Phase 2 tests (without include → exit 2, with matching include → exit 0, with mismatched include → exit 1).

---

### June 16, 2026 — Phase 1 within-Bundle resolution; 38/38 constraints evaluated

**Implemented:** Within-document resolution for the two formerly-skipped cross-document constraints (`sharedvariablereference-argument-datatype-agreement` and `policyreference-argument-datatype-agreement`).

Before Phase 1, both constraints blanket-skipped every document with advisory warnings. After Phase 1, for any document whose references resolve within the same Bundle, both constraints are fully evaluated — no skip warnings emitted.

**Mechanism:** `_build_resolution_index(document)` scans a Bundle and builds two indexes:
- `shared_vars: {Id → [ParameterType]}`  (from `Bundle.SharedVariableDefinition[]`)
- `policies: {PolicyId → [ParameterType]}` (from `Bundle.Policy[]`)

`evaluate()` builds the index before running catalog rules and passes it to `_property_agreement` via `context=`. For each `SharedVariableReference`/`PolicyReference` found in the document, the checker resolves it in the index. If found: runs `_check_argument_datatype_agreement()` which matches positional and named arguments against parameter DataType declarations. If not found (cross-file, Phase 2 territory): emits a per-reference skip warning with hint "Use --include to provide the definition file."

**Output change:** All valid fixtures now show `Constraints: 38/38 evaluated` with no skip annotation (was `34/36 evaluated · 2 skipped`).

**Test suite:** 33 passed, 2 skipped (permanent XPath). Two new fixtures added:
- `ex10-bundle-parameterized-sharedvar.yaml` — valid; exercises DataType agreement check
- `err10-sharedvar-datatype-mismatch.yaml` — invalid; `{integer}` passed where `{string}` required

**Phase 2 (next):** Add `--include FILE` CLI flag to load external definition files into the resolution index, enabling full evaluation for cross-file references.

---

### June 16, 2026 — Fixture test suite complete; gold-standard validation enforced

**Completed:** Added `tests/fixtures/valid/` (7 adoption guide examples, ex01–ex09) and `tests/fixtures/invalid/` (9 error cases). Created `tests/test_fixtures.py` with 19 parametrized and targeted tests. All 31 tests pass (2 permanent XPath skips unchanged).

**Gold-standard requirement:** yacal-validator must have NO known gaps. Two upstream catalog defects were found and remedied by supplementary constraint checks in `constraints.py` rather than documenting them as acceptable gaps:

1. **Missing catalog rule** — duplicate Rule IDs within a Policy CombinerInput had no catalog entry. Added `_check_rule_id_unique_within_policy()`.
2. **Wrong catalog path** — `shortidset-shortid-name-unique` uses path `$.ShortIdSet[].ShortId` which matches no real YACAL document form (ShortIdSet appears only at document root). Added `_check_shortid_name_unique()` with recursive traversal.

Both supplementary checks increment `constraints_total`/`constraints_evaluated` so coverage reporting stays accurate. Counter is now `38/38 evaluated · 2 skipped` for valid documents.

**Spec schema bugs fixed** (in `_patch_schema()` in validator.py):
1. `ExactMatchIdReferenceType.allOf[1].properties: null` — removes null properties key
2. `$defs.QuantifiedExpressionTypeTree` — bare list wrapped in `{"oneOf": [...]}`
3. `ArgumentTypeTree.oneOf[1].required` — scalar string promoted to array

**Constraint catalog path bug fixed** — All 7 non-graph checkers were reading path fields from rule top level; the catalog nests them under `AppliesTo`. Fixed systematically.

**False-positive in graph checker fixed** — `_graph_no_repeat` seeded `visited` with the node's own refs before traversal, causing immediate false-positive on first-hop edges. Fixed by initializing `visited` as empty set.

---

### June 16, 2026 — Saxon pivot, yacal-validator built, constraint transparency added

**Trigger:** A `/grill-me` session on Saxon EE licensing established that Saxon EE (commercial) is required for XSD 1.1 schema processing. The `saxonche` pip package (Saxon HE) cannot perform schema validation at all, making the original `acal-validator` XML path permanently broken for an open-source tool.

**Architectural pivot:** Split `acal-validator` into per-language tools. XML validation deferred to a separate effort. `yacal-validator` branch created from `main`, containing only YACAL code carved from `acal-validator` with XML/hint cruft stripped. Flat module layout (`src/yacal_validator/validator.py`, `constraints.py`, `schemas.py`, etc.); no `validators/` subdir; no migration hints; no Saxon dependency. (→ per-language-tools-no-xml)

**`__main__.py` + README:** Added `python -m yacal_validator` support. README documents three invocation modes (run from source, install locally, install from PyPI) and walks through the full PyPI publishing workflow step-by-step for first-time publishers.

**Constraint coverage transparency:** The catalog has 36 rules. Two require cross-document lookup and are permanently skipped. Before this change, skips were buried as individual WARNING issues; users had no summary-level signal that semantic validation was partial. `evaluate()` now returns `(issues, total, evaluated, skipped)`. `ValidationResult` carries the counters. Both human and JSON output surfaces coverage on every run. Multi-file batch validation stays external (shell loops) — the tool delivers a complete verdict on one file; orchestration is the caller's job. (→ constraint-coverage-always-surfaced)

---

## Open Items

- ~~**Phase 2**: Add `--include FILE` CLI flag~~ ✓ Done
- Create `jacal-validator` branch from `main` (next milestone after Phase 2)
- Delete `acal-validator` branch once `jacal-validator` is verified
- Populate root `README.md` with project description and tool index
- File upstream bugs against the spec repo:
  1. Three YAML authoring bugs in `acal-core-yaml-v1.0-structure.schema.yaml` (properties: null, bare list in $defs, required: scalar)
  2. Missing Rule ID uniqueness constraint in `acal-core-yaml-v1.0-constraints.yaml`
  3. Wrong path for `shortidset-shortid-name-unique` in constraint catalog
- The 2 skipped XPath example tests require `.yaml` fixture files in the spec repo; revisit when spec adds YAML examples
- Publish to PyPI when both tools are stable

---

## Key Diary Files

- [architectural_decisions.md](architectural_decisions.md) — design principles, non-negotiable patterns
- [lessons_learned.md](lessons_learned.md) — anti-patterns and hard-won insights (most recent at top)
