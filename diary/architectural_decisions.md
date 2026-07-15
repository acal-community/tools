# Architectural Decisions

> **Cross-cutting structural decisions have a public home: [`docs/design/`](../docs/design/) (ADRs).**
> This file is the internal working log — dated entries, the session-level "why". The ADRs are
> the durable, contributor-facing statement with explicit consequences. When a decision here is
> structural enough to shape the whole toolchain, write or update the ADR and keep this entry as
> the log record; the ADRs cite these slugs back. Entries with an ADR are tagged `(→ ADR-NNNN)`.

## heavy-runtime-dependencies-are-optional-extras (July 2026)

A dependency that is heavy (compiled wheels, large transitive trees) and needed only for a
specific runtime capability is declared as an **optional extra**, not a hard dependency. The
code imports it lazily (`try/except ImportError`) and raises a clear install hint when the
capability is actually used; the test suite mocks or skips it.

**WHY**: Two packages now follow this — `acal-core[cedar]` (cedarpy, a Rust wheel, only for
reading `.cedar`) and `acal-explain[llm]` (litellm + openai/tokenizers/tiktoken/aiohttp, only
for live LLM calls). Making either a hard dependency imposes a heavy, fragile install on every
user and every CI job for a capability many of them never invoke — and, as the litellm case
showed, a hard heavy dependency that fails to build takes the whole package's install down with
it. The base install stays light and robust; the capability is one extra away. The rule for
"heavy enough to be optional": a compiled/Rust/C wheel, or a dependency that itself drags in a
large stack, that serves one clearly separable feature. (→ simulate-a-ci-workflow-in-a-clean-env-before-committing-it)

---

## conversion-decisions-are-data-not-flags (July 2026) (→ ADR-0006)

Every judgment call a *user* may legitimately make during conversion is enumerated as data, in
the `decisions:` block of `capabilities/<dialect>.yaml`: question, options, the consequence of
each, a default, the CLI flag that sets it, and a `triggers` condition. Three front-ends
consume that one definition — `--profile` (replay), `--interactive` (prompt), and the web UI
(form + download/upload).

Conversion becomes two-phase: `plan()` collects the decision points the *document actually
reaches*; `execute()` runs once they are resolved.

**WHY**: Cedar alone produced five user-facing decisions (presence fidelity, approximate
datatypes, unmapped datatypes, annotation loss, template handling). ALFA and XACML have their
own; Rego and IAM will add more. Expressing them as CLI flags leads to
`--strict --fail-closed --allow-approximate --expand-templates …` — a matrix nobody can hold in
their head, with undefined interactions, and no record of what was chosen.

The `triggers` field is what makes this better than flags rather than merely different: a
decision is raised only if the document reaches it. A Cedar policy with no decimals and no
attribute access asks nothing.

The durable artifact is a **decision profile** — an org answers once, replays across every
conversion, and can later answer "why was this policy converted this way?". For access control
that provenance is worth more than the convenience.

**What is deliberately NOT a decision**: correctness requirements. The Cedar combining
encoding (outer deny-unless-permit over inner deny-overrides) is not offered as a choice,
because the alternatives are simply wrong — offering them would be offering the user a way to
silently disable every `forbid` in their policy. A decision point is where a *reasonable person
could differ*, not where one answer is a bug.

---

## acal-web-is-stateless (July 2026) (→ ADR-0006)

The planned web UI (FastAPI + Jinja2 + HTMX) persists nothing. Policies and decision profiles
are uploaded and downloaded; neither is stored server-side. No database.

**WHY**: Two reasons, and the second is the real one.

Deployment: no DB means one process, `pip install` + `uvicorn`, ~60MB resident — it runs on a
Pi or a $5 VPS, which was a stated requirement.

Security: the documents this tool handles are **customers' authorization rules**. They describe
exactly who can reach what. A server that never stores them cannot leak them, and that property
is far cheaper to design in at the first commit than to retrofit after someone asks where their
policies are kept.

Stack rationale: FastAPI because the endpoint the web form POSTs to *is* the batch API,
auto-documented — the batch story falls out of the UI work rather than being a second parallel
implementation. HTMX because it is one script tag: no npm, no bundler, no Node in the deploy
path. Pyodide/WASM was considered and rejected — `cedarpy` is a Rust extension and Pyodide
cannot load arbitrary compiled wheels. Streamlit was rejected for ~300MB of dependencies and no
usable API.

---

## presence-semantics-must-be-explicit (July 2026) (→ ADR-0003)

Every reader emits `MustBePresent` **explicitly** on every `AttributeDesignator` it
synthesizes, set to whatever reproduces the **source language's real runtime behaviour**.
Never omit it and never silently harden it. Where the faithful value means the policy can fail
open, that is reported as a fidelity note; `--fail-closed` offers the hardened variant as a
deliberate, declared deviation.

**WHY**: Three readers, three different behaviours, only one of them defensible.

- **XACML** carries `MustBePresent` from the source — correct: the author decided.
- **ALFA** *omitted it entirely*, so the converted policy's behaviour fell back to an ACAL
  schema default that reflects nothing ALFA meant. Every ALFA-converted deny rule referencing
  an attribute the PDP does not supply could fail open, silently, with no diagnostic.
- **Cedar** was going to be hardened to `MustBePresent: true` on the reasoning that a `forbid`
  with a missing attribute should deny. Asking Cedar's own evaluator killed that: Cedar
  **skips** a policy it cannot evaluate, so the `forbid` does not fire and the decision is
  **Allow**. Cedar fails open. `true` would have been *safer than Cedar* — and therefore a
  different policy.

The line that resolves it: **a converter that changes decisions is not a converter.** Fidelity
is the job. Cedar's compensating control (its schema validator, which catches missing
attributes at authoring time) does not exist on the ACAL side, so the hazard is real — but the
answer is to *report* it, and to offer `--fail-closed` for users who want hardening, not to
impose a decision change on everyone by default.

One exception, and it is not a hole: inside a `has` operand `MustBePresent` stays `false` even
under `--fail-closed`, because "is this attribute present?" is exactly what `has` asks.

The general rule this replaces: presence semantics were never stated anywhere, so each reader
improvised. Improvising a fail-open in an access-control converter is how you ship a hole.
(→ find-based-readers-drop-what-they-do-not-ask-for)

---

## datatype-resolution-ladder (July 2026) (→ ADR-0005)

Source datatypes and extension functions resolve through a three-step ladder, defined per
dialect in the `datatypes:` section of `capabilities/<dialect>.yaml`:

1. a **built-in direct mapping** exists → proceed (exact);
2. else a **datamap entry** exists → proceed; if `fidelity: approximate`, warn (b), error under
   `--strict`;
3. else → **hard error** (c), and the message names the missing entry.

**WHY**: Datatype mismatch is the recurring headache across every spoke, and the two obvious
policies are both wrong. Hard-erroring on every unmapped type makes the tool unusable — Cedar's
`decimal`, `ipaddr` and `datetime` are common, and refusing them refuses most real policies.
Best-effort mapping is worse: a near-miss on a comparison operator silently changes who gets
access. Cedar `decimal` is fixed-point to 4 places and ACAL `double` is IEEE-754 binary float,
so a comparison at a precision boundary decides differently — in an authorization policy, that
means someone gets in who should not.

The ladder makes the unmapped case *actionable* rather than terminal: the error names the one
YAML entry that would fix it. `acal_type: null` in a shipped map is a deliberate refusal to
guess, not an absence of thought — Cedar's `ipaddr` is null because mapping `isInRange` onto
string comparison would turn a subnet check into a text match that fails open.

This also fixes an existing blind spot: the XACML reader remaps datatypes by regex passthrough
(`XMLSchema#foo` → `acal:data-type:foo`) and will happily emit an ACAL datatype that does not
exist, unchecked. Retrofitting XACML and ALFA onto the ladder is follow-up work.

---

## acal-is-a-hub-not-a-xacml-dialect (July 2026) (→ ADR-0001)

**The hub is ACAL itself, in every serialization it has or will have** — today XACML 4.0
(XML), YACAL (YAML), JACAL (JSON); tomorrow any further ACAL version or encoding, which joins
the hub by definition rather than by review.

**Everything else is a spoke, permanently.** XACML 2.0, XACML 3.0, ALFA, Cedar, AWS IAM,
Rego. Lineage confers nothing: XACML 1–3 are spokes, not "earlier hub." ACAL is a new,
independent endpoint that happens to have an XML serialization — it is not a dialect of XACML,
and the XML serialization being *called* XACML 4.0 is an accident of naming that has already
misled this codebase once.

Capability matrices hang off **dialects**, not languages; native dialects have no matrix at
all.

The frame is stated for future contributors in [`CLAUDE.md`](../CLAUDE.md), because it must be
read before designing anything, not discovered afterwards.

**WHY**: The registry originally had one `xacml` entry spanning 2.0–4.0, marked foreign. That
forced a single capability matrix to answer for three languages that differ enormously, and it
answered wrong: it asserted XACML "cannot express SharedVariableDefinition", which is true of
3.0 and false of 4.0 — the reader parses `<Bundle><SharedVariableDefinition>` natively. Since
the matrix is meant to be the export tool's precondition gate, an export tool built on it would
have refused to emit something it can emit perfectly well.

The code already believed the hub model before the registry did: `_remap` is False for V4_0
precisely because 4.0 identifiers are *already* ACAL URNs. The registry was the thing lagging.

Consequence worth stating plainly: **XACML 4.0 output is serialization, not export.** A
`writers/xacml.py` belongs beside the YACAL and JACAL writers. (→ xacml-writer-is-not-blocked)

---

## xacml-writer-is-not-blocked (July 2026)

An XACML 4.0 writer is not blocked by Saxon EE licensing, and is not part of the hard
`acal-export` problem.

**WHY**: The expressiveness doc claimed XACML output was blocked because the toolchain for
authoritative XML generation (Saxon EE) is commercially licensed. That is the same conflation
this project already caught once for *reading* (→ xml-parsing-vs-xml-schema-validation): Saxon
EE is required to **validate** XML against XSD 1.1, not to **write** it. Generating XACML 4.0
XML is `ElementTree`, exactly as parsing it is.

Two payoffs make this worth doing early: it enables `XACML 4.0 → YACAL → XACML 4.0` round-trip
tests, which are the strongest correctness check available to this codebase and are currently
impossible to write; and it closes GitHub issue #1 (XACML 3.0 → XACML 4.0), which is just
import-a-spoke then serialize-the-hub, and was wrongly believed to depend on the export tool.

---

## unconverted-constructs-raise-they-do-not-vanish (July 2026) (→ ADR-0002)

Every `find()`-based builder in a reader carries an explicit known-children allowlist and
raises `XACMLUnsupportedFeatureError` on anything outside it — including valid constructs that
are simply not implemented yet.

**WHY**: A reader assembled from targeted `find()` / `findall()` calls silently ignores every
element nobody asked for. That is not a hypothetical: `_rule()` never read `<Target>`, so a
Rule's Target was dropped in every XACML version and a rule scoped to doctors converted into a
rule permitting **everyone**. `_result()` was likewise dropping Obligations, AssociatedAdvice,
Attributes, and PolicyIdentifierList — an obligation lost from a Result is an enforcement
requirement the PEP never sees.

The allowlist is the only thing that turns "we forgot to handle X" from a wrong answer into an
error message. Raising on the *unimplemented* (not merely the invalid) is the deliberate part:
a user who hits it files a bug; a user who does not hit it gets a policy that means something
other than what they wrote. (→ find-based-readers-drop-what-they-do-not-ask-for)

## capability-matrix-is-the-delta-list (July 2026) (→ ADR-0005)

Each non-native source language gets a machine-readable capability matrix at
`acal-core/capabilities/<lang>.yaml`, keyed by **ACAL feature** (not by source construct),
declaring which ACAL features that language can express. It is authored in Phase 3 of
`/import-model`, before any reader code exists.

**WHY**: The plan for the eventual ACAL *export* tool was to audit each language for what it
can and cannot export, and write the result down as prose. Prose cannot gate an export tool,
so the audit would have been redone — a third time, after the reader and the doc — when
export was finally built, and by then the three would have drifted.

Keying by ACAL feature rather than source construct is the whole point. "What does this
source construct become in ACAL?" is the *import* question, and the reader's own code already
answers it. "What can this language say *about* ACAL?" is the *export* question, and nothing
in the codebase answers it — yet three separate consumers need it: the reader (warn vs.
error), `acal-explain` (report what a target language could never express), and the future
export tool (its precondition gate). Authoring it once per language is what makes export
tractable later; auditing three times in three places is what makes it not.

---

## acal-explain-reads-every-source-language (July 2026)

`acal-explain` accepts every format `acal-core` can read, converts non-native input in
memory, and never writes a policy document. Supersedes (→ acal-explain-acal-only-input).

**WHY**: The user asked for explain to "not export a file, simply explain." The old design
forced anyone with an ALFA policy to run `acal-convert` first and materialize a `.yaml` they
did not want, purely to satisfy a restriction at the CLI layer — `acal_core.readers.load()`
had supported ALFA the whole time. Explaining a policy and producing an ACAL artifact are
different jobs; `acal-convert` is the tool for the second one. Making explain refuse a file
it was perfectly capable of reading served no user.

The two jobs stay separate in the code: explain writes only its explanation, and the
conversion exists solely in memory for the duration of the call.

---

## conversion-report-never-enters-the-document (July 2026) (→ ADR-0004)

`load_with_report(path, fmt) -> (doc, ConversionReport)` returns import-fidelity information
*beside* the neutral document. Provenance, source language, and lossy-mapping notes are never
written into the document itself.

**WHY**: To report what an import lost, that information has to reach the caller. The obvious
design — stamp a `SourceLanguage` / conversion-report key into the ACAL document so it
survives any pipeline — would make `acal-convert` emit documents that **fail our own
validators**: the ACAL schemas set `additionalProperties` / `unevaluatedProperties` to false
in several places, so an extra key is a structural violation. A converter whose output its
sibling validator rejects is worse than one that reports less.

The accepted cost is that fidelity is only available when explain performs the import itself;
a YACAL file converted in an earlier process has no memory of its source. That is honest —
the alternative is a claim we cannot substantiate. Carrying provenance properly requires a
spec extension point, which is on the roadmap, not a workaround.

---

## central-language-registry (July 2026)

Every policy language is declared exactly once, in `acal-core/src/acal_core/languages.py`.
Format detection, reader dispatch, writer dispatch, and both CLIs' `--from` / `--to` choices
are all derived from it. Adding a language is one registry entry.

**WHY**: A format was previously declared in five places (`_VALID_FORMATS`, `_EXT_TO_FORMAT`,
the `load()` dispatch, and a hand-written `click.Choice` in each of the two CLIs). Five
declarations of one fact is four opportunities for them to disagree, and with Cedar and IAM
queued that number was about to grow. Parity tests in each tool's suite now fail if a CLI's
choices diverge from the registry, so the drift cannot return silently.

---

## notice-id-is-a-concept-identifier (July 2026)

A `NoticeExpression`/`Notice` `Id` in the ACAL spec is a **concept** identifier, not an instance identifier: it names *what the obligation means and how the PEP must process it*. It is therefore **not** required to be unique within a Policy, Rule, or Result — the same `Id` may appear repeatedly with different `AttributeAssignment`s.

**WHY**: ACAL's `Id` properties are deliberately non-uniform. `PolicyId` is an instance identifier (must be unique); attribute `Id`, `FunctionId`, and notice `Id` are concept identifiers (repeats are legal and meaningful). The pull toward "every property named `Id` should be unique" is intuitive and wrong, and it was acted on once (spec commit 851ebc9) before Steven Legg caught it.

Requiring uniqueness forces the obligation's *semantics* out of the `Id` and into an overloaded `AttributeAssignment` (`action = send-mail`), which breaks every preexisting XACML 3.0 obligation definition — their published `ObligationId` URIs become decorative, and the `Id` degrades into a per-occurrence instance tag nobody needs. It also blocks legitimate patterns: emitting `add-history` twice with different parameters, or emitting the same obligation from two rules that permit access for two different reasons.

It is additionally inconsistent with the evaluation model. Spec §8.16 passes notices *up* the tree from rule → policy → Result, so two rules emitting the same-Id obligation makes a unique-by-Id `ResultType` literally unrepresentable — and no de-duplication or merging rule exists anywhere to reconcile it.

---

## alfa-function-map-sources-from-system-alfa (July 2026)

`_NAMED_FUNCTION_MAP` in the ALFA reader is sourced exhaustively from `system.alfa` (the canonical Axiomatics PDP 7.x runtime declaration file), converting the XACML version prefix (`xacml:1.0`, `xacml:2.0`, `xacml:3.0`) uniformly to `acal:1.0`.

**WHY**: The prior map covered ~20 functions and was manually curated, producing "Unknown ALFA function" warnings on real Axiomatics policies (date comparisons, bag introspection, type conversions, regex matches). `system.alfa` is the authoritative short-name → URN registry for the Axiomatics dialect — all functions a PDP user can call are declared there. Sourcing from it eliminates the completeness problem and ties the map to the same reference that Axiomatics tools use.

---

## alfa-bag-overloading-private-marker (July 2026)

Bag-typed attributes signal their multiplicity to `cmp_expr` via a private `"_bag": True` key on the outer `{"AttributeDesignator": {...}}` wrapper dict. `cmp_expr` consumes the marker and strips it before returning in all code paths.

**WHY**: `_resolve_attr_path` returns a plain dict; changing it to return a tuple `(dict, is_bag)` would require updating every caller in the transformer. The `_bag` key on the outer wrapper is invisible to downstream consumers (neutral dict writers, `acal-explain` analyzer) because they access the inner `"AttributeDesignator"` key, not the wrapper. The only other option — reverse-looking up from the symbol table inside `cmp_expr` by AttributeId — would require iterating all symbol table entries and comparing full URNs, which is fragile if the URN was synthesized from the namespace. The private marker is cheap, local, and always stripped at the boundary.

---

## alfa-bag-type-is-cardinality-not-datatype (July 2026)

When an ALFA attribute block declares `type = bag`, the string `"bag"` sets `is_bag = True` and `attr_type` is cleared to `""`. A subsequent `datatype = <type>` clause then sets the element type.

**WHY**: `"bag"` is a cardinality modifier in Axiomatics ALFA, not an XSD or ACAL data type. Storing `DataType = "bag"` in the AttributeDesignator would produce an invalid neutral dict (no PDP recognises `"bag"` as a type) and would cause the `_TYPE_IS_IN_MAP` lookup to return `None`, silently falling back to the wrong function. The correct pattern matches what Axiomatics uses in real attribute files: `type = bag` + `datatype = integer` for a typed multi-valued integer attribute.

---

## acal-explain-acal-only-input (June 2026) — SUPERSEDED July 2026

**Superseded by (→ acal-explain-reads-every-source-language). Kept because the reasoning
was sound and only one premise turned out to be wrong.**

`acal-explain` accepts only XACML, YACAL, and JACAL as input — ALFA is explicitly rejected with a message directing the user to convert first.

**WHY**: `acal-explain` explains what an ACAL policy is expressing. ALFA is a source language that gets *converted into* ACAL; explaining an ALFA file directly would require running the ALFA reader and then explaining the resulting ACAL neutral dict anyway. The tool's purpose is ACAL-family insight, not ALFA parsing. Making the rejection explicit (with a `acal-convert … | acal-explain` hint) is clearer than silently accepting ALFA and potentially confusing users who expected ALFA-level semantics.

**What was wrong with it**: the argument "you'd just run the reader and explain the neutral
dict anyway" is *correct*, and is precisely the reason to accept ALFA rather than reject it —
the work is identical either way, so the only thing the rejection bought was making the user
do it by hand and leave a `.yaml` on disk they never wanted. The premise that the user wanted
an ACAL artifact was never checked.

---

## acal-explain-two-call-llm (June 2026)

`acal-explain` makes two separate LLM calls: (1) structural summary (what the policy does, given the full neutral dict as JSON), (2) observations/nuances (given only the structured analysis findings — shadowed rules, default-deny gaps, obligation gaps, unresolved attrs).

**WHY**: A single call mixing "explain what it does" and "find the problems" produces unfocused output — the model tends to either narrate the JSON or make generic observations without grounding. Separating the calls keeps each prompt tightly scoped. The second call receives pre-computed structured findings rather than raw JSON, which prevents the model from hallucinating issues that aren't there and keeps the observations section factual and specific.

---

## acal-explain-config-file (June 2026)

LLM provider, model string, API credentials, and output format defaults are configured via `~/.config/acal-explain/config.toml` with env var overrides (`ACAL_EXPLAIN_MODEL`, `ACAL_EXPLAIN_API_KEY`, `ACAL_EXPLAIN_API_BASE`). No model versions are hardcoded anywhere in the tool.

**WHY**: This is an open-source tool; users run it with their own credentials against their own preferred provider. Hardcoding model strings would make the tool go stale as new versions drop. The `~/.config/acal-explain/` path follows the XDG convention already established by `~/.cache/acal-validator/`. litellm's `provider/model` convention (e.g. `anthropic/claude-sonnet-4-6`, `ollama/llama3`) is used directly so users can switch providers without changing anything except the config file.

---

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

## xacml-converter-yacal-target (June 2026)

The `xacml-converter` targets YACAL (YAML) output, not JACAL (JSON), even though Issue #2 specifically requested JACAL.

**Why:** YACAL aligns with the `yacal-validator` tool already in the repo, giving users an immediate validate-after-convert workflow. The internal representation is a Python dict; serialising to JSON instead of YAML is a one-line change if JACAL output is needed later, so there is no technical cost to this choice.

---

## xacml-converter-pure-python (June 2026)

The XACML → YACAL converter is implemented in pure Python using `xml.etree.ElementTree` (stdlib), with no XSLT, no Java, and no Saxon dependency.

**Why:** The issue author (Cyril Dangerville) suggested XSLT because XACML is XML. The prior lesson about Saxon EE licensing made Java/XSLT seem necessary, but that concern only applies to XML *schema validation* (checking input against XSD 1.1). A *converter* only needs to *parse* XML elements and attributes, which Python's stdlib handles for any well-formed XML regardless of version. Pure Python keeps the tool in the same ecosystem as `yacal-validator`, enabling direct pipeline integration (`--validate` flag calls yacal-validator after conversion), and eliminates a Java runtime dependency. (→ saxon-he-schema-not-licensed)

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
