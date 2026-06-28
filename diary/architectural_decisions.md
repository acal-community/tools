# Architectural Decisions

Design principles and the reasoning behind non-obvious choices. Add an entry when a future
engineer would reasonably ask "why did they do it this way?" — and the answer isn't obvious
from the code.

Most recent decisions at top. No archiving.

---

## one-test-path-per-yacal-rule-family (June 2026)

The `yacal-validator` suite intentionally maintains at least one deliberate test path for every current YACAL constraint-catalog rule, plus explicit coverage of YAML-specific conformance rules and every supported root document form.

**Why:** This tool is being positioned as the reference validator for YAML ACAL policies. "A lot of tests" is not a sufficient bar; the suite needs traceable coverage over the actual rule inventory so we can tell the difference between an unimplemented rule, an unreachable rule, and a rule that is working correctly. This decision directly shaped the fixture expansion work: when the upstream schemas made some catalog rules unreachable, we patched the loader locally rather than accepting blind spots in the compliance suite.

---

## constraint-coverage-always-surfaced (June 2026)

`evaluate()` returns `(issues, total, evaluated, skipped)`. `ValidationResult` carries the three counters. Both human and JSON output always include a constraint coverage line when constraints ran.

**Why:** The catalog has 36 rules. Two (`sharedvariablereference-argument-datatype-agreement` and `policyreference-argument-datatype-agreement`) require cross-document reference lookup and are permanently skipped in single-file mode. Without explicit surfacing, users get no signal that their document received partial semantic validation — which is unacceptable for a tool positioned as the gold standard. Multi-file batch validation is intentionally left to external tooling (shell loops, `xargs`) so the tool stays single-file and each invocation produces a complete, accurate verdict. The tool's job is to report truthfully; orchestration is the caller's job.

---

## per-language-tools-no-xml (June 2026)

The tools repo ships one focused tool per policy language: `yacal-validator` (YAML) and `jacal-validator` (JSON). There is no combined multi-format validator and no XML validation.

**Why:** Saxon EE (commercial license) is required for XSD 1.1 schema processing of XACML v4.0 documents. The `saxonche` pip package provides Saxon HE, which cannot perform schema validation at all. Since the tools repo is open source, a commercial license dependency is a non-starter. XML/XACML validation is deferred to a separate effort (potentially Java-based). Each per-language tool is self-contained with its own `pyproject.toml`, `src/` layout, `tests/`, config file (`{tool}.toml`), and cache dir (`~/.cache/{tool}/`). No shared library between tools.

---

## content-sniff-first-detection (June 2026)

Format detection sniffs the file content first and uses the file extension only as a fallback when the content produces no clear signal.

**Why:** The stated product goal is language-first detection — a `.json` file that actually contains XML should be validated as XACML, not JACAL. Extension-first would silently send it to the wrong validator and report a syntax error. One special case: a `.yaml`/`.yml` file whose content starts with `{` is treated as YACAL (not JACAL) because YAML is a strict superset of JSON and YACAL documents may use JSON-compatible syntax.

---

## acal-validator-per-tool-directory (June 2026)

Each tool in this repo lives in its own self-contained subdirectory with its own `pyproject.toml` and `src/` layout, rather than sharing a monorepo package manifest.

**Why:** The tools repo is intended to host tools written in different languages. Forcing a single manifest would require choosing one build system and one language. Per-tool directories allow each tool to be installed, tested, and released independently.

---

## saxonche-for-xml-xsd11 (June 2026)

XACML v4.0 XML validation uses `saxonche` (Saxon C) rather than `lxml` or `xmlschema`.

**Why:** The XACML v4.0 schema uses XSD 1.1 `xs:assert` assertions. `lxml` and `xmlschema` have partial or no XSD 1.1 support. Saxon is the reference implementation for XSD 1.1. The companion Schematron file is explicitly documented in the spec as an alternative for XSD 1.0 environments, making it redundant when Saxon is available. **Caveat**: the `saxonche` pip package provides Saxon HE (Home Edition), which does NOT include schema-aware processing — that requires Saxon PE or EE. The XML validator degrades gracefully with a clear error rather than crashing (→ saxon-he-schema-not-licensed).

---

## schema-source-configurable (June 2026)

Schema files are not vendored into the tool. Instead, a configurable source (local path or GitHub URL) is resolved at runtime, with schemas cached in `~/.cache/acal-validator/` and refreshed on demand with `--refresh-schemas`.

**Why:** The ACAL/JACAL/YACAL specifications are still in active development. Vendoring would require a tool release for every spec update. The cache means network access is only required on first use or explicit refresh, which is acceptable for a developer tool. This also allows contributors to point the tool at a local spec checkout for offline work.

---

## yacal-two-layer-validation (June 2026)

YACAL validation runs in two layers: JSON Schema Draft 2020-12 structural validation first, then the machine-readable constraint catalog (`acal-core-yaml-v1.0-constraints.yaml`) only if structural validation passes.

**Why:** The constraint catalog enforces higher-order rules (uniqueness, reference integrity, graph acyclicity) that JSON Schema cannot express. Running catalog checks against a structurally invalid document produces confusing cascading errors. The two-layer gate keeps error messages actionable.

---

## jacal-profile-composition-via-dynamic-ref (June 2026)

Profile activation (XPath, JSONPath) is implemented by constructing an in-memory "composed root" schema with `$dynamicAnchor` entries in `$defs`, registered in the `referencing` registry alongside the core and profile schemas.

**Why:** The JACAL core schema uses `$dynamicRef`/`$dynamicAnchor` (JSON Schema 2020-12) as extension points. The spec provides a reference example (`jacal-root-schema-example-using-xpath-and-jsonpath-profiles.json`) showing the intended composition pattern. Auto-detecting profiles from document content and composing the root at runtime avoids requiring users to supply a root schema file — the tool handles it transparently.

---

## diary-initialized (June 2026)

Memtoad diary scaffolded at project inception. No architectural decisions have been made yet — the first real entry should be added when the initial tool scope and language/stack are chosen.

**Why:** Project is pre-alpha with no committed tooling code. Capturing the initialization event establishes the baseline and reminds future contributors to fill this in as the project takes shape.
