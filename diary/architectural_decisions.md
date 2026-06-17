# Architectural Decisions

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
