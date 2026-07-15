# ADR-0001: ACAL is a hub, not a dialect of XACML

**Status:** Accepted · **Applies to:** the whole toolchain

## Context

ACAL 1.0 has an XML serialization that is, by an accident of naming, called *XACML 4.0*. It is
tempting to conclude that ACAL is therefore "the latest XACML," and that XACML 2.0, 3.0, and 4.0
are three versions of one language the toolchain reads.

That framing is wrong, and it produced a real defect. When the language registry treated
"XACML 2.0–4.0" as a single foreign language with a single capability matrix, that matrix had to
answer for three languages at once — and it answered wrong, asserting that XACML "cannot express
`SharedVariableDefinition`." That is true of XACML 3.0 and **false** of XACML 4.0, which carries
shared variables natively because it *is* the ACAL model. Since the matrix is meant to gate a
future export tool, the error would have caused that tool to refuse to emit something it can emit
perfectly well.

## Decision

**The hub is ACAL itself, in every serialization it has or will have** — today XACML 4.0 (XML),
YACAL 1.0 (YAML), JACAL 1.0 (JSON); tomorrow any further ACAL version or encoding, which joins
the hub by definition.

**Everything else is a spoke, permanently.** XACML 2.0, XACML 3.0, ALFA, Cedar, AWS IAM, Rego. A
spoke is a foreign language that imports *into* the hub. Lineage confers nothing: XACML 1–3 are
spokes, not "earlier hub." ACAL is a new, independent endpoint that happens to have an XML
serialization; it is not a dialect of XACML.

Capability is a property of the **dialect**, not the file extension. An `.xml` file may be a
foreign XACML 3.0 policy or the native ACAL XML serialization, and the reader resolves which by
namespace. Native dialects have **no** capability matrix — they express the whole model by
construction, so there is nothing they cannot say. Only spokes declare gaps.

## Consequences

- **Native ⇄ native conversion is lossless; spoke → hub is not.** The two are handled by
  different machinery. Emitting a hub serialization is *serialization* (a writer beside the
  YACAL and JACAL writers); emitting into a spoke is *export* (a separate, harder problem — see
  [ADR-0005](0005-capability-matrix.md)).
- **A consequence people get wrong: XACML 4.0 output is not "export."** It is serialization of
  the hub, and it is not blocked by the Saxon licensing concern that applies to XML *schema
  validation* — writing XML is not validating it. An XACML 4.0 writer is therefore a
  near-term item, not part of the export tool.
- **The registry carries two tables, `LANGUAGES` and `DIALECTS`** (`acal-core/src/acal_core/languages.py`),
  because a *format* (what a file is encoded as) and a *dialect* (what a document actually is)
  are different things; one `.xml` format carries three dialects.
- **Adding a language means adding a spoke.** The `/import-model` process is spoke-shaped:
  gap analysis → capability matrix → reader → tests. A native serialization would instead get a
  reader *and* a writer with a lossless round-trip test.

## See also

- Stated as a first principle for contributors and agents in [`../../CLAUDE.md`](../../CLAUDE.md).
- [ADR-0005](0005-capability-matrix.md) — why matrices hang off dialects.
- `diary/architectural_decisions.md` → `acal-is-a-hub-not-a-xacml-dialect` (the session record).
