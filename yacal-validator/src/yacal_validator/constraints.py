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
    applies_to = rule.get("AppliesTo", {}) or {}
    coll_path = applies_to.get("CollectionPath", "")
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
    applies_to = rule.get("AppliesTo", {}) or {}
    coll_path = applies_to.get("CollectionPath", "")
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
    applies_to = rule.get("AppliesTo", {}) or {}
    container_path = applies_to.get("ContainerPath", "")
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
    applies_to = rule.get("AppliesTo", {}) or {}
    container_path = applies_to.get("ContainerPath", "")
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


def _build_resolution_index(document: Any) -> dict:
    """Index SharedVariableDefinition and Policy entries from a Bundle for within-document lookup.

    Returns {"shared_vars": {Id: [ParameterType]}, "policies": {PolicyId: [ParameterType]}}.
    """
    shared_vars: dict[str, list] = {}
    policies: dict[str, list] = {}
    if not isinstance(document, dict):
        return {"shared_vars": shared_vars, "policies": policies}
    bundle = document.get("Bundle")
    if isinstance(bundle, dict):
        for svd in bundle.get("SharedVariableDefinition") or []:
            if isinstance(svd, dict) and "Id" in svd:
                shared_vars[str(svd["Id"])] = list(svd.get("Parameter") or [])
        for policy in bundle.get("Policy") or []:
            if isinstance(policy, dict) and "PolicyId" in policy:
                policies[str(policy["PolicyId"])] = list(policy.get("Parameter") or [])
    return {"shared_vars": shared_vars, "policies": policies}


def _check_argument_datatype_agreement(
    ref: dict,
    params: list,
    ref_path: str,
    rule_id: str,
    spec: str | None,
    out: list[ValidationIssue],
) -> None:
    """Check that Value-typed arguments agree with the declared parameter DataTypes.

    Handles positional arguments (matched by index) and named arguments
    (NamedArgument.Name matched against Parameter.Name).
    Only fires when both the parameter declares DataType AND the argument
    supplies an explicit Value with DataType — as required by the spec.
    """
    if not params:
        return
    arguments = ref.get("Argument") or []
    if not isinstance(arguments, list):
        return

    param_by_name = {
        p["Name"]: p for p in params if isinstance(p, dict) and "Name" in p
    }

    for idx, arg_item in enumerate(arguments):
        if not isinstance(arg_item, dict):
            continue

        matched_param: dict | None = None
        arg_datatype: str | None = None

        if "NamedArgument" in arg_item:
            named = arg_item["NamedArgument"]
            if isinstance(named, dict):
                param_name = named.get("Name")
                matched_param = param_by_name.get(param_name) if param_name else None
                # NamedArgumentType.Expression contains the value expression
                expr = named.get("Expression")
                if isinstance(expr, dict):
                    val = expr.get("Value")
                    if isinstance(val, dict):
                        arg_datatype = val.get("DataType")
        else:
            # Positional: argument at index idx matches parameter at index idx
            if idx < len(params) and isinstance(params[idx], dict):
                matched_param = params[idx]
            val = arg_item.get("Value")
            if isinstance(val, dict):
                arg_datatype = val.get("DataType")

        if matched_param is None or arg_datatype is None:
            continue

        param_datatype = matched_param.get("DataType")
        if param_datatype is None:
            continue

        if str(arg_datatype) != str(param_datatype):
            param_name = matched_param.get("Name", str(idx))
            out.append(ValidationIssue(
                severity=Severity.ERROR,
                message=(
                    f"DataType mismatch at {ref_path}: argument {idx} "
                    f"specifies DataType={arg_datatype!r} but parameter "
                    f"{param_name!r} requires {param_datatype!r}"
                ),
                path=f"{ref_path}.Argument[{idx}]",
                rule_id=f"yacal:{rule_id}",
                spec_ref=spec,
            ))


def _property_agreement(
    root: Any, rule: dict, out: list[ValidationIssue], context: dict | None = None
) -> None:
    rule_id = rule["Id"]
    spec = _provenance(rule)
    resolution = rule.get("Resolution", {}) or {}

    if resolution.get("RequiresReferencedSharedVariableLookup"):
        applies_to = rule.get("AppliesTo", {}) or {}
        shared_var_index = (context or {}).get("shared_vars", {})
        for loc in applies_to.get("ContainerLocations", []) or []:
            for ref_path, ref in eval_path(root, loc):
                if not isinstance(ref, dict):
                    continue
                ref_id = str(ref.get("Id", "")) if ref.get("Id") is not None else None
                if ref_id is None:
                    continue
                if ref_id not in shared_var_index:
                    out.append(ValidationIssue(
                        severity=Severity.WARNING,
                        message=(
                            f"Constraint '{rule_id}': SharedVariableReference {ref_id!r} at "
                            f"{ref_path} resolves to an external definition; "
                            "cross-document DataType agreement not checked. "
                            "Use --include to provide the definition file."
                        ),
                        rule_id=f"yacal-skip:{rule_id}",
                        spec_ref=spec,
                    ))
                else:
                    _check_argument_datatype_agreement(
                        ref, shared_var_index[ref_id], ref_path, rule_id, spec, out
                    )
        return

    if resolution.get("RequiresReferencedPolicyLookup"):
        applies_to = rule.get("AppliesTo", {}) or {}
        policy_index = (context or {}).get("policies", {})
        for loc in applies_to.get("ContainerLocations", []) or []:
            for ref_path, ref in eval_path(root, loc):
                if not isinstance(ref, dict):
                    continue
                ref_id = str(ref.get("Id", "")) if ref.get("Id") is not None else None
                if ref_id is None:
                    continue
                if ref_id not in policy_index:
                    out.append(ValidationIssue(
                        severity=Severity.WARNING,
                        message=(
                            f"Constraint '{rule_id}': PolicyReference {ref_id!r} at "
                            f"{ref_path} resolves to an external definition; "
                            "cross-document DataType agreement not checked. "
                            "Use --include to provide the definition file."
                        ),
                        rule_id=f"yacal-skip:{rule_id}",
                        spec_ref=spec,
                    ))
                else:
                    _check_argument_datatype_agreement(
                        ref, policy_index[ref_id], ref_path, rule_id, spec, out
                    )
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
    applies_to = rule.get("AppliesTo", {}) or {}
    ref_path = applies_to.get("ReferencePath", "")
    target_coll_path = applies_to.get("TargetCollectionPath", "")
    target_key = applies_to.get("TargetKeyProperty")

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
    applies_to = rule.get("AppliesTo", {}) or {}
    coll_path = applies_to.get("CollectionPath", "")
    derived_path = applies_to.get("DerivedSetPath", "")

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
    applies_to = rule.get("AppliesTo", {}) or {}
    expr_path = applies_to.get("ExpressionPath", "")
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
        if walk(nid, set()):
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


# ---------------------------------------------------------------------------
# Supplementary checks (fill catalog gaps / fix catalog path bugs)
# ---------------------------------------------------------------------------

def _find_all(document: Any, key: str) -> list[tuple[str, Any]]:
    """Recursively collect all values at *key* anywhere in the document tree."""
    results: list[tuple[str, Any]] = []

    def _walk(obj: Any, path: str) -> None:
        if isinstance(obj, dict):
            if key in obj:
                results.append((f"{path}.{key}" if path else key, obj[key]))
            for k, v in obj.items():
                _walk(v, f"{path}.{k}" if path else k)
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                _walk(item, f"{path}[{i}]")

    _walk(document, "")
    return results


def _check_rule_id_unique_within_policy(document: Any, out: list[ValidationIssue]) -> None:
    # Catalog gap: no constraint covers Rule.Id uniqueness within Policy.CombinerInput.
    # Rule IDs must be unique within each policy (they are used as identifiers in evaluation).
    spec = "YACAL §5.3.2 / ACAL §7.6"
    for policy_path, policy in _find_all(document, "Policy"):
        if not isinstance(policy, dict):
            continue
        combiner_input = policy.get("CombinerInput", [])
        if not isinstance(combiner_input, list):
            continue
        seen: dict[Any, str] = {}
        for idx, entry in enumerate(combiner_input):
            if not isinstance(entry, dict):
                continue
            rule = entry.get("Rule")
            if not isinstance(rule, dict):
                continue
            rule_id_val = rule.get("Id")
            if rule_id_val is None:
                continue
            item_path = f"{policy_path}.CombinerInput[{idx}].Rule"
            if rule_id_val in seen:
                out.append(ValidationIssue(
                    severity=Severity.ERROR,
                    message=(
                        f"Duplicate Rule Id {rule_id_val!r} at {item_path}; "
                        f"first at {seen[rule_id_val]}"
                    ),
                    path=item_path,
                    rule_id="yacal:rule-id-unique-within-policy",
                    spec_ref=spec,
                ))
            else:
                seen[rule_id_val] = item_path


def _check_shortid_name_unique(document: Any, out: list[ValidationIssue]) -> None:
    # Catalog bug: shortidset-shortid-name-unique has path $.ShortIdSet[].ShortId which
    # matches no real document form (standalone ShortIdSetDocument has a single ShortIdSet,
    # not an array; Bundle uses $.Bundle.ShortIdSet[]).
    # This supplementary check finds all ShortIdSet objects at any depth and enforces
    # the uniqueness requirement directly.
    spec = "YACAL §5.11.2 / ACAL §7.2"
    for sid_path, shortidset in _find_all(document, "ShortIdSet"):
        # ShortIdSet may be a single object or a list (in Bundle)
        items = shortidset if isinstance(shortidset, list) else [shortidset]
        for obj_idx, obj in enumerate(items):
            if not isinstance(obj, dict):
                continue
            obj_path = f"{sid_path}[{obj_idx}]" if isinstance(shortidset, list) else sid_path
            short_ids = obj.get("ShortId", [])
            if not isinstance(short_ids, list):
                continue
            seen: dict[Any, str] = {}
            for i, sid in enumerate(short_ids):
                if not isinstance(sid, dict):
                    continue
                name = sid.get("Name")
                if name is None:
                    continue
                item_path = f"{obj_path}.ShortId[{i}]"
                if name in seen:
                    out.append(ValidationIssue(
                        severity=Severity.ERROR,
                        message=(
                            f"Duplicate ShortId Name {name!r} at {item_path}; "
                            f"first at {seen[name]}"
                        ),
                        path=item_path,
                        rule_id="yacal:shortidset-shortid-name-unique",
                        spec_ref=spec,
                    ))
                else:
                    seen[name] = item_path


_SUPPLEMENTARY_CHECKS = [
    _check_rule_id_unique_within_policy,
    _check_shortid_name_unique,
]


def evaluate(
    document: Any, catalog: dict
) -> tuple[list[ValidationIssue], int, int, int]:
    """Run every rule in *catalog* against *document*, plus supplementary checks.

    Returns (issues, total, evaluated, skipped).
    - total:     catalog rules with a known Kind + supplementary checks
    - evaluated: rules/checks that ran to completion
    - skipped:   rules that emitted a yacal-skip issue (cross-document dependency)
    """
    issues: list[ValidationIssue] = []
    total = 0
    evaluated = 0
    skipped = 0

    context = _build_resolution_index(document)

    for rule in catalog.get("Rule", []) or []:
        kind = rule.get("Kind")
        checker = _CHECKERS.get(kind)
        if not checker:
            continue
        total += 1
        before = len(issues)
        try:
            if kind == "propertyAgreement":
                checker(document, rule, issues, context=context)
            else:
                checker(document, rule, issues)
        except Exception as exc:
            issues.append(ValidationIssue(
                severity=Severity.WARNING,
                message=f"Constraint '{rule.get('Id', '?')}' could not be evaluated: {exc}",
                rule_id=f"yacal-eval-error:{rule.get('Id', '?')}",
            ))
        new_issues = issues[before:]
        if any((i.rule_id or "").startswith("yacal-skip:") for i in new_issues):
            skipped += 1
        else:
            evaluated += 1

    for check in _SUPPLEMENTARY_CHECKS:
        total += 1
        try:
            check(document, issues)
        except Exception as exc:
            issues.append(ValidationIssue(
                severity=Severity.WARNING,
                message=f"Supplementary check '{check.__name__}' could not be evaluated: {exc}",
                rule_id=f"yacal-eval-error:{check.__name__}",
            ))
        evaluated += 1

    return issues, total, evaluated, skipped
