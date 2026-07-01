# acal-explain

Generates plain-English explanations of ACAL policy documents, with observations about completeness, rule interactions, and potential issues.

`acal-explain` accepts ACAL 1.0 policies in any of the three ACAL serialization formats — XACML 2.0–4.0 (`.xml`), YACAL (`.yaml`), or JACAL (`.json`) — and produces a structured explanation using an LLM of your choice via [litellm](https://github.com/BerriAI/litellm).

ALFA policies must first be converted to YACAL or JACAL using `acal-convert` (see [ALFA input](#alfa-input)).

---

## Specification basis

This tool operates on the **ACAL 1.0** neutral data model. ACAL 1.0 is aligned with the XACML 4.0 specification:

- Combining algorithm URNs: `urn:oasis:names:tc:acal:1.0:combining-algorithm:*`
- Attribute category URNs: `urn:oasis:names:tc:acal:1.0:attribute-category:*` and `urn:oasis:names:tc:acal:1.0:subject-category:*`
- Data type URNs: `urn:oasis:names:tc:acal:1.0:data-type:*`
- Function URNs: `urn:oasis:names:tc:acal:1.0:function:*`

XACML 2.0 and 3.0 inputs are remapped to ACAL 1.0 identifiers on load. XACML 4.0 inputs use ACAL 1.0 URNs natively.

For ALFA policies: ALFA (Abbreviated Language for Authorization) was submitted to OASIS as a contribution to the XACML TC but was never published as a formally versioned standard. `acal-convert --from alfa` is validated against the Axiomatics PDP 7.x ALFA dialect, which is the de-facto reference implementation. It includes extensions beyond the original OASIS submission — notably the `target clause` two-word keyword form, `apply` declared inside policy/policyset bodies, `and`/`or` as keyword operators, and `system.alfa`-style runtime declarations (`ruleCombinator`, `type`, `category`, `function`, `infix`). See [ALFA input](#alfa-input) for how to convert ALFA before using `acal-explain`.

---

## Installation

```bash
git clone https://github.com/acal-community/tools
cd tools/acal-explain
pip install -e .
```

After installation, `acal-explain` is on your `PATH`.

**Dependencies installed automatically:**

| Package | Purpose |
|---------|---------|
| `acal-core` | Policy loading and format detection |
| `click` | CLI framework |
| `litellm` | LLM provider abstraction |

---

## Configuration

`acal-explain` requires an LLM to generate explanations. Configure the provider and credentials before first use.

### Config file

Create `~/.config/acal-explain/config.toml`:

```toml
[llm]
model = "anthropic/claude-sonnet-4-6"   # litellm provider/model string
api_key = "sk-ant-..."                  # optional — prefer ACAL_EXPLAIN_API_KEY env var

[output]
format = "text"                         # default output format: text | markdown | json
```

### Environment variables

Environment variables take precedence over the config file:

| Variable | Purpose |
|----------|---------|
| `ACAL_EXPLAIN_MODEL` | litellm model string (e.g. `anthropic/claude-sonnet-4-6`) |
| `ACAL_EXPLAIN_API_KEY` | API key for the configured provider |
| `ACAL_EXPLAIN_API_BASE` | Custom endpoint URL (for Ollama, Azure, proxies) |

### Provider model strings

litellm uses `provider/model` strings. Common examples:

```toml
# Anthropic
model = "anthropic/claude-sonnet-4-6"
model = "anthropic/claude-opus-4-8"
model = "anthropic/claude-haiku-4-5"

# OpenAI
model = "openai/gpt-4o"
model = "openai/o3"

# xAI (Grok)
model = "xai/grok-3"
model = "xai/grok-3-mini"

# Google
model = "google/gemini-2.0-flash"
model = "google/gemini-2.5-pro"

# Ollama (local — no API key required)
model = "ollama/llama3"
model = "ollama/mistral"
model = "ollama/phi3"
```

For Ollama, also set the base URL if not running on the default port:

```toml
[llm]
model = "ollama/llama3"
api_base = "http://localhost:11434"
```

---

## Usage

```
acal-explain [OPTIONS] FILE
```

### Options

| Option | Description |
|--------|-------------|
| `FILE` | Path to the policy file to explain. Required. |
| `--from FORMAT` | Input format: `xacml`, `yacal`, or `jacal`. Auto-detected from file content if omitted. |
| `--format FORMAT` | Output format: `text`, `markdown`, or `json`. Defaults to config value or `text`. |
| `-o, --output FILE` | Write output to a file instead of stdout. |
| `--model MODEL` | litellm model string. Overrides config file and `ACAL_EXPLAIN_MODEL` env var for this run. |

---

## Examples

### Explain a YACAL policy (plain text)

```bash
acal-explain my-policy.yaml
```

Output:

```
This policy governs access to the document management system. It uses a
deny-overrides combining algorithm, which means any matching Deny rule will
override any matching Permit rule, regardless of rule order.

The single rule "AllowEditors" permits access when the subject's role attribute
equals "editor". There are no target constraints on the policy itself, so the
combining algorithm evaluates against all incoming requests. When no rule
matches — for example, when a request arrives from a subject without a role
attribute — the outcome is NotApplicable, meaning the PDP will defer to any
enclosing policy set.

- The Permit effect has no associated obligation or advice. If audit logging is
  required on access grants, add an obligation to this rule or to the enclosing
  policy.
- The "role" attribute has no declared category. At runtime, the PDP may reject
  the attribute designator if it cannot infer the subject category. Declare the
  attribute explicitly or use the canonical form
  Attributes.<subject-category>.<attribute-id>.
```

---

### Explain as Markdown (suitable for documentation or GitHub)

```bash
acal-explain --format markdown my-policy.yaml
```

Output:

```markdown
# Policy Explanation: `com.example.DocumentAccess`

## Summary

This policy governs access to the document management system...

## Observations

- The Permit effect has no associated obligation or advice...
- The "role" attribute has no declared category...
```

---

### Explain as JSON (suitable for pipelines and tooling)

```bash
acal-explain --format json my-policy.yaml
```

Output:

```json
{
  "policy_id": "com.example.DocumentAccess",
  "format": "yacal",
  "rule_count": 1,
  "permit_count": 1,
  "deny_count": 0,
  "is_default_deny": false,
  "default_effect": "NotApplicable",
  "shadowed_rules": [],
  "obligation_gaps": ["Permit"],
  "unresolved_attrs": ["role"],
  "summary": "This policy governs access to the document management system...",
  "observations": "- The Permit effect has no associated obligation or advice...\n- The \"role\" attribute has no declared category..."
}
```

---

### Explain an XACML policy

```bash
acal-explain --from xacml legacy-policy.xml
```

XACML 2.0, 3.0, and 4.0 are all accepted. Identifiers are remapped to ACAL 1.0 URNs before analysis.

---

### Write output to a file

```bash
acal-explain --format markdown -o explanation.md my-policy.yaml
```

---

### Use a specific model for one run

```bash
acal-explain --model openai/gpt-4o my-policy.yaml
```

This overrides both the config file and the `ACAL_EXPLAIN_MODEL` environment variable for this invocation only.

---

### Use a local Ollama model (no API key required)

```bash
ACAL_EXPLAIN_MODEL=ollama/llama3 ACAL_EXPLAIN_API_BASE=http://localhost:11434 acal-explain my-policy.yaml
```

Or set these permanently in `~/.config/acal-explain/config.toml`.

---

### Explain a JACAL policy and pipe to a pager

```bash
acal-explain --format markdown policy.json | less
```

---

## ALFA input

ALFA (Abbreviated Language for Authorization) is a concise DSL for authoring XACML/ACAL policies, used by the Axiomatics PDP toolchain. `acal-explain` does not read ALFA directly — convert it first:

```bash
# Convert ALFA to YACAL, then explain
acal-convert my-policy.alfa --to yacal -o my-policy.yaml
acal-explain my-policy.yaml

# Or pipe directly (Linux/macOS)
acal-convert my-policy.alfa --to yacal | acal-explain /dev/stdin --from yacal
```

For ALFA files that reference attribute registries or standard include files, pass `--include` to `acal-convert`:

```bash
acal-convert my-policy.alfa \
  --include standard-attributes.alfa \
  --include attributes.alfa \
  --to yacal | acal-explain /dev/stdin --from yacal
```

---

## How it works

`acal-explain` makes two LLM calls per invocation:

1. **Structural summary** — the full policy (as a JSON-serialized ACAL neutral dict) plus metadata about rule count and combining algorithm. The LLM explains what the policy governs and how the rules interact.

2. **Observations** — the pre-computed structural analysis findings (shadowed rules, default-deny detection, obligation gaps, unresolved attribute references). The LLM translates these into specific, actionable observations for a reviewer.

Separating the calls keeps each prompt focused: the first answers "what does this do?", the second answers "what should a reviewer be concerned about?". The observations call never receives the raw policy JSON, which prevents the model from narrating the structure instead of commenting on it.

### Structural analysis (deterministic, no LLM)

Before any LLM call, `acal-explain` computes:

| Analysis | What it detects |
|----------|----------------|
| **Default effect** | What happens when no rule matches, given the combining algorithm (`Deny` for `deny-unless-permit`, `NotApplicable` for `deny-overrides`, etc.) |
| **Default-deny** | Whether the policy is secure by default (true only for `deny-unless-permit`) |
| **Shadowed rules** | Rules that can never be reached: for `first-applicable`, any rule after an unconditional rule; for `deny-overrides`/`permit-overrides`, rules after an unconditional dominant-effect rule |
| **Obligation gaps** | Effects (`Permit` or `Deny`) that have matching rules but no associated obligation or advice at any level |
| **Unresolved attributes** | `AttributeDesignator` entries with no `Category` — these will fail at PDP evaluation time if the category cannot be inferred |

---

## Development

Run the test suite from the `acal-explain/` directory:

```bash
pip install -e ".[dev]"
pytest
```

Tests cover the structural analyzer (no LLM required) and the CLI (LLM calls are mocked). No API key or network access is needed to run the test suite.
