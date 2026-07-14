# Capability matrices

One YAML file per **foreign dialect**, naming which **ACAL features** that dialect can
express. This is the machine-readable form of the gap analysis in
[`../docs/policy-language-expressiveness.md`](../docs/policy-language-expressiveness.md).

The prose doc explains *why* to a human. These files are the same knowledge in a form a
tool can execute. When the two disagree, these files win — they are the ones that run.

## Hub and spoke — and why there is no `xacml.yaml`

ACAL 1.0 is a **hub**, not a dialect of XACML. It has three serializations of the same
neutral model:

| Serialization | Format |
|---|---|
| **XACML 4.0** | XML |
| **YACAL 1.0** | YAML |
| **JACAL 1.0** | JSON |

These are **native**. They express the whole ACAL model by construction, so they have **no
matrix at all** — there is nothing they cannot say.

Everything else is a **spoke**: a foreign dialect that imports *into* the hub. XACML 2.0,
XACML 3.0, ALFA, and in future Cedar, AWS IAM, Rego. Only spokes get matrices.

**Capability is a property of the dialect, not the file extension.** An earlier version of
this directory had a single `xacml.yaml` covering "XACML 2.0–4.0", which asserted that XACML
cannot express `SharedVariableDefinition`. That is true of 3.0 and **false of 4.0** — the
reader parses `<Bundle><SharedVariableDefinition>` natively. A matrix keyed on the language
has to pick one answer and is wrong half the time. Hence `xacml-2.0.yaml` and
`xacml-3.0.yaml`, and no matrix for `xacml-4.0`.

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

## Two sections, two directions

Each file carries the machine-readable knowledge about one dialect, in both directions:

| Section | Direction | Question it answers | Consumers |
|---|---|---|---|
| `datatypes:` | **import** | How do this dialect's types and functions become ACAL ones? | the reader |
| `acal_features:` | **export** | What can this dialect say *about* ACAL? | `acal-explain`, future `acal-export` |

## The datatype ladder

Datatype mismatch is the recurring headache across every spoke, so it is resolved once, here,
rather than ad hoc in each reader. When a reader meets a source type or extension function, it
walks a three-step ladder:

1. **A built-in direct mapping exists** → proceed. Exact.
2. **No direct mapping, but a `datatypes:` entry exists** → proceed using it. If that entry is
   `fidelity: approximate`, emit a fidelity note (disposition **b**) — promoted to a hard error
   under `--strict`.
3. **Neither** → **hard error** (disposition **c**), and the message names the missing entry.

Step 3 is the point of the whole mechanism. A type we cannot map is not a permanent wall and
it is not a silent guess: it is an error that tells you exactly which one line of YAML would
make it work. `acal_type: null` in a shipped map means "we know about this type and have
deliberately declined to guess" — see Cedar's `ipaddr`, where mapping to string comparison
would silently turn a subnet check into a text match.

`fidelity: approximate` exists because some mappings are usable but not safe to assume. Cedar
`decimal` is fixed-point (4 dp); ACAL `double` is IEEE-754 binary float. A comparison at a
precision boundary can decide differently — and in an authorization policy, "differently"
means someone gets access they should not. The note is not decoration; it is the warning text
the user sees.

## Schema

```yaml
language: cedar              # the format, per LANGUAGES in languages.py
dialect: cedar               # the dialect id, per DIALECTS in languages.py
direction: import-only       # import-only | bidirectional
reference: https://…         # authoritative spec/dialect reference

datatypes:                   # import direction — see "The datatype ladder" above
  decimal:
    acal_type: "{double}"    # null = deliberately unmapped; the reader hard-errors
    fidelity: exact | approximate | none
    note: >
      What is lost, and what it costs. User-facing: this is the warning text.
    functions:               # extension functions belonging to this type
      lessThan: "{double-less-than}"

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

## Consuming a matrix

```python
from acal_core import export_gaps, load

doc = load("policy.yaml", "yacal")
export_gaps(doc, "cedar")   # {feature: why-not} for features this doc actually uses
```

`acal-explain` calls this to report what a policy could never say in a given language. The
future `acal-export` tool calls the same function as its precondition gate.

## Adding a language

`/import-model <LANGUAGE>` writes this file in Phase 3, **before** any reader code exists.
That ordering is deliberate: the gap analysis is a design decision, and design decisions
that get made while writing the parser get made badly.

Most languages have exactly one dialect, so `language` and `dialect` are the same string and
you can ignore the distinction. Add a second dialect only when one format genuinely carries
two different models — as XML does.
