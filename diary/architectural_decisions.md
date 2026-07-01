# Architectural Decisions

## acal-core-as-shared-library (June 2026)

All format readers and writers live in a dedicated `acal-core/` package. The `acal-converter` tool is a thin CLI wrapper that imports from it. Future tools (`acal-explain`, and any others) depend on `acal-core` directly.

**WHY**: The `acal-explain` tool needs the same readers and format-detection logic as `acal-converter`. The original per-tool-directory pattern (one self-contained `pyproject.toml` per tool, no shared libraries) was chosen to avoid build-system coupling — but it only holds when tools share no logic. Once a second tool needs the same readers, the only options are duplication or a shared library. Duplication is worse: two copies of the ALFA grammar and Lark transformer would diverge. The shared library breaks the pattern intentionally and only for logic that genuinely belongs at the core: parsing and serialization of ACAL formats. CLI entrypoints, configuration, and output formatting remain per-tool. Writers were included alongside readers because future bidirectional conversion (ACAL → source language) will also need shared serializers. (→ per-language-tools-no-xml)

---

## alfa-policyset-as-policy (June 2026)

A `policyset_decl` that appears at the namespace level is surfaced in the ACAL neutral dict as a `"Policy"` key, not a `"PolicySet"` key.

**WHY**: The neutral dict top-level schema only has `{"Policy": ...}` and `{"Bundle": {"Policy": [...]}}` forms. A `policyset` in ALFA is structurally equivalent to a `policy` in ACAL — both have `PolicyId`, `CombiningAlgId`, `Target`, and `CombinerInput`. Emitting a `"PolicySet"` wrapper that no writer or downstream consumer handles would cause silent data loss. The writers (YACAL, JACAL) treat the neutral dict as pass-through, so the key name matters at the output level, not the ALFA source level.

---

## alfa-system-decl-discard (June 2026)

System.alfa-style declarations (`ruleCombinator`, `policyCombinator`, `type`, `category`, `function`, `infix`) are parsed by the grammar and silently discarded by the transformer — they are not collected into the symbol table.

**WHY**: These declarations are PDP runtime configuration (mapping short names to XACML URNs for combining algorithms, types, and operators). They have no ACAL equivalent — ACAL uses fixed combining algorithm URNs and does not need type or operator declarations. The grammar must accept them so `system.alfa` can be passed as an `--include` file without parse errors; the transformer discards them because they contribute nothing to the ACAL output. The `infix` body grammar uses `INFIX_BODY: /[^}]+/` (a single regex terminal matching everything except `}`) to avoid writing a full type-signature sub-grammar that will never be used.

---

## alfa-target-clause-keyword (June 2026)

The `target_clause` rule accepts an optional `_CLAUSE_KW` ("clause") after the `target` keyword, matching the full Axiomatics ALFA syntax `target clause <expr>`.

**WHY**: Axiomatics ALFA consistently uses `target clause <expr>`. The ALFA spec grammar uses the two-word form. Our synthetic test fixtures were written without `clause` and happened to work (because `clause` was parsed as a DOTTED_ID attr_path, leaving the expression to follow — which happened to parse correctly for simple fixtures). Real-world policy files expose the gap immediately. Adding `_CLAUSE_KW?` preserves backward compatibility with either form.

---

## alfa-apply-in-body (June 2026)

The `applying_kw` alternative is allowed both before `{` (ACAL convention) and inside `policy_body` / `policyset_body` (Axiomatics convention). The transformer checks for `str` items in the body list when no combining algorithm was provided in the pre-body position.

**WHY**: Axiomatics ALFA consistently puts `apply <algo>` inside the braces alongside `target clause` and rules. ACAL synthetic fixtures used the pre-brace form. Neither form is wrong — the ALFA spec is ambiguous on this point. Supporting both means the converter accepts real-world files without preprocessing.

---

## alfa-keyword-exclusion-in-dotted-id (June 2026)

The ALFA grammar excludes all ALFA reserved words from matching the `DOTTED_ID` terminal via a negative lookahead regex, rather than relying on terminal priority to resolve the ambiguity.

**WHY**: Lark's earley parser with `ambiguity="resolve"` picks the first valid alternative in a rule regardless of terminal priority. When `func_call: DOTTED_ID "("` appeared before `var_ref: VAR_REF_KW "("` in the `primary_expr` alternation, `variable(name)` was always parsed as a `func_call` (with `variable` tokenized as DOTTED_ID), because earley explores all options and then picks by order, not by specificity. Preventing DOTTED_ID from ever matching reserved words makes the grammar unambiguous by construction rather than by resolution policy. The pattern is: `DOTTED_ID: /(?!(namespace|policy|...|variable)[^a-zA-Z0-9_])[a-zA-Z_].../`.

---

## lark-keyword-discard-prefix (June 2026)

All ALFA grammar keyword terminals whose string value is not needed by the transformer use the `_` prefix (e.g., `_POLICY_KW`, `_CONDITION_KW`) so Lark auto-discards them from the transformer's item lists.

**WHY**: Without `_` prefix, Lark includes named keyword terminals as `Token` objects in the children list passed to each transformer method. This makes position-based access to actual content unreliable — `policy_decl` receives `[Token('_POLICY_KW','policy'), Token('IDENTIFIER','DocAccess'), ...]` instead of `[Token('IDENTIFIER','DocAccess'), ...]`. Every method needs to filter or skip tokens, which is error-prone and verbose. The `_` prefix is idiomatic Lark for "structural glue — don't pass to transformer." Value-carrying terminals that the transformer needs (PERMIT_KW, DENY_KW, CMP_OP, etc.) keep their names.

---

## alfa-separate-error-types (June 2026)

The ALFA reader defines two distinct exception classes: `ALFASyntaxError(ValueError)` for parse failures and `ALFAUnsupportedFeatureError(ValueError)` for semantic conversion failures. Both inherit `ValueError`, matching `XACMLUnsupportedFeatureError`.

**WHY**: Callers need to distinguish "this file is not valid ALFA syntax" (user supplied wrong input) from "this ALFA construct has no ACAL equivalent" (language gap, user needs to redesign). These require different user actions and different error messages. Inheriting `ValueError` rather than stdlib `SyntaxError` keeps the exceptions in application-error territory rather than interpreter-error territory, avoiding the need to populate interpreter-specific attributes (`lineno`, `filename`, `offset`) that `SyntaxError` carries.

---

## alfa-two-pass-symbol-table (June 2026)

The ALFA reader operates in two passes: a pre-pass (`_collect_symbols(tree)`) that walks the raw Lark `Tree` to populate a `_SymbolTable` (attribute declarations, obligation/advice URNs, namespace hierarchy), then a `AlfaTransformer(symbols, strict)` pass that resolves all paths and identifiers against the table.

**WHY**: ALFA allows shorthand attribute paths (`user.role`) where `user` is bound to a category via an `attribute { category = subjectCat }` declaration elsewhere in the file. A single-pass Lark Transformer visits nodes bottom-up and cannot resolve a shorthand path without first knowing all declarations. Policy-scoped variables are the one exception — they are tracked in `self._current_vars` inside the Transformer (reset per policy block) rather than in the symbol table, because they are short-lived and not referenced across blocks.

---

## import-model-skill-documents-before-code (June 2026)

The `import-model` skill requires Phase 3 (writing the expressiveness doc section with all gap dispositions) to be confirmed by the user before Phase 4 (implementation) begins.

**WHY**: Gap decisions made during analysis are easy to silently reverse during implementation — a construct that was agreed to raise an error gets quietly mapped instead, and the documentation is updated after the fact to match the code. Requiring written documentation and explicit user confirmation before any code is written makes the decisions reviewable and reversible. It also produces a paper trail for why each gap was handled the way it was, which matters for security-critical policy conversion tools where silent semantic changes can be dangerous.

---

## alfa-reader-uses-lark-not-antlr (June 2026)

The ALFA reader uses the `lark` Python parsing library with a custom ALFA grammar, not the ANTLR4 runtime with the official OASIS/Axiomatics ALFA grammar.

**WHY**: ANTLR4 requires a Java runtime for grammar compilation and adds `antlr4-python3-runtime` as a package dependency. ACAL's design philosophy is to shed the legacy XACML toolchain — carrying ANTLR into a modern JSON/YAML-profile converter runs counter to that goal. `lark` is pure Python, requires no compilation step, and the grammar risk is mitigated by test-driven development against real-world ALFA documents. If the grammar proves insufficient for a specific ALFA construct, it can be extended without changing the runtime dependency.

---

## jacal-never-errors-datatype-constraints (June 2026)

JACAL constraint fixtures for DataType agreement rules are categorized as "structurally prevented" rather than "constraint-level errors."

**WHY**: The JACAL JSON Schema uses `dependentSchemas` with `"not": true` on `Value.DataType` in multiple contexts (AttributeType, SharedVariableReferenceType.Argument, PolicyReferenceType.Argument, ParameterType.Expression) — making the DataType-bearing forms structurally invalid. The catalog rules evaluate on every document but can never produce constraint errors for schema-valid input. Trying to create fixture documents that trigger these constraint errors inevitably produces schema errors instead, because the only inputs that would trigger the constraint are inputs the schema rejects first.

## two-layer-two-exit-code-design (prior session)

The validator uses a two-layer architecture (JSON Schema structural pass → constraint catalog pass) with three exit codes (0=valid+complete, 1=fail, 2=incomplete).

**WHY**: Constraint evaluation is expensive and meaningless on structurally broken documents. Separating layers allows constraints to assume a well-formed document and focus only on semantic rules. The third exit code (incomplete) models the case where a cross-document reference can't be resolved without `--include`; silently passing would hide real gaps.

## separate-tools-per-language (prior session)

Validator tooling is split into `jacal-validator` (JSON) and `yacal-validator` (YAML) rather than a single `acal-validator`.

**WHY**: XML validation requires a fundamentally different library stack (lxml, XPath, etc.) that bloats the tool for JSON/YAML users. Separate tools stay lightweight, can evolve independently, and let a Java-focused team handle XACML v4 validation separately. The constraint catalog (`acal-core-yaml-v1.0-constraints.yaml`) is shared — path evaluation works over parsed Python dicts regardless of source format.

## jacal-profile-composition-uses-type-tree-refs (prior session)

The JACAL composed root schema references `*TypeTree` names (e.g., `XPathPolicyDefaultsTypeTree`), NOT `*TypeExtension` like YACAL does.

**WHY**: The JACAL XPath profile schema was authored to use `*TypeTree` as the `$ref` target for dynamic anchors. YACAL requires a corrective patch at runtime (`*TypeTree` → `*TypeExtension`); JACAL uses the correct names as-authored and requires no patch.

## patch-attributeselectortype-unevaluateditems (prior session)

`_patch_core_schema_shape_bugs()` removes `unevaluatedProperties: false` from `AttributeSelectorType` and `EntityAttributeSelectorType` in the JACAL core schema at runtime.

**WHY**: The JACAL core schema's abstract base types use `unevaluatedProperties: false`, which prevents the XPath profile from adding `ContextSelectorId`. This is a spec bug — the abstract base type cannot know about subtype-specific properties. Upstream bug report is pending. The workaround must stay in the validator until fixed upstream.
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
