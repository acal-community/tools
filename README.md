# ACAL tools

Tools for working with **ACAL 1.0** access-control policies: validating them, converting other
policy languages into them, and explaining what a policy does.

ACAL 1.0 is a neutral access-control model with three serializations — **XACML 4.0** (XML),
**YACAL** (YAML), and **JACAL** (JSON). These are the *hub*. Every other policy language —
XACML 2.0 and 3.0, ALFA, Cedar, and more to come — is a *spoke* that imports into the hub. That
framing is the spine of the whole toolchain; if you read one thing first, read
**[the design overview](docs/design/README.md)**.

## Packages

| Package | What it does |
|---|---|
| [`acal-core`](acal-core/) | The shared library: readers (XACML, YACAL, JACAL, ALFA, Cedar), writers (YACAL, JACAL), the language registry, and the per-dialect capability matrices. |
| [`acal-convert`](acal-converter/) | CLI: convert any readable source language to YACAL or JACAL. |
| [`acal-explain`](acal-explain/) | CLI: explain what a policy does in plain English, and report what its source language could not express faithfully in ACAL. |
| [`yacal-validator`](yacal-validator/) | Gold-standard validator for YACAL (YAML) policies. |
| [`jacal-validator`](jacal-validator/) | Validator for JACAL (JSON) policies. |

Each package is self-contained (`pip install -e ./<package>`) with its own tests.

## Design

The **structural decisions** that define how conversion works — and, just as importantly, what
they commit us to — are documented as Architecture Decision Records:

- **[Design overview and ADR index](docs/design/README.md)** — start here.
- Per-language gap analyses: [`acal-core/docs/policy-language-expressiveness.md`](acal-core/docs/policy-language-expressiveness.md).
- The machine-readable capability matrices: [`acal-core/capabilities/`](acal-core/capabilities/).

The load-bearing commitment across all of it: the artifact is access-control policy, so the
toolchain **never loses or changes policy meaning silently** — it reports, or it refuses, but it
does not quietly convert a policy into a different one.

## Roadmap

See [`ROADMAP.md`](ROADMAP.md): an XACML 4.0 writer, an ACAL export tool, interactive
conversion (`acal-decisions` + `acal-web`), and further language imports.

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md). New source languages are added with the
`/import-model` process; readers live in `acal-core` and every language is registered once in
`acal-core/src/acal_core/languages.py`.

## License

[Apache License 2.0](LICENSE).
