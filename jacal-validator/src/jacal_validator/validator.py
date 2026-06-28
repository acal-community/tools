"""JACAL v1.0 (JSON) validation.

Two-layer validation:
  1. Structural JSON Schema (Draft 2020-12) via jsonschema + referencing
  2. Higher-order constraint catalog (constraints.py)

Structural schema passes first; constraints run only if structure is clean.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import jsonschema
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from .base import Severity, ValidationIssue, ValidationResult
from .constraints import evaluate as eval_constraints, load_catalog

_JACAL_SPEC_REF = "JACAL §5 / RFC 8259"

_XPATH_INDICATORS = frozenset({
    "XPathPolicyDefaults", "XPathRequestDefaults", "ContextSelectorId",
    "XPathCategory", "XPath", "XPathAttributeSelector", "XPathEntityAttributeSelector",
})
_JSONPATH_INDICATORS = frozenset({
    "JSONPathAttributeSelector", "JSONPathEntityAttributeSelector",
})


def detect_profiles(content: str) -> list[str]:
    profiles: list[str] = []
    if any(f'"{k}"' in content for k in _XPATH_INDICATORS):
        profiles.append("xpath")
    if any(f'"{k}"' in content for k in _JSONPATH_INDICATORS):
        profiles.append("jsonpath")
    return profiles


def validate(
    json_path: Path,
    core_structure_path: Path,
    core_constraints_path: Path,
    xpath_structure_path: Path | None,
    jsonpath_structure_path: Path | None,
    include_paths: list[Path] | None = None,
) -> ValidationResult:
    content = json_path.read_text(encoding="utf-8")
    profiles = detect_profiles(content)
    result = ValidationResult(format="jacal", profiles=profiles)

    for issue in _lint_json_features(content):
        result.add_issue(issue)

    if not result.valid:
        return result

    try:
        document = _load_json_strict(content)
    except json.JSONDecodeError as exc:
        result.add_issue(ValidationIssue(
            severity=Severity.ERROR,
            message=f"JSON parse error: {exc}",
            path="$",
            rule_id="parse:json-syntax",
        ))
        return result

    if document is None or not isinstance(document, dict):
        result.add_issue(ValidationIssue(
            severity=Severity.ERROR,
            message="Document must be a JSON object.",
            path="$",
            rule_id="parse:not-an-object",
        ))
        return result

    core, registry, ids = _build_registry(
        core_structure_path, xpath_structure_path, jsonpath_structure_path
    )
    root_schema = _composed_root(ids, profiles)
    registry = registry.with_resource(root_schema["$id"], Resource.from_contents(root_schema))
    validator = Draft202012Validator({"$ref": root_schema["$id"]}, registry=registry)

    for error in validator.iter_errors(document):
        result.add_issue(ValidationIssue(
            severity=Severity.ERROR,
            message=error.message,
            path=_jsonpath(error),
            rule_id=f"jsonschema:{error.validator}",
        ))

    if result.valid and core_constraints_path.exists():
        catalog = load_catalog(core_constraints_path)
        extra_docs = _load_include_docs(include_paths) if include_paths else []
        issues, total, evaluated, skipped = eval_constraints(document, catalog, extra_docs)
        result.constraints_total = total
        result.constraints_evaluated = evaluated
        result.constraints_skipped = skipped
        for issue in issues:
            result.add_issue(issue)

    return result


def _load_json_strict(content: str) -> Any:
    """Parse JSON, detecting duplicate object keys."""
    duplicate_keys: list[str] = []

    def object_pairs_hook(pairs: list[tuple[str, Any]]) -> dict:
        seen: dict[str, Any] = {}
        for key, value in pairs:
            if key in seen:
                duplicate_keys.append(key)
            seen[key] = value
        return seen

    obj = json.loads(content, object_pairs_hook=object_pairs_hook)
    if duplicate_keys:
        raise _DuplicateKeyError(duplicate_keys)
    return obj


class _DuplicateKeyError(ValueError):
    def __init__(self, keys: list[str]) -> None:
        self.keys = keys
        super().__init__(f"Duplicate JSON object key(s): {keys}")


def _load_include_docs(paths: list[Path]) -> list[Any]:
    docs = []
    for p in paths:
        try:
            content = p.read_text(encoding="utf-8")
            doc = json.loads(content)
            if doc is not None:
                docs.append(doc)
        except Exception:
            pass
    return docs


def _lint_json_features(content: str) -> list[ValidationIssue]:
    """Check for JSON conformance issues invisible to the JSON parser."""
    issues: list[ValidationIssue] = []

    # Duplicate object keys — detected separately in _load_json_strict;
    # check here so we can report before attempting structural validation.
    try:
        _load_json_strict(content)
    except _DuplicateKeyError as exc:
        for key in exc.keys:
            issues.append(ValidationIssue(
                severity=Severity.ERROR,
                message=f"Duplicate JSON object key {key!r} — JACAL documents must have unique keys per object.",
                path="$",
                rule_id="json:duplicate-key",
                spec_ref=_JACAL_SPEC_REF,
            ))
    except json.JSONDecodeError:
        pass  # reported separately

    # Line or block comments (non-standard JSON extension)
    if re.search(r'(?://[^\n]*|/\*.*?\*/)', content, re.DOTALL):
        issues.append(ValidationIssue(
            severity=Severity.ERROR,
            message="JSON comments (// or /* */) are not allowed in JACAL documents.",
            path="$",
            rule_id="json:comment",
            spec_ref=_JACAL_SPEC_REF,
        ))

    # Trailing commas before ] or } (non-standard JSON extension)
    if re.search(r',\s*[}\]]', content):
        issues.append(ValidationIssue(
            severity=Severity.ERROR,
            message="Trailing commas are not allowed in JACAL documents.",
            path="$",
            rule_id="json:trailing-comma",
            spec_ref=_JACAL_SPEC_REF,
        ))

    return issues


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
    core = _load_json_schema(core_path)
    ids = {"core": core.get("$id", "urn:oasis:names:tc:jacal:1.0:core:schema")}
    resources = [(ids["core"], Resource.from_contents(core))]

    if xpath_path and xpath_path.exists():
        xpath = _load_json_schema(xpath_path)
        ids["xpath"] = xpath.get("$id", "urn:oasis:names:tc:jacal:1.0:xpath:schema")
        resources.append((ids["xpath"], Resource.from_contents(xpath)))

    if jsonpath_path and jsonpath_path.exists():
        jp = _load_json_schema(jsonpath_path)
        ids["jsonpath"] = jp.get("$id", "urn:oasis:names:tc:jacal:1.0:jsonpath:schema")
        resources.append((ids["jsonpath"], Resource.from_contents(jp)))

    return core, Registry().with_resources(resources), ids


_JSON_ROOT_ID = "urn:jacal-validator:composed-json-root"


def _composed_root(ids: dict[str, str], profiles: list[str]) -> dict:
    core_id = ids["core"]
    if not profiles:
        return {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": _JSON_ROOT_ID,
            "$ref": core_id,
        }

    xpath_id = ids.get("xpath", "urn:oasis:names:tc:jacal:1.0:xpath:schema")
    jsonpath_id = ids.get("jsonpath", "urn:oasis:names:tc:jacal:1.0:jsonpath:schema")
    defs: dict = {}

    if "xpath" in profiles:
        defs["_xpathPolicy"] = {
            "$dynamicAnchor": "PolicyDefaultsTypeExtensions",
            "$ref": f"{xpath_id}#/$defs/XPathPolicyDefaultsTypeTree",
        }
        defs["_xpathRequest"] = {
            "$dynamicAnchor": "RequestDefaultsTypeExtensions",
            "$ref": f"{xpath_id}#/$defs/XPathRequestDefaultsTypeTree",
        }
        defs["_xpathAttrSel"] = {
            "$dynamicAnchor": "AttributeSelectorTypeExtensions",
            "$ref": f"{xpath_id}#/$defs/XPathAttributeSelectorTypeTree",
        }
        defs["_xpathEntityAttrSel"] = {
            "$dynamicAnchor": "EntityAttributeSelectorTypeExtensions",
            "$ref": f"{xpath_id}#/$defs/XPathEntityAttributeSelectorTypeTree",
        }
        defs["_xpathValue"] = {
            "$dynamicAnchor": "StructuredValueTypeExtensions",
            "$ref": f"{xpath_id}#/$defs/XPathExpressionValueType",
        }

    if "jsonpath" in profiles:
        if "xpath" in profiles:
            defs["_xpathAttrSel"] = {
                "$dynamicAnchor": "AttributeSelectorTypeExtensions",
                "anyOf": [
                    {"$ref": f"{xpath_id}#/$defs/XPathAttributeSelectorTypeTree"},
                    {"$ref": f"{jsonpath_id}#/$defs/JSONPathAttributeSelectorTypeTree"},
                ],
            }
            defs["_xpathEntityAttrSel"] = {
                "$dynamicAnchor": "EntityAttributeSelectorTypeExtensions",
                "anyOf": [
                    {"$ref": f"{xpath_id}#/$defs/XPathEntityAttributeSelectorTypeTree"},
                    {"$ref": f"{jsonpath_id}#/$defs/JSONPathEntityAttributeSelectorTypeTree"},
                ],
            }
        else:
            defs["_jsonpathAttrSel"] = {
                "$dynamicAnchor": "AttributeSelectorTypeExtensions",
                "$ref": f"{jsonpath_id}#/$defs/JSONPathAttributeSelectorTypeTree",
            }
            defs["_jsonpathEntityAttrSel"] = {
                "$dynamicAnchor": "EntityAttributeSelectorTypeExtensions",
                "$ref": f"{jsonpath_id}#/$defs/JSONPathEntityAttributeSelectorTypeTree",
            }

    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": _JSON_ROOT_ID,
        "$defs": defs,
        "$ref": core_id,
    }


def _load_json_schema(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        schema = json.load(f)
    _patch_core_schema_shape_bugs(schema)
    return schema


def _patch_core_schema_shape_bugs(schema: dict) -> None:
    """Patch known JACAL core-schema shape bugs that block spec-aligned validation."""
    if schema.get("$id") != "urn:oasis:names:tc:jacal:1.0:core:schema":
        return

    defs = schema.get("$defs")
    if not isinstance(defs, dict):
        return

    # AttributeSelectorType and EntityAttributeSelectorType use unevaluatedProperties: false.
    # This prevents profile-specific subtypes (XPathAttributeSelectorType) from adding extra
    # properties (e.g. ContextSelectorId) because the base type's unevaluatedProperties
    # rejects them before the subtype schema can evaluate them.
    # Fix: remove unevaluatedProperties from the abstract intermediate types.
    for type_name in ("AttributeSelectorType", "EntityAttributeSelectorType"):
        t = defs.get(type_name)
        if isinstance(t, dict):
            t.pop("unevaluatedProperties", None)
