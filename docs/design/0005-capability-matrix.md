# ADR-0005: The capability matrix is the single source of truth

**Status:** Accepted · **Applies to:** `acal-core/capabilities/`, readers, `acal-explain`, future `acal-export`

## Context

Three separate consumers need to know the same things about a spoke language:

- the **reader**, to decide which constructs warn versus hard-error, and how datatypes map;
- **`acal-explain`**, to report which ACAL features in a document that language could never
  express;
- the future **`acal-export`** tool, as its precondition gate — refuse to emit a policy whose
  semantics the target cannot hold.

The first plan was to record this as prose. But prose cannot gate a tool, so the analysis would be
redone — a third time, after the reader and the human-readable doc — and by then the three would
have drifted. Access-control conversion is exactly the domain where "the docs said one thing and
the code did another" is dangerous.

## Decision

Each spoke dialect has **one machine-readable capability matrix**,
`acal-core/capabilities/<dialect>.yaml`, that is the single source of truth. It carries both
directions of knowledge:

- **`acal_features:` — the export direction.** Keyed by *ACAL feature* (not by source construct),
  because the question is "what can this dialect say *about* ACAL?" — the question nothing in the
  reader answers. Each entry records whether the feature is exportable, a disposition, and a
  one-line reason. This is the export tool's gate, and what `acal-explain` reports against.
- **`datatypes:` — the import direction.** How the dialect's types and extension functions become
  ACAL ones, consulted by the reader through a **resolution ladder**:
  1. a built-in direct mapping exists → proceed (exact);
  2. else a `datatypes:` entry exists → proceed; if it is `fidelity: approximate`, warn (error
     under `--strict`);
  3. else → **hard error**, and the message names the missing entry.

The prose that explains *why* to a human lives in `policy-language-expressiveness.md`; where the
two disagree, **the matrix wins**, because it is the one that executes.

## Consequences

- **The audit is done once, per dialect, and every tool reads the result.** No dialect's gaps are
  re-derived in three places, and the export tool becomes tractable because its specification
  already exists as the accumulated matrices.
- **"Cannot map" is actionable, not terminal.** A datatype the reader will not guess at
  (`acal_type: null` — e.g. Cedar `ipaddr`, where mapping a subnet check onto string comparison
  would silently become a text match that fails open) produces an error naming the one line of
  YAML that would make it work. A refusal to guess is recorded as data, not left implicit.
- **Native dialects have no matrix**, by construction — they express the whole model, so there is
  nothing to declare (see [ADR-0001](0001-acal-is-a-hub.md)).
- **A misconfigured matrix fails loudly.** Because the EST carries no type at a call site, two
  datatypes claiming the same source function name is unresolvable; the reader raises at
  construction rather than silently mapping one type's method to another's function.
- **Conversion decisions ride in the same file** (`decisions:`), so the knowledge a human decision
  needs and the knowledge a tool executes are never separated — see [ADR-0006](0006-decisions-as-data.md).

## See also

- [`../../acal-core/capabilities/README.md`](../../acal-core/capabilities/README.md) — the matrix schema, the ladder, and the disposition codes.
- `diary/architectural_decisions.md` → `capability-matrix-is-the-delta-list`, `datatype-resolution-ladder`.
- `diary/lessons_learned.md` → `capability-claims-must-be-checked-against-the-reader`.
