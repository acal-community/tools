# Capability matrices

One YAML file per source language, naming which **ACAL features** that language can
express. This is the machine-readable form of the gap analysis in
[`../docs/policy-language-expressiveness.md`](../docs/policy-language-expressiveness.md).

The prose doc explains *why* to a human. These files are the same knowledge in a form a
tool can execute. When the two disagree, these files win — they are the ones that run.

## Why it is keyed by ACAL feature, not by source construct

A reader asks "what does this source construct become in ACAL?" — that is the **import**
direction, and it is answered by the reader's own code.

These files ask the opposite question: "what can this language say *about* ACAL?" That is
the **export** direction, and it is the one nobody can answer by reading the reader. It is
also the question three separate consumers need answered:

- **the reader** — which constructs warn, and which are hard errors (`disposition`)
- **`acal-explain`** — "this policy uses 3 ACAL features Cedar could never express"
- **the future ACAL export tool** — its precondition gate: refuse to emit a policy whose
  semantics the target language cannot hold

Authoring this once, per language, is what makes the export tool tractable later. Doing the
audit three times in three places is what makes it not.

## Schema

```yaml
language: cedar              # must match the `name` in languages.py
direction: import-only       # import-only | bidirectional
reference: https://…         # authoritative spec/dialect reference

acal_features:
  <FeatureName>:             # an ACAL construct, e.g. CombiningAlgId, NoticeExpression
    exportable: false        # true | false | partial
    disposition: c           # a–e, see below
    supported: [...]         # optional; when `partial`, the subset that survives
    note: >
      One line on what the limit is and what it costs. This text is user-facing —
      acal-explain may surface it verbatim.
```

## Dispositions

| Code | Meaning |
|---|---|
| `a` | Direct mapping — 1:1 structural translation |
| `b` | Lossy — `UserWarning` on import; promoted to an error under `--strict` |
| `c` | Hard error — always raises `<Lang>UnsupportedFeatureError` |
| `d` | Supplementary transformation — ACAL equivalent synthesized, not directly present in source |
| `e` | ACAL model extension required — stop and flag; do not implement around it |

## Adding a language

`/import-model <LANGUAGE>` writes this file in Phase 3, **before** any reader code exists.
That ordering is deliberate: the gap analysis is a design decision, and design decisions
that get made while writing the parser get made badly.
