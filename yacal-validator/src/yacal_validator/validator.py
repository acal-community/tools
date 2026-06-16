"""YACAL v1.0 (YAML) validation.

Two-layer validation:
  1. Structural JSON Schema (Draft 2020-12) via jsonschema + referencing
  2. Higher-order constraint catalog (constraints.py)

Structural schema passes first; constraints run only if structure is clean.
"""
from __future__ import annotations

from io import StringIO
from pathlib import Path
from typing import Any

import jsonschema
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from ruamel.yaml.comments import TaggedScalar
from ruamel.yaml import YAML
from ruamel.yaml.scalarint import OctalInt

from .base import Severity, ValidationIssue, ValidationResult
from .constraints import evaluate as eval_constraints, load_catalog

_yaml = YAML()
_yaml.preserve_quotes = True

_XPATH_INDICATORS = frozenset({
    "XPathPolicyDefaults", "XPathRequestDefaults", "ContextSelectorId",
    "XPathCategory", "XPath:", "XPathAttributeSelector", "XPathEntityAttributeSelector",
})
_JSONPATH_INDICATORS = frozenset({
    "MediaType: application/json", 'MediaType: "application/json"',
    "Path: $", "Path: \"$", "Path: '$",
    "JSONPathAttributeSelector", "JSONPathEntityAttributeSelector",
})
_YAML_SPEC_REF = "YACAL §5.1.4 / §7.4"


def detect_profiles(content: str) -> list[str]:
    profiles: list[str] = []
    if any(k in content for k in _XPATH_INDICATORS):
        profiles.append("xpath")

    # JSONPath selector surface forms in YACAL use the core wrapper keys
    # AttributeSelector / EntityAttributeSelector, so we infer the profile from
    # JSON content markers and the conventional '$'-prefixed path syntax.
    if any(k in content for k in _JSONPATH_INDICATORS):
        profiles.append("jsonpath")
    return profiles


def validate(
    yaml_path: Path,
    core_structure_path: Path,
    core_constraints_path: Path,
    xpath_structure_path: Path | None,
    jsonpath_structure_path: Path | None,
    include_paths: list[Path] | None = None,
) -> ValidationResult:
    content = yaml_path.read_text(encoding="utf-8")
    profiles = detect_profiles(content)
    result = ValidationResult(format="yacal", profiles=profiles)

    try:
        documents = list(_yaml.load_all(StringIO(content)))
    except Exception as exc:
        result.add_issue(ValidationIssue(
            severity=Severity.ERROR,
            message=f"YAML parse error: {exc}",
            path="$",
            rule_id="parse:yaml-syntax",
        ))
        return result

    if not documents or documents[0] is None:
        result.add_issue(ValidationIssue(
            severity=Severity.ERROR,
            message="Document is empty.",
            path="$",
            rule_id="parse:empty",
        ))
        return result

    if len(documents) != 1:
        result.add_issue(ValidationIssue(
            severity=Severity.ERROR,
            message="YACAL documents MUST NOT use YAML multi-document streams.",
            path="$",
            rule_id="yaml:multi-document-stream",
            spec_ref=_YAML_SPEC_REF,
        ))
        return result

    document = documents[0]
    for issue in _lint_yaml_features(document):
        result.add_issue(issue)

    document_plain = _to_plain(document)

    core, registry, ids = _build_registry(
        core_structure_path, xpath_structure_path, jsonpath_structure_path
    )
    root_schema = _composed_root(ids, profiles)
    registry = registry.with_resource(root_schema["$id"], Resource.from_contents(root_schema))
    validator = Draft202012Validator({"$ref": root_schema["$id"]}, registry=registry)

    for error in validator.iter_errors(document_plain):
        result.add_issue(ValidationIssue(
            severity=Severity.ERROR,
            message=error.message,
            path=_jsonpath(error),
            rule_id=f"jsonschema:{error.validator}",
        ))

    if result.valid and core_constraints_path.exists():
        catalog = load_catalog(core_constraints_path)
        extra_docs = _load_include_docs(include_paths) if include_paths else []
        issues, total, evaluated, skipped = eval_constraints(document_plain, catalog, extra_docs)
        result.constraints_total = total
        result.constraints_evaluated = evaluated
        result.constraints_skipped = skipped
        for issue in issues:
            result.add_issue(issue)

    return result


def _load_include_docs(paths: list[Path]) -> list[Any]:
    docs = []
    for p in paths:
        try:
            with open(p, "r", encoding="utf-8") as f:
                doc = _yaml.load(f)
            if doc is not None:
                docs.append(_to_plain(doc))
        except Exception:
            pass
    return docs


def _jsonpath(error: jsonschema.ValidationError) -> str:
    parts = list(error.absolute_path)
    if not parts:
        return "$"
    segs = []
    for p in parts:
        segs.append(f"[{p}]" if isinstance(p, int) else f".{p}")
    return "$" + "".join(segs)


def _build_registry(
    core_path: Path,
    xpath_path: Path | None,
    jsonpath_path: Path | None,
) -> tuple[dict, Registry, dict[str, str]]:
    core = _load_yaml_schema(core_path)
    ids = {"core": core.get("$id", "acal-core-yaml-v1.0-structure.schema.yaml")}
    resources = [(ids["core"], Resource.from_contents(core))]

    if xpath_path and xpath_path.exists():
        xpath = _load_yaml_schema(xpath_path)
        ids["xpath"] = xpath.get("$id", "acal-xpath-yaml-v1.0-structure.schema.yaml")
        resources.append((ids["xpath"], Resource.from_contents(xpath)))

    if jsonpath_path and jsonpath_path.exists():
        jp = _load_yaml_schema(jsonpath_path)
        ids["jsonpath"] = jp.get("$id", "acal-jsonpath-yaml-v1.0-structure.schema.yaml")
        resources.append((ids["jsonpath"], Resource.from_contents(jp)))

    return core, Registry().with_resources(resources), ids


_YAML_ROOT_ID = "urn:yacal-validator:composed-yaml-root"


def _composed_root(ids: dict[str, str], profiles: list[str]) -> dict:
    core_id = ids["core"]
    if not profiles:
        return {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": _YAML_ROOT_ID,
            "$ref": core_id,
        }

    xpath_id = ids.get("xpath", "acal-xpath-yaml-v1.0-structure.schema.yaml")
    jsonpath_id = ids.get("jsonpath", "acal-jsonpath-yaml-v1.0-structure.schema.yaml")
    defs: dict = {}

    if "xpath" in profiles:
        defs["_xpathPolicy"] = {
            "$dynamicAnchor": "PolicyDefaultsTypeExtensions",
            "$ref": f"{xpath_id}#/$defs/XPathPolicyDefaultsTypeExtension",
        }
        defs["_xpathRequest"] = {
            "$dynamicAnchor": "RequestDefaultsTypeExtensions",
            "$ref": f"{xpath_id}#/$defs/XPathRequestDefaultsTypeExtension",
        }
        defs["_xpathAttrSel"] = {
            "$dynamicAnchor": "AttributeSelectorTypeExtensions",
            "$ref": f"{xpath_id}#/$defs/XPathAttributeSelectorTypeExtension",
        }
        defs["_xpathEntityAttrSel"] = {
            "$dynamicAnchor": "EntityAttributeSelectorTypeExtensions",
            "$ref": f"{xpath_id}#/$defs/XPathEntityAttributeSelectorTypeExtension",
        }
        defs["_xpathValue"] = {
            "$dynamicAnchor": "StructuredValueTypeExtensions",
            "$ref": f"{xpath_id}#/$defs/XPathStructuredValueTypeExtension",
        }

    if "jsonpath" in profiles:
        if "xpath" in profiles:
            defs["_xpathAttrSel"] = {
                "$dynamicAnchor": "AttributeSelectorTypeExtensions",
                "anyOf": [
                    {"$ref": f"{xpath_id}#/$defs/XPathAttributeSelectorTypeExtension"},
                    {"$ref": f"{jsonpath_id}#/$defs/JSONPathAttributeSelectorTypeExtension"},
                ],
            }
            defs["_xpathEntityAttrSel"] = {
                "$dynamicAnchor": "EntityAttributeSelectorTypeExtensions",
                "anyOf": [
                    {"$ref": f"{xpath_id}#/$defs/XPathEntityAttributeSelectorTypeExtension"},
                    {"$ref": f"{jsonpath_id}#/$defs/JSONPathEntityAttributeSelectorTypeExtension"},
                ],
            }
        else:
            defs["_jsonpathAttrSel"] = {
                "$dynamicAnchor": "AttributeSelectorTypeExtensions",
                "$ref": f"{jsonpath_id}#/$defs/JSONPathAttributeSelectorTypeExtension",
            }
            defs["_jsonpathEntityAttrSel"] = {
                "$dynamicAnchor": "EntityAttributeSelectorTypeExtensions",
                "$ref": f"{jsonpath_id}#/$defs/JSONPathEntityAttributeSelectorTypeExtension",
            }

    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": _YAML_ROOT_ID,
        "$defs": defs,
        "$ref": core_id,
    }


def _load_yaml_schema(path: Path) -> dict:
    # Schema files may have trailing tabs and duplicate keys in $defs.
    content = path.read_text(encoding="utf-8")
    content = "\n".join(line.rstrip() for line in content.splitlines())
    _schema_yaml = YAML()
    _schema_yaml.allow_duplicate_keys = True
    raw = _schema_yaml.load(content)
    patched = _patch_schema(_to_plain(raw))
    if path.name == "acal-core-yaml-v1.0-structure.schema.yaml":
        _patch_core_schema_shape_bugs(patched)
    return patched


def _patch_core_schema_shape_bugs(schema: dict) -> None:
    """Patch known core-schema shape bugs that block spec-aligned validation."""
    defs = schema.get("$defs")
    if not isinstance(defs, dict):
        return

    if "AttributeSelectorCoreType" not in defs:
        defs["AttributeSelectorCoreType"] = {
            "allOf": [
                {"$ref": "#/$defs/BaseAttributeSelectorType"},
                {
                    "type": "object",
                    "required": ["Category"],
                    "properties": {
                        "Category": {"$ref": "#/$defs/IdentifierType"},
                    },
                },
            ],
        }

    if "EntityAttributeSelectorCoreType" not in defs:
        defs["EntityAttributeSelectorCoreType"] = {
            "allOf": [
                {"$ref": "#/$defs/BaseAttributeSelectorType"},
                {
                    "type": "object",
                    "required": ["Expression"],
                    "properties": {
                        "Expression": {"$ref": "#/$defs/ExpressionTypeTree"},
                    },
                },
            ],
        }

    defs["AttributeSelectorTypeTree"] = {
        "type": "object",
        "required": ["AttributeSelector"],
        "properties": {
            "AttributeSelector": {"$dynamicRef": "#AttributeSelectorTypeExtensions"},
        },
        "additionalProperties": False,
    }

    defs["EntityAttributeSelectorTypeTree"] = {
        "type": "object",
        "required": ["EntityAttributeSelector"],
        "properties": {
            "EntityAttributeSelector": {"$dynamicRef": "#EntityAttributeSelectorTypeExtensions"},
        },
        "additionalProperties": False,
    }

    defs["BaseAttributeSelectorTypeTree"] = {
        "anyOf": [
            {"$ref": "#/$defs/AttributeSelectorTypeTree"},
            {"$ref": "#/$defs/EntityAttributeSelectorTypeTree"},
        ],
    }

    defs["IdReferenceType"] = {
        "type": "object",
        "properties": {
            "Id": {"$ref": "#/$defs/URIType"},
        },
        "required": ["Id"],
    }

    defs["ExactMatchIdReferenceType"] = {
        "allOf": [
            {"$ref": "#/$defs/IdReferenceType"},
            {
                "type": "object",
                "properties": {
                    "Version": {"$ref": "#/$defs/VersionType"},
                },
                "required": ["Version"],
            },
        ],
        "unevaluatedProperties": False,
    }

    status_detail_extensions = defs.get("StatusDetailTypeExtensionsDisabled")
    if isinstance(status_detail_extensions, dict):
        status_detail_extensions.clear()
        status_detail_extensions["$dynamicAnchor"] = "StatusDetailTypeExtensions"

    policy_type = defs.get("PolicyType")
    if isinstance(policy_type, dict):
        properties = policy_type.get("properties")
        if isinstance(properties, dict) and isinstance(properties.get("PolicyDefaults"), dict):
            properties["PolicyDefaults"] = {
                "type": "array",
                "items": {"$ref": "#/$defs/PolicyDefaultsTypeTree"},
                "minItems": 1,
            }

    request_type = defs.get("RequestType")
    if isinstance(request_type, dict):
        properties = request_type.get("properties")
        if isinstance(properties, dict) and isinstance(properties.get("RequestDefaults"), dict):
            properties["RequestDefaults"] = {
                "type": "array",
                "items": {"$ref": "#/$defs/RequestDefaultsTypeTree"},
                "minItems": 1,
            }


def _patch_schema(obj: Any) -> Any:
    # The spec schemas have several authoring bugs that cause the referencing library
    # to crash. Patch them at load time so the tool stays usable while upstream fixes
    # are pending.
    #
    #  1. 'properties: null' — YAML indentation error; null is invalid JSON Schema.
    #     Strip the key (no-op in JSON Schema).
    #  2. '$defs' value is a list — missing 'oneOf:' wrapper; wrap it.
    #     (QuantifiedExpressionTypeTree in core schema)
    #  3. 'required' value is a scalar — must be an array.
    #     (ArgumentTypeTree in core schema)
    if isinstance(obj, dict):
        result = {}
        for k, v in obj.items():
            if k == "properties" and v is None:
                continue
            if k == "$defs" and isinstance(v, dict):
                fixed_defs = {}
                for dk, dv in v.items():
                    if isinstance(dv, list):
                        fixed_defs[dk] = {"oneOf": _patch_schema(dv)}
                    else:
                        fixed_defs[dk] = _patch_schema(dv)
                result[k] = fixed_defs
                continue
            if k == "required" and isinstance(v, str):
                result[k] = [v]
                continue
            result[k] = _patch_schema(v)
        return result
    if isinstance(obj, list):
        return [_patch_schema(i) for i in obj]
    return obj


def _to_plain(obj: Any) -> Any:
    """Convert ruamel CommentedMap/CommentedSeq to plain Python dicts/lists."""
    if isinstance(obj, dict):
        return {k: _to_plain(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_to_plain(i) for i in obj]
    return obj


def _lint_yaml_features(document: Any) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    seen: set[int] = set()

    def visit(node: Any, path: str) -> None:
        node_id = id(node)
        if isinstance(node, (dict, list)):
            if node_id in seen:
                return
            seen.add(node_id)

        tag = getattr(node, "tag", None)
        tag_value = getattr(tag, "value", None)
        if tag_value is not None:
            issues.append(ValidationIssue(
                severity=Severity.ERROR,
                message=f"YAML tags are not allowed in YACAL documents ({tag_value}).",
                path=path,
                rule_id="yaml:disallowed-tag",
                spec_ref=_YAML_SPEC_REF,
            ))

        anchor = getattr(node, "anchor", None)
        anchor_value = getattr(anchor, "value", None)
        if anchor_value is not None:
            issues.append(ValidationIssue(
                severity=Severity.ERROR,
                message="YAML anchors and aliases are not allowed in YACAL documents.",
                path=path,
                rule_id="yaml:disallowed-anchor",
                spec_ref=_YAML_SPEC_REF,
            ))

        merge = getattr(node, "merge", None)
        if merge:
            issues.append(ValidationIssue(
                severity=Severity.ERROR,
                message="YAML merge keys are not allowed in YACAL documents.",
                path=path,
                rule_id="yaml:disallowed-merge-key",
                spec_ref=_YAML_SPEC_REF,
            ))

        if node is None:
            issues.append(ValidationIssue(
                severity=Severity.ERROR,
                message="YAML null values are not allowed in YACAL documents.",
                path=path,
                rule_id="yaml:null-value",
                spec_ref=_YAML_SPEC_REF,
            ))
            return

        if isinstance(node, OctalInt):
            issues.append(ValidationIssue(
                severity=Severity.ERROR,
                message="YAML octal integer notation is not allowed in YACAL documents.",
                path=path,
                rule_id="yaml:octal-integer",
                spec_ref=_YAML_SPEC_REF,
            ))
            return

        if isinstance(node, dict):
            for key, value in node.items():
                child_path = f"{path}.{key}" if path != "$" else f"$.{key}"
                visit(value, child_path)
        elif isinstance(node, list):
            for index, value in enumerate(node):
                visit(value, f"{path}[{index}]")
        elif isinstance(node, TaggedScalar):
            # Already covered by the tag check above; return to avoid treating
            # tagged nulls or scalars as plain Python values.
            return

    visit(document, "$")
    return issues
