# acal-converter

Converts policy documents between ACAL serialization formats, and reads legacy XACML policies into ACAL.

## Supported conversions

| Input | Output | Direction | Notes |
|---|---|---|---|
| YACAL (`.yaml`) | JACAL (`.json`) | ↔ bidirectional | Lossless round-trip |
| JACAL (`.json`) | YACAL (`.yaml`) | ↔ bidirectional | Lossless round-trip |
| XACML 2.0–4.0 (`.xml`) | YACAL or JACAL | → input only | Version detected from namespace (`XACMLVersion` enum); V2.0/V3.0 require identifier remapping |

YACAL and JACAL represent the same ACAL data model — one in YAML, one in JSON. Conversion between them is always lossless.

XACML is input-only. See [docs/policy-language-expressiveness.md](docs/policy-language-expressiveness.md) for the rationale.

---

## Usage

### Install

```bash
git clone https://github.com/acal-community/tools
cd tools/acal-converter
pip install -e .
```

After installation, `acal-convert` is on your `PATH`:

```bash
# Default (lenient)
acal-convert --to jacal my-policy.yaml

# Strict mode (recommended for security policies)
acal-convert --to jacal --strict my-policy.yaml
```

### CLI reference

```
acal-convert [OPTIONS] FILE
```

| Option | Description |
|---|---|
| `--from FORMAT` | Input format: `xacml`, `yacal`, or `jacal`. Auto-detected from file content if omitted. |
| `--to FORMAT` | **Required.** Output format: `yacal` or `jacal`. |
| `--strict` / `--no-strict` | Whether to treat non-semantic deprecations (e.g. `IncludeInResult`) as errors. Default: `--no-strict`. |
| `-o FILE`, `--output FILE` | Write output to `FILE` (default: stdout) |
| `--validate` | Validate the output with the appropriate ACAL validator (requires `-o`) |
| `--help` | Show help and exit |

### Format auto-detection

The input format is detected from the **file content** (not the extension) by inspecting the first non-whitespace byte:

| Leading byte | Detected format |
|---|---|
| `<` | XACML (XML) |
| `{` | JACAL (JSON) |
| anything else | YACAL (YAML) |

A UTF-8 BOM is stripped before inspection. The extension is used only as a fallback when the file is empty. This means the tool works correctly on files with wrong or missing extensions, and is ready to accept content from an HTTP request body without a filename.

Override detection at any time with `--from`.

---

## Examples

### YACAL → JACAL

```bash
acal-convert --to jacal policy.yaml
```

```json
{
  "Policy": {
    "PolicyId": "urn:example:guide:ex01",
    "Version": "1.0",
    "CombiningAlgId": "urn:oasis:names:tc:acal:1.0:combining-algorithm:deny-unless-permit",
    "CombinerInput": [
      {
        "Rule": {
          "Id": "rule-doctor-read",
          "Effect": "Permit"
        }
      }
    ]
  }
}
```

### JACAL → YACAL

```bash
acal-convert --to yacal policy.json
```

```yaml
Policy:
  PolicyId: urn:example:guide:ex01
  Version: '1.0'
  CombiningAlgId: urn:oasis:names:tc:acal:1.0:combining-algorithm:deny-unless-permit
  CombinerInput:
  - Rule:
      Id: rule-doctor-read
      Effect: Permit
```

### XACML 3.0 → JACAL

```bash
acal-convert --to jacal legacy-policy.xml
```

The converter handles the full structural translation from XACML 3.0:

| XACML 3.0 | ACAL 1.0 |
|---|---|
| `<PolicySet>` | `Policy:` with nested `CombinerInput` |
| `<AnyOf>/<AllOf>/<Match>` | `Apply:` boolean expression tree |
| `<ObligationExpression>` | `NoticeExpression:` with `IsObligation: true` |
| `<AdviceExpression>` | `NoticeExpression:` (no `IsObligation`) |
| `<Rule RuleId="...">` | `Rule: {Id: ...}` |
| `<AttributeValue>` | `Value:` |
| XACML URNs (`urn:oasis:names:tc:xacml:…`) | ACAL URNs (`urn:oasis:names:tc:acal:1.0:…`) |
| XSD data types (`XMLSchema#string`) | ACAL data types (`acal:1.0:data-type:string`) |

XACML 4.0 already uses ACAL 1.0 URNs internally, so only structural mapping is needed.

### Convert and validate

```bash
acal-convert --to jacal -o out.json legacy-policy.xml --validate
```

`--validate` requires `-o` (output file) because it invokes `jacal-validate` or `yacal-validate` on the written file. Validation is skipped with a warning if the output goes to stdout.

---

## Conversion integrity: no silent drops

**This converter never silently drops data.** Every element in the input document is either:

1. **Fully converted** to its ACAL equivalent, or
2. **Explicitly failed** with `XACMLUnsupportedFeatureError`.

There is no third option. A silent drop — where the converter ignores an element and produces output that looks valid but is semantically different from the input — is treated as a defect. This requirement is stricter than typical format converters precisely because the output is access-control policy: a converted policy that silently omits a constraint could grant access that the original policy denied.

The two categories of failure are:

- **Removed constructs**: elements or attributes that existed in XACML 2.0/3.0 but were explicitly removed in ACAL 1.0 because their semantics were unsound or redundant. These raise with a message explaining the removal and offering alternatives.
- **Unimplemented constructs**: elements that are valid XACML but whose conversion is not yet implemented in this tool. These also raise, with a message identifying the element and inviting a bug report or TC contact.

Both categories use the same error type. Callers cannot accidentally succeed on partial conversions.

## Unsupported XACML constructs

When the converter encounters any of the following it **aborts with an error** (`XACMLUnsupportedFeatureError`, a subclass of `ValueError`). The error message identifies the construct and, where applicable, offers concrete alternatives.

### Removed in ACAL 1.0 (construct no longer exists)

| XACML construct | Message summary |
|---|---|
| `<CombinerParameters>` | Removed in ACAL 1.0. Contact the XACML TC. Redesign without CombinerParameters. |
| `<RuleCombinerParameters>` | Same as above. |
| `<PolicyCombinerParameters>` | Same as above. |
| `EarliestVersion` on `<PolicyIdReference>` | Use an explicit `Version`, a version pattern, or a version-encoded `PolicyId` URI. |
| `LatestVersion` on `<PolicyIdReference>` | Same as above. |
| `<XPathVersion>` in `<PolicyDefaults>` | XPath profile conversion not yet implemented. Remove element or contact the XACML TC. |

### Not yet implemented (construct is valid, conversion is pending)

| XACML construct | Context | Message summary |
|---|---|---|
| Any unrecognised expression element | Inside `<Condition>`, `<Apply>`, etc. | Element name is not a known ACAL expression construct. |
| Any unrecognised child of `<Policy>` | Direct policy child | Element name is not a recognised child of `<Policy>`. |
| Any unrecognised child of `<PolicySet>` | Direct policyset child | Element name is not a recognised child of `<PolicySet>`. |
| `<Attributes>` in XACML 2.0/3.0 `<Request>` | Request body | XACML 2.0/3.0 request body conversion is not yet implemented; use XACML 4.0 `<RequestEntity>` structure. |

### Warnings (conversion continues)

The `--strict` / `--no-strict` flag controls behavior for non-semantic deprecations:

- `--strict`: All such cases raise `XACMLUnsupportedFeatureError`
- `--no-strict` (default): Emit a warning for harmless constructs like `IncludeInResult`

| XACML construct | Behaviour with --no-strict | Behaviour with --strict |
|---|---|---|
| `IncludeInResult="true"` on request `<Attribute>` | Warning (ignored — only affects response formatting) | Error |

See [docs/policy-language-expressiveness.md](docs/policy-language-expressiveness.md) for the full rationale behind these decisions.

The converter assumes the input is a valid XACML document and does not validate it against the XACML XSD schemas.

---

## Development

```bash
pip install -e ".[dev]"
pytest
```

The test suite (`tests/test_converter.py`) covers:

- YACAL reader: CommentedMap is stripped to plain dict
- JACAL reader: standard JSON loading
- Content-based format detection (leading byte, BOM handling, empty-file fallback)
- `detect_format_from_bytes` (service/HTTP-body use case, no filename)
- YACAL → JACAL correctness against paired fixtures
- JACAL → YACAL correctness against paired fixtures
- Round-trip YACAL → JACAL → YACAL (lossless)
- Round-trip JACAL → YACAL → JACAL (lossless)
- XACML 3.0 → ACAL happy path
- XACML 2.0 structural conversion (target, condition, obligations)
- `XACMLUnsupportedFeatureError` for all removed constructs (CombinerParameters, EarliestVersion, LatestVersion, XPathVersion)
- `XACMLUnsupportedFeatureError` for all unimplemented constructs (unknown expression elements, unknown Policy children, XACML 2.0/3.0 request bodies)
- `IncludeInResult` warning (emitted before the request-body error)
- `XACMLUnsupportedFeatureError` is catchable as `ValueError`
- CLI: auto-detection, `--from` override, `-o` output, error exit codes

---

## Publishing to PyPI

From the `acal-converter/` directory:

```bash
pip install build twine
python -m build
twine upload dist/*
```

Update `version` in `pyproject.toml` before each release.
