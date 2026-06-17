# Lessons Learned

## typed-value-boolean-is-not-valid (June 2026)

**Rule**: In JACAL `TypedValueType`, `Value` must be a number or string — boolean `true`/`false` are NOT valid. Use the raw boolean `true`/`false` (PrimitiveValueType) instead of `{"DataType": "{boolean}", "Value": true}`.

**Why**: `TypedValueType` in the JACAL schema uses `{"type": ["number", "string"]}` for primitive Value. Boolean values always have a fixed DataType (`{boolean}`) so they don't need one specified; the schema comment says "Boolean values not included here because they have a fixed DataType: ACAL Boolean." Writing `{DataType: "{boolean}", Value: true}` causes `jsonschema:anyOf` failures that look like top-level document errors, making it very hard to diagnose without inspecting sub-errors.

## schema-dependent-required-vs-constraint (June 2026)

**Rule**: When building JACAL test fixtures for constraints that the schema also enforces structurally (e.g., via `dependentRequired`, `uniqueItems`, `dependentSchemas`), the constraint catalog rule will never fire — the schema catches it first. Categorize these fixtures as "structural" in the test suite rather than "constraint."

**Why**: Several constraints from the ACAL catalog were implemented twice: once in the JSON Schema (as structural enforcement) and once in the constraint catalog (as a semantic rule). Examples: `bundle-policyreference-requires-policy` uses both `dependentRequired` in schema and a `nonEmptyWhenPresent` catalog rule; `shortidset-reference-no-repeat` (duplicate path) is caught by `uniqueItems: true`. Discovering this required validating the same fixture in multiple ways and examining sub-errors, not just top-level error messages. The fixture still demonstrates "invalid document" behavior; it just isn't a constraint-layer test.

## expression-value-datatype-is-context-dependent (June 2026)

**Rule**: In JACAL, whether `Expression.Value.DataType` is allowed depends on WHERE in the schema the expression appears, not on the ExpressionTypeTree definition itself. Always test the specific container type before assuming TypedValueType works.

**Why**: `ExpressionTypeTree` includes `TypedValueType` as a valid option at the schema level. But many container types add `dependentSchemas` that forbid `DataType` in the Value when the parent already declares DataType. Affected containers: `ParameterType.Expression`, `AttributeType.Value[]`, `SharedVariableReferenceType.Argument.Value`, `PolicyReferenceType.Argument.Value`. Writing fixtures with `{Value: {DataType: "...", Value: ...}}` in these containers produces top-level `jsonschema:anyOf` errors that give no direct hint about which nested `dependentSchemas.DataType: {not: true}` triggered.

## debugging-nested-jsonschema-anyof-errors (June 2026)

**Rule**: When a JACAL document fails with `jsonschema:anyOf` at `$`, always inspect `err.context` sub-errors to find the real failure path — the top-level message just says "not valid under any of the given schemas."

**Why**: The JACAL top-level schema is `anyOf: [PolicyWrapper, BundleWrapper, RequestWrapper, ResponseWrapper]`. ANY structural error anywhere in the document surfaces as a top-level `anyOf` failure because all four branches fail. The actual error (e.g., `dependentRequired: Policy required when PolicyReference present`) is buried several levels deep in `err.context`. The `validate()` function currently only reports the top-level error; investigating requires either `--output json` with post-processing, or direct `jsonschema` API usage with `err.context` traversal.
