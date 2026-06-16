"""YACAL v1.0 (YAML) validation.

Two-layer validation:
  1. Structural JSON Schema (Draft 2020-12) via jsonschema + referencing
  2. Higher-order constraint catalog (constraints.py)

Structural schema passes first; constraints run only if structure is clean.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import jsonschema
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from ruamel.yaml import YAML

from .base import Severity, ValidationIssue, ValidationResult
from .constraints import evaluate as eval_constraints, load_catalog

_yaml = YAML()
_yaml.preserve_quotes = True

_XPATH_INDICATORS = frozenset({
    "XPathAttributeSelector", "XPathPolicyDefaults", "XPathRequestDefaults",
    "XPathEntityAttributeSelector",
})
_JSONPATH_INDICATORS = frozenset({
    "JSONPathAttributeSelector", "JSONPathPolicyDefaults",
    "JSONPathEntityAttributeSelector",
})


def detect_profiles(content: str) -> list[str]:
    profiles: list[str] = []
    if any(k in content for k in _XPATH_INDICATORS):
        profiles.append("xpath")
    if any(k in content for k in _JSONPATH_INDICATORS):
        profiles.append("jsonpath")
    return profiles


def validate(
    yaml_path: Path,
    core_structure_path: Path,
    core_constraints_path: Path,
    xpath_structure_path: Path | None,
    jsonpath_structure_path: Path | None,
) -> ValidationResult:
    content = yaml_path.read_text(encoding="utf-8")
    profiles = detect_profiles(content)
    result = ValidationResult(format="yacal", profiles=profiles)

    try:
        with open(yaml_path, "r", encoding="utf-8") as f:
            document = _yaml.load(f)
    except Exception as exc:
        result.add_issue(ValidationIssue(
            severity=Severity.ERROR,
            message=f"YAML parse error: {exc}",
            path="$",
            rule_id="parse:yaml-syntax",
        ))
        return result

    if document is None:
        result.add_issue(ValidationIssue(
            severity=Severity.ERROR,
            message="Document is empty.",
            path="$",
            rule_id="parse:empty",
        ))
        return result

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
        issues, total, evaluated, skipped = eval_constraints(document_plain, catalog)
        result.constraints_total = total
        result.constraints_evaluated = evaluated
        result.constraints_skipped = skipped
        for issue in issues:
            result.add_issue(issue)

    return result


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
    return _to_plain(raw)


def _to_plain(obj: Any) -> Any:
    """Convert ruamel CommentedMap/CommentedSeq to plain Python dicts/lists."""
    if isinstance(obj, dict):
        return {k: _to_plain(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_to_plain(i) for i in obj]
    return obj
