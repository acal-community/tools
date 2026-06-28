# yacal-validator

Validates YACAL v1.0 (YAML) policy documents against the ACAL normative schemas and constraint catalog.

Validation is two-layer:
1. **Structural** — JSON Schema Draft 2020-12 validates the document shape
2. **Constraints** — the machine-readable constraint catalog enforces higher-order rules (uniqueness, reference integrity, graph acyclicity) that JSON Schema cannot express

XPath and JSONPath profiles are auto-detected from the document content.

---

## Usage

### Option A: run from source (no installation required)

Clone the repo and run directly with Python:

```bash
python -m yacal_validator my-policy.yaml
```

This works as long as the package's dependencies are available. Install them once with:

```bash
pip install click httpx "jsonschema[format-nongpl]" referencing "ruamel.yaml"
```

### Option B: install as a persistent local tool

Install from source in editable mode. After this, the `yacal-validate` command is on your PATH permanently (until you uninstall it).

```bash
git clone https://github.com/oasis-tcs/acal-tools
cd acal-tools/yacal-validator
pip install -e .
```

Then from anywhere on your system:

```bash
yacal-validate my-policy.yaml
```

### Option C: install from PyPI (once published)

```bash
pip install yacal-validator
yacal-validate my-policy.yaml
```

---

## CLI reference

```
yacal-validate [OPTIONS] FILE
```

| Option | Description |
|---|---|
| `--json` | Emit results as JSON instead of human-readable text |
| `--refresh-schemas` | Re-fetch schema files from the configured source before validating |
| `--version` | Show version and exit |
| `-h`, `--help` | Show help and exit |

**Exit codes**

| Code | Meaning |
|---|---|
| `0` | Document is valid |
| `1` | Validation failed (one or more errors) |
| `2` | Tool error (unreadable file, missing schemas, network failure) |

---

## Configuration

Schema files are fetched from the ACAL spec repository and cached locally. No configuration is required for default behavior.

To override the schema source, create `yacal-validator.toml` in your working directory (or `~/.config/yacal-validator/config.toml` for a user-wide default):

```toml
[schemas]
source = "https://github.com/oasis-tcs/xacml-spec"
branch = "main"
```

`source` can also be a local filesystem path, which is useful when working against a local spec checkout:

```toml
[schemas]
source = "/path/to/your/xacml-spec"
```

Cached schemas live in `~/.cache/yacal-validator/`. Run `--refresh-schemas` to force a refresh.

---

## Publishing to PyPI

PyPI (the Python Package Index at [pypi.org](https://pypi.org)) is the standard registry where `pip install` looks by default. Publishing there makes the tool installable by anyone with `pip install yacal-validator`.

**One-time setup**

1. Create a free account at [pypi.org](https://pypi.org) and verify your email.
2. Generate an API token: *Account settings → API tokens → Add API token*. Scope it to this project once the project exists, or use account-scope for the first upload.
3. Install the build and upload tools:
   ```bash
   pip install build twine
   ```

**Build the package**

From the `yacal-validator/` directory:

```bash
python -m build
```

This produces `dist/yacal_validator-0.1.0.tar.gz` and `dist/yacal_validator-0.1.0-py3-none-any.whl`.

**Upload to PyPI**

```bash
twine upload dist/*
```

Twine will prompt for your username (`__token__`) and the API token as the password.

After upload, the package is live and anyone can install it with `pip install yacal-validator`.

**Test before publishing**

PyPI provides a test instance at [test.pypi.org](https://test.pypi.org) where you can do a dry run without affecting the real registry:

```bash
twine upload --repository testpypi dist/*
pip install --index-url https://test.pypi.org/simple/ yacal-validator
```

**Version bumps**

Each upload to PyPI must have a unique version number. Update the `version` field in `pyproject.toml` before building and uploading a new release.

---

## Development

```bash
pip install -e ".[dev]"
pytest
```

Tests that require the normative spec files look for them at `/Users/wparducci/source/acal/xacml-spec` by default. Override with the `ACAL_SPEC_DIR` environment variable:

```bash
ACAL_SPEC_DIR=/path/to/xacml-spec pytest
```
