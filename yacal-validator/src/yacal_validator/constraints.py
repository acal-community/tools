"""Evaluator for the YACAL v1.0 higher-order constraint catalog.

Reads the machine-readable constraint catalog (acal-core-yaml-v1.0-constraints.yaml)
and evaluates each rule against a parsed YACAL document.

Path notation used by the catalog:
  $           document root
  .Property   access dict key
  []          iterate sequence items
  $..Key      recursive descent (find key at any depth)
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

from .base import Severity, ValidationIssue

_yaml = YAML()
_yaml.preserve_quotes = True


# ---------------------------------------------------------------------------
# Catalog loading
# ---------------------------------------------------------------------------

def load_catalog(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return _yaml.load(f)


# ---------------------------------------------------------------------------
# Path evaluator
# ---------------------------------------------------------------------------

def eval_path(root: Any, path: str) -> list[tuple[str, Any]]:
    """Return [(path_string, value)] for all matches of *path* in *root*."""
    if not path.startswith("$"):
        raise ValueError(f"Path must start with '$': {path!r}")

    # Recursive descent: $..Key
    if path.startswith("$.."):
        return _descend(root, path[3:], "$")

    tokens = _tokenize(path[1:])
    return _eval([("$", root)], tokens)


def _tokenize(path: str) -> list[str]:
    """Split '.Foo[].Bar' into ['Foo', '[]', 'Bar']."""
    tokens: list[str] = []
    i = 0
    while i < len(path):
        if path[i] == ".":
            i += 1
            j = i
            while j < len(path) and path[j] not in (".", "["):
                j += 1
            if j > i:
                tokens.append(path[i:j])
            i = j
        elif path[i:i+2] == "[]":
            tokens.append("[]")
            i += 2
        elif path[i] == "[":
            # Skip numeric index (not used in catalog paths)
            end = path.find("]", i)
            i = end + 1 if end != -1 else len(path)
        else:
            i += 1
    return tokens


def _eval(current: list[tuple[str, Any]], tokens: list[str]) -> list[tuple[str, Any]]:
    for token in tokens:
        nxt: list[tuple[str, Any]] = []
        for path_str, node in current:
            if token == "[]":
                if isinstance(node, list):
                    for idx, item in enumerate(node):
                        nxt.append((f"{path_str}[{idx}]", item))
            else:
                if isinstance(node, dict) and token in node:
                    nxt.append((f"{path_str}.{token}", node[token]))
        current = nxt
    return current


def _descend(root: Any, key: str, path: str) -> list[tuple[str, Any]]:
    """Find all values named *key* at any depth."""
    results: list[tuple[str, Any]] = []
    if isinstance(root, dict):
        if key in root:
            results.append((f"{path}.{key}", root[key]))
        for k, v in root.items():
            results.extend(_descend(v, key, f"{path}.{k}"))
    elif isinstance(root, list):
        for i, item in enumerate(root):
            results.extend(_descend(item, key, f"{path}[{i}]"))
    return results


def _resolve_relative(node: Any, rel_path: str) -> list[tuple[str, Any]]:
    """Evaluate a dot-separated relative path against *node*."""
    if not rel_path:
        return [("$", node)]
    full = "$." + rel_path
    return eval_path(node, full)


# ---------------------------------------------------------------------------
# Constraint checkers
# ---------------------------------------------------------------------------

def _provenance(rule: dict) -> str | None:
    prov = rule.get("Provenance", {}) or {}
    parts = []
    if "YACALSection" in prov:
        parts.append(f"YACAL §{prov['YACALSection']}")
    if "ACALSection" in prov:
        parts.append(f"ACAL §{prov['ACALSection']}")
    return " / ".join(parts) or None


def _unique_by_property(root: Any, rule: dict, out: list[ValidationIssue]) -> None:
    coll_path = rule.get("CollectionPath", "")
    keys = rule.get("KeyProperties", [])
    ignore_missing = bool(rule.get("IgnoreMissingKey", False))
    rule_id = rule["Id"]
    spec = _provenance(rule)

    for coll_str, coll in eval_path(root, coll_path):
        if not isinstance(coll, list):
            continue
        seen: dict[tuple, str] = {}
        for idx, item in enumerate(coll):
            if not isinstance(item, dict):
                continue
            if ignore_missing and not any(k in item for k in keys):
                continue
            key_val = tuple(item.get(k) for k in keys)
            item_path = f"{coll_str}[{idx}]"
            if key_val in seen:
                kv_str = ", ".join(f"{k}={item.get(k)!r}" for k in keys)
                out.append(ValidationIssue(
                    severity=Severity.ERROR,
                    message=f"Duplicate value ({kv_str}) at {item_path}; first at {seen[key_val]}",
                    path=item_path,
                    rule_id=f"yacal:{rule_id}",
                    spec_ref=spec,
                ))
            else:
                seen[key_val] = item_path


def _unique_by_concrete_subtype(root: Any, rule: dict, out: list[ValidationIssue]) -> None:
    coll_path = rule.get("CollectionPath", "")
    rule_id = rule["Id"]
    spec = _provenance(rule)

    for coll_str, coll in eval_path(root, coll_path):
        if not isinstance(coll, list):
            continue
        seen: dict[str, int] = {}
        for idx, item in enumerate(coll):
            if not isinstance(item, dict):
                continue
            item_keys = [k for k in item if not k.startswith("$")]
            if len(item_keys) == 1:
                subtype = item_keys[0]
            else:
                continue
            if subtype in seen:
                out.append(ValidationIssue(
                    severity=Severity.ERROR,
                    message=(
                        f"Duplicate concrete subtype '{subtype}' at "
                        f"{coll_str}[{idx}] (also at [{seen[subtype]}])"
                    ),
                    path=f"{coll_str}[{idx}]",
                    rule_id=f"yacal:{rule_id}",
                    spec_ref=spec,
                ))
            else:
                seen[subtype] = idx


def _non_empty_when_present(root: Any, rule: dict, out: list[ValidationIssue]) -> None:
    container_path = rule.get("ContainerPath", "")
    if_present = rule.get("IfPresentProperty")
    required = rule.get("RequiredNonEmptyCollectionProperty")
    rule_id = rule["Id"]
    spec = _provenance(rule)

    for path_str, container in eval_path(root, container_path):
        if not isinstance(container, dict):
            continue
        if if_present in container:
            val = container.get(required)
            if not val:
                out.append(ValidationIssue(
                    severity=Severity.ERROR,
                    message=(
                        f"'{required}' must be present and non-empty when "
                        f"'{if_present}' is present (at {path_str})"
                    ),
                    path=path_str,
                    rule_id=f"yacal:{rule_id}",
                    spec_ref=spec,
                ))


def _conditional_presence(root: Any, rule: dict, out: list[ValidationIssue]) -> None:
    container_path = rule.get("ContainerPath", "")
    when = rule.get("WhenPropertyEquals", {}) or {}
    when_prop_path = when.get("PropertyPath", "")
    when_value = when.get("Value")
    forbidden = rule.get("ForbiddenProperty")
    rule_id = rule["Id"]
    spec = _provenance(rule)

    if not forbidden:
        return

    for path_str, container in eval_path(root, container_path):
        if not isinstance(container, dict):
            continue
        cond = _resolve_relative(container, when_prop_path)
        actual = cond[0][1] if cond else None
        if actual == when_value and forbidden in container:
            out.append(ValidationIssue(
                severity=Severity.ERROR,
                message=(
                    f"'{forbidden}' MUST NOT be present when "
                    f"'{when_prop_path}' equals '{when_value}' (at {path_str})"
                ),
                path=path_str,
                rule_id=f"yacal:{rule_id}",
                spec_ref=spec,
            ))


def _property_agreement(root: Any, rule: dict, out: list[ValidationIssue]) -> None:
    rule_id = rule["Id"]
    spec = _provenance(rule)
    resolution = rule.get("Resolution", {}) or {}

    if resolution.get("RequiresReferencedSharedVariableLookup"):
        out.append(ValidationIssue(
            severity=Severity.WARNING,
            message=(
                f"Constraint '{rule_id}' requires cross-document shared-variable lookup "
                "and was not evaluated. Verify compliance manually."
            ),
            rule_id=f"yacal-skip:{rule_id}",
            spec_ref=spec,
        ))
        return
    if resolution.get("RequiresReferencedPolicyLookup"):
        out.append(ValidationIssue(
            severity=Severity.WARNING,
            message=(
                f"Constraint '{rule_id}' requires cross-document policy lookup "
                "and was not evaluated. Verify compliance manually."
            ),
            rule_id=f"yacal-skip:{rule_id}",
            spec_ref=spec,
        ))
        return

    applies_to = rule.get("AppliesTo", {}) or {}
    container_locations = applies_to.get("ContainerLocations", []) or []
    parent_prop = applies_to.get("ParentProperty")
    child_prop = applies_to.get("ChildProperty")
    child_coll = applies_to.get("ChildCollectionPath")
    child_expr = applies_to.get("ChildExpressionPath")

    if not (parent_prop and child_prop and (child_coll or child_expr)):
        out.append(ValidationIssue(
            severity=Severity.WARNING,
            message=(
                f"Constraint '{rule_id}' uses an unsupported propertyAgreement shape "
                "and was not evaluated."
            ),
            rule_id=f"yacal-skip:{rule_id}",
            spec_ref=spec,
        ))
        return

    for loc in container_locations:
        for path_str, container in eval_path(root, loc):
            if not isinstance(container, dict):
                continue
            parent_val = container.get(parent_prop)
            if parent_val is None:
                continue

            if child_coll:
                children = container.get(child_coll, [])
                if not isinstance(children, list):
                    children = [children]
                for i, child in enumerate(children):
                    if not isinstance(child, dict):
                        continue
                    child_val = child.get(child_prop)
                    if child_val is not None and child_val != parent_val:
                        out.append(ValidationIssue(
                            severity=Severity.ERROR,
                            message=(
                                f"DataType mismatch at {path_str}: "
                                f"parent {parent_prop}={parent_val!r}, "
                                f"but {child_coll}[{i}].{child_prop}={child_val!r}"
                            ),
                            path=f"{path_str}.{child_coll}[{i}]",
                            rule_id=f"yacal:{rule_id}",
                            spec_ref=spec,
                        ))
            elif child_expr:
                matches = _resolve_relative(container, child_expr)
                for child_path, child in matches:
                    if not isinstance(child, dict):
                        continue
                    child_val = child.get(child_prop)
                    if child_val is not None and child_val != parent_val:
                        out.append(ValidationIssue(
                            severity=Severity.ERROR,
                            message=(
                                f"DataType mismatch at {path_str}: "
                                f"parent {parent_prop}={parent_val!r}, "
                                f"but {child_expr}.{child_prop}={child_val!r}"
                            ),
                            path=f"{path_str}.{child_expr}",
                            rule_id=f"yacal:{rule_id}",
                            spec_ref=spec,
                        ))


def _reference_must_resolve(root: Any, rule: dict, out: list[ValidationIssue]) -> None:
    rule_id = rule["Id"]
    spec = _provenance(rule)
    ref_path = rule.get("ReferencePath", "")
    target_coll_path = rule.get("TargetCollectionPath", "")
    target_key = rule.get("TargetKeyProperty")

    if not (ref_path and target_coll_path and target_key):
        return

    valid: set[Any] = set()
    for _, targets in eval_path(root, target_coll_path):
        if isinstance(targets, list):
            for t in targets:
                if isinstance(t, dict) and target_key in t:
                    valid.add(t[target_key])
        elif isinstance(targets, dict) and target_key in targets:
            valid.add(targets[target_key])

    for ref_str, ref_val in eval_path(root, ref_path):
        if ref_val not in valid:
            out.append(ValidationIssue(
                severity=Severity.ERROR,
                message=f"Reference {ref_val!r} at {ref_str} does not resolve to any {target_key}",
                path=ref_str,
                rule_id=f"yacal:{rule_id}",
                spec_ref=spec,
            ))


def _unique_by_derived_set(root: Any, rule: dict, out: list[ValidationIssue]) -> None:
    rule_id = rule["Id"]
    spec = _provenance(rule)
    coll_path = rule.get("CollectionPath", "")
    derived_path = rule.get("DerivedSetPath", "")

    for coll_str, coll in eval_path(root, coll_path):
        if not isinstance(coll, list):
            continue
        seen_sets: list[tuple[frozenset, str]] = []
        for idx, item in enumerate(coll):
            if not isinstance(item, dict):
                continue
            vals: list[Any] = []
            for _, v in _resolve_relative(item, derived_path):
                if isinstance(v, list):
                    vals.extend(v)
                elif v is not None:
                    vals.append(v)
            derived = frozenset(vals)
            item_path = f"{coll_str}[{idx}]"
            for prev, prev_path in seen_sets:
                if derived == prev:
                    out.append(ValidationIssue(
                        severity=Severity.ERROR,
                        message=f"Duplicate derived set at {item_path} (same as {prev_path})",
                        path=item_path,
                        rule_id=f"yacal:{rule_id}",
                        spec_ref=spec,
                    ))
                    break
            seen_sets.append((derived, item_path))


def _no_nested_expression_kind(root: Any, rule: dict, out: list[ValidationIssue]) -> None:
    rule_id = rule["Id"]
    spec = _provenance(rule)
    expr_path = rule.get("ExpressionPath", "")
    prohibited = rule.get("ProhibitedWrapperKey")

    if not prohibited:
        return

    for path_str, expr in eval_path(root, expr_path):
        for found_path, _ in _descend(expr, prohibited, path_str):
            out.append(ValidationIssue(
                severity=Severity.ERROR,
                message=f"Prohibited expression type '{prohibited}' found at {found_path}",
                path=found_path,
                rule_id=f"yacal:{rule_id}",
                spec_ref=spec,
            ))


def _graph_acyclic(root: Any, rule: dict, out: list[ValidationIssue]) -> None:
    rule_id = rule["Id"]
    spec = _provenance(rule)
    applies = rule.get("AppliesTo", {}) or {}
    id_prop = applies.get("NodeIdentityProperty")
    ref_prop = applies.get("ReferencePath")
    locations = applies.get("ObjectLocations", []) or []

    if not (id_prop and ref_prop and locations):
        return

    nodes: dict[Any, Any] = {}
    for loc in locations:
        for _, node in eval_path(root, loc):
            if isinstance(node, dict) and id_prop in node:
                nodes[node[id_prop]] = node

    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[Any, int] = {nid: WHITE for nid in nodes}

    def dfs(nid: Any) -> bool:
        color[nid] = GRAY
        node = nodes[nid]
        refs = node.get(ref_prop, [])
        if isinstance(refs, str):
            refs = [refs]
        if isinstance(refs, list):
            for ref in refs:
                if ref not in color:
                    continue
                if color[ref] == GRAY:
                    return True
                if color[ref] == WHITE and dfs(ref):
                    return True
        color[nid] = BLACK
        return False

    for nid in list(nodes):
        if color[nid] == WHITE:
            if dfs(nid):
                out.append(ValidationIssue(
                    severity=Severity.ERROR,
                    message=f"Cycle detected in {rule_id} graph involving '{nid}'",
                    rule_id=f"yacal:{rule_id}",
                    spec_ref=spec,
                ))


def _graph_no_repeat(root: Any, rule: dict, out: list[ValidationIssue]) -> None:
    rule_id = rule["Id"]
    spec = _provenance(rule)
    applies = rule.get("AppliesTo", {}) or {}
    id_prop = applies.get("NodeIdentityProperty")
    ref_prop = applies.get("ReferencePath")
    locations = applies.get("ObjectLocations", []) or []

    if not (id_prop and ref_prop and locations):
        return

    nodes: dict[Any, Any] = {}
    for loc in locations:
        for _, node in eval_path(root, loc):
            if isinstance(node, dict) and id_prop in node:
                nodes[node[id_prop]] = node

    def walk(nid: Any, visited: set) -> bool:
        node = nodes.get(nid)
        if not node:
            return False
        refs = node.get(ref_prop, [])
        if isinstance(refs, str):
            refs = [refs]
        if not isinstance(refs, list):
            return False
        for ref in refs:
            if ref in visited:
                return True
            visited.add(ref)
            if walk(ref, visited):
                return True
        return False

    for nid in nodes:
        refs = nodes[nid].get(ref_prop, [])
        if isinstance(refs, str):
            refs = [refs]
        if isinstance(refs, list) and len(refs) != len(set(refs)):
            out.append(ValidationIssue(
                severity=Severity.ERROR,
                message=f"Node '{nid}' directly references another node more than once ({rule_id})",
                rule_id=f"yacal:{rule_id}",
                spec_ref=spec,
            ))
        if walk(nid, set(refs)):
            out.append(ValidationIssue(
                severity=Severity.ERROR,
                message=f"Node '{nid}' indirectly revisits a node in the {rule_id} graph",
                rule_id=f"yacal:{rule_id}",
                spec_ref=spec,
            ))


_CHECKERS = {
    "uniqueByProperty": _unique_by_property,
    "uniqueByConcreteSubtype": _unique_by_concrete_subtype,
    "nonEmptyWhenPresent": _non_empty_when_present,
    "conditionalPresence": _conditional_presence,
    "propertyAgreement": _property_agreement,
    "referenceMustResolve": _reference_must_resolve,
    "uniqueByDerivedSet": _unique_by_derived_set,
    "noNestedExpressionKind": _no_nested_expression_kind,
    "graphMustBeAcyclic": _graph_acyclic,
    "graphMustNotRepeatNode": _graph_no_repeat,
}


def evaluate(document: Any, catalog: dict) -> list[ValidationIssue]:
    """Run every rule in *catalog* against *document*. Return all issues found."""
    issues: list[ValidationIssue] = []
    for rule in catalog.get("Rule", []) or []:
        kind = rule.get("Kind")
        checker = _CHECKERS.get(kind)
        if checker:
            try:
                checker(document, rule, issues)
            except Exception as exc:
                issues.append(ValidationIssue(
                    severity=Severity.WARNING,
                    message=f"Constraint '{rule.get('Id', '?')}' could not be evaluated: {exc}",
                    rule_id=f"yacal-eval-error:{rule.get('Id', '?')}",
                ))
    return issues
