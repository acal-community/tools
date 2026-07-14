# xacml-converter

Converts XACML 3.0 and XACML 4.0 XML policy documents to YACAL v1.0 (YAML).

Handles the full structural translation between the XML and YAML policy families:

| XACML (source) | YACAL (output) |
|---|---|
| `<PolicySet>` (3.0 only) | `Policy:` with nested `CombinerInput` |
| `<AnyOf>/<AllOf>/<Match>` (3.0 only) | `Apply:` boolean expression tree |
| `<ObligationExpression>` (3.0) | `NoticeExpression:` with `IsObligation: true` |
| `<AdviceExpression>` (3.0) | `NoticeExpression:` (no `IsObligation`) |
| `<Rule RuleId="...">` | `Rule: {Id: ...}` |
| `<AttributeValue>` | `Value:` |
| `<Target>/<Condition>` (4.0) | direct `Apply:` expression (pass-through) |
| XACML identifier URNs | ACAL 1.0 URNs |
| XSD data types (`XMLSchema#string`) | ACAL data types (`acal:1.0:data-type:string`) |

XACML 4.0 policies already use ACAL 1.0 identifier URNs internally, so only structural mapping is required. XACML 3.0 policies additionally need identifier remapping across functions, data types, attribute categories, and combining algorithms.

---

## Usage

### Option A: run from source (no installation required)

Clone the repo and run from within the `xacml-converter/` directory:

```bash
git clone https://github.com/acal-community/tools
cd tools/xacml-converter
python -m xacml_converter my-policy.xml
```

Install dependencies once with:

```bash
pip install click "ruamel.yaml"
```

A convenience wrapper script is also included so you can use `./xacml-convert` with relative paths:

```bash
./xacml-convert my-policy.xml
```

### Option B: install as a persistent local tool

```bash
git clone https://github.com/acal-community/tools
cd tools/xacml-converter
pip install -e .
```

After installation, `xacml-convert` is on your PATH permanently:

```bash
xacml-convert my-policy.xml
```

### Option C: install from PyPI (once published)

```bash
pip install xacml-converter
xacml-convert my-policy.xml
```

---

## CLI reference

```
xacml-convert [OPTIONS] FILE
```

| Option | Description |
|---|---|
| `-o FILE`, `--output FILE` | Write YACAL output to `FILE` (default: stdout) |
| `--validate` | Run yacal-validator on the converted output (requires `yacal-validator`) |
| `--help` | Show help and exit |

**Exit codes**

| Code | Meaning |
|---|---|
| `0` | Conversion succeeded |
| `1` | Converted output failed yacal-validator (only with `--validate`) |
| `2` | Conversion error (unrecognised namespace, malformed XML, etc.) |

---

## Examples

### XACML 3.0 → YACAL: simple policy

**Input** (`tests/fixtures/xacml3/ex01-simple-policy.xml`):

```xml
<Policy xmlns="urn:oasis:names:tc:xacml:3.0:core:schema:wd-17"
        PolicyId="urn:example:policy:simple-permit"
        Version="1.0"
        RuleCombiningAlgId="urn:oasis:names:tc:xacml:3.0:rule-combining-algorithm:deny-unless-permit">
  <Description>A doctor may read any resource.</Description>
  <Target>
    <AnyOf>
      <AllOf>
        <Match MatchId="urn:oasis:names:tc:xacml:1.0:function:string-equal">
          <AttributeValue DataType="http://www.w3.org/2001/XMLSchema#string">read</AttributeValue>
          <AttributeDesignator
            Category="urn:oasis:names:tc:xacml:3.0:attribute-category:action"
            AttributeId="urn:oasis:names:tc:xacml:1.0:action:action-id"
            DataType="http://www.w3.org/2001/XMLSchema#string"/>
        </Match>
      </AllOf>
    </AnyOf>
  </Target>
  <Rule RuleId="rule-doctor-permit" Effect="Permit">
    <Description>Doctors may read.</Description>
    <Condition>
      <Apply FunctionId="urn:oasis:names:tc:xacml:1.0:function:string-is-in">
        <AttributeValue DataType="http://www.w3.org/2001/XMLSchema#string">doctor</AttributeValue>
        <AttributeDesignator
          Category="urn:oasis:names:tc:xacml:1.0:subject-category:access-subject"
          AttributeId="urn:oasis:names:tc:xacml:1.0:subject:subject-id"
          DataType="http://www.w3.org/2001/XMLSchema#string"
          MustBePresent="true"/>
      </Apply>
    </Condition>
  </Rule>
</Policy>
```

**Command:**

```bash
./xacml-convert tests/fixtures/xacml3/ex01-simple-policy.xml
```

**Output:**

```yaml
Policy:
  PolicyId: urn:example:policy:simple-permit
  Version: '1.0'
  CombiningAlgId: urn:oasis:names:tc:acal:1.0:combining-algorithm:deny-unless-permit
  Description: A doctor may read any resource.
  Target:
    Apply:
      FunctionId: urn:oasis:names:tc:acal:1.0:function:string-equal
      Argument:
      - Value: read
      - AttributeDesignator:
          Category: urn:oasis:names:tc:acal:1.0:attribute-category:action
          AttributeId: urn:oasis:names:tc:acal:1.0:action:action-id
  CombinerInput:
  - Rule:
      Id: rule-doctor-permit
      Effect: Permit
      Description: Doctors may read.
      Condition:
        Apply:
          FunctionId: urn:oasis:names:tc:acal:1.0:function:string-is-in
          Argument:
          - Value: doctor
          - AttributeDesignator:
              Category: urn:oasis:names:tc:acal:1.0:subject-category:access-subject
              AttributeId: urn:oasis:names:tc:acal:1.0:subject:subject-id
              MustBePresent: true
```

Notice what changed:
- `RuleCombiningAlgId` + `urn:oasis:names:tc:xacml:3.0:rule-combining-algorithm:` → `CombiningAlgId` + `urn:oasis:names:tc:acal:1.0:combining-algorithm:`
- `AnyOf/AllOf/Match` → `Apply` with `FunctionId` taken from `MatchId`
- `AttributeValue` → `Value`; `RuleId` → `Id`
- `http://www.w3.org/2001/XMLSchema#string` DataType omitted (it is the ACAL default)
- `MustBePresent="false"` omitted (ACAL default); `MustBePresent="true"` preserved

---

### XACML 3.0 → YACAL: PolicySet with nested policies

**Command:**

```bash
./xacml-convert tests/fixtures/xacml3/ex03-policyset.xml
```

**Output** (abbreviated):

```yaml
Policy:
  PolicyId: urn:example:policyset:medical
  Version: '1.0'
  CombiningAlgId: urn:oasis:names:tc:acal:1.0:combining-algorithm:deny-unless-permit
  Description: Medical data access control.
  CombinerInput:
  - Policy:
      PolicyId: urn:example:policy:read-access
      ...
  - Policy:
      PolicyId: urn:example:policy:write-access
      ...
```

`PolicySet` becomes a `Policy` whose child policies appear in `CombinerInput`. The `PolicySetId` and `PolicyCombiningAlgId` attributes are renamed accordingly.

---

### XACML 4.0 → YACAL

**Command:**

```bash
./xacml-convert tests/fixtures/xacml4/ex04-simple-policy.xml
```

**Output:**

```yaml
Policy:
  PolicyId: urn:example:policy:xacml4-simple
  Version: '1.0'
  CombiningAlgId: urn:oasis:names:tc:acal:1.0:combining-algorithm:deny-unless-permit
  Description: XACML 4.0 simple permit policy with an obligation.
  Target:
    Apply:
      FunctionId: urn:oasis:names:tc:acal:1.0:function:string-is-in
      Argument:
      - Value: read
      - AttributeDesignator:
          Category: urn:oasis:names:tc:acal:1.0:attribute-category:action
          AttributeId: urn:oasis:names:tc:acal:1.0:action:action-id
          MustBePresent: true
  CombinerInput:
  - Rule:
      Id: rule-doctor-permit
      Effect: Permit
      Description: Doctors may read.
      Condition:
        Apply:
          FunctionId: urn:oasis:names:tc:acal:1.0:function:string-is-in
          Argument:
          - Value: doctor
          - AttributeDesignator:
              Category: urn:oasis:names:tc:acal:1.0:subject-category:access-subject
              AttributeId: urn:oasis:names:tc:acal:1.0:subject:subject-id
              MustBePresent: true
  NoticeExpression:
  - Id: urn:example:obligation:log
    IsObligation: true
    AppliesTo: Permit
    AttributeAssignmentExpression:
    - AttributeId: urn:example:attribute:log-message
      Expression:
        Value: Access granted
```

XACML 4.0 identifiers already use ACAL 1.0 URNs, so only the element structure is mapped (e.g. `NoticeExpression` passes through directly).

---

### Save output to a file

```bash
./xacml-convert my-policy.xml -o converted.yaml
```

---

### Convert and validate in one step

If `yacal-validator` is installed, pass `--validate` to pipe the converted output directly through the validator:

```bash
./xacml-convert tests/fixtures/xacml3/ex01-simple-policy.xml --validate
```

```
Policy:
  PolicyId: urn:example:policy:simple-permit
  ...
PASS  YACAL v1.0 (YAML) — tmp1234abcd.yaml
        Constraints: 42/42 evaluated
```

Install yacal-validator with:

```bash
pip install -e ../yacal-validator   # from source
# or
pip install yacal-validator         # from PyPI once published
```

The validator requires its schema cache to be populated on first use:

```bash
yacal-validate --refresh-schemas <any-yacal-file>
```

---

## What is not converted

A small number of XACML constructs have no ACAL 1.0 equivalent and are silently dropped:

| XACML construct | Reason omitted |
|---|---|
| `CombinerParameters` / `RuleCombinerParameters` | Removed in ACAL 1.0 |
| `EarliestVersion` / `LatestVersion` on `PolicyIdReference` | Removed in ACAL 1.0 |
| `IncludeInResult` on request attributes | Removed in ACAL 1.0 |
| `XPathVersion` in `PolicyDefaults` | Handled by XPath profile, not core |

The converter assumes the input is a valid XACML document and does not validate it against the XACML XSD schemas.

---

## Development

```bash
pip install -e ".[dev]"
cd xacml-converter
python -m pytest
```

The test suite (`tests/test_converter.py`) covers:
- Identifier remapping for all XACML 3.0 URN families
- XACML 3.0 → YACAL: simple policy, policy with obligations/advice, PolicySet with nested policies
- XACML 4.0 → YACAL: simple policy with NoticeExpression
- Unknown namespace error handling
- Fixture-level dict equality checks (input XML → expected YAML)

---

## Publishing to PyPI

**One-time setup**

1. Create a free account at [pypi.org](https://pypi.org) and verify your email.
2. Generate an API token: *Account settings → API tokens → Add API token*.
3. Install build tools:
   ```bash
   pip install build twine
   ```

**Build and upload**

From the `xacml-converter/` directory:

```bash
python -m build
twine upload dist/*
```

Twine will prompt for username (`__token__`) and the API token as the password.

**Test on TestPyPI first**

```bash
twine upload --repository testpypi dist/*
pip install --index-url https://test.pypi.org/simple/ xacml-converter
```

**Version bumps**

Update the `version` field in `pyproject.toml` before each new release.
