"""Cedar (AWS) reader — converts a Cedar policy to a neutral ACAL dict.

Cedar is a foreign spoke (see ../../../CLAUDE.md for the hub/spoke frame). Parsing is done by
Cedar's own Rust parser via ``cedarpy.policies_to_json_str``, which yields Cedar's official
JSON AST (the EST); we map that AST rather than parsing Cedar ourselves, so our understanding
of Cedar cannot silently diverge from Cedar's.

Design decisions and their reasoning live in:
  - acal-core/capabilities/cedar.yaml                       (matrix, datatype ladder, decisions)
  - acal-core/docs/policy-language-expressiveness.md        (prose, combining truth table)
  - diary/architectural_decisions.md                        (presence-semantics, datatype ladder)

Two behaviours worth stating at the top because they are load-bearing and non-obvious:

1. Combining. Cedar allows iff some permit matches AND no forbid matches, else deny. This is
   reproduced as an outer deny-unless-permit Policy wrapping an inner deny-overrides Policy.
   Any flatter encoding silently turns a forbid into a no-op.

2. Missing attributes. Cedar fails open — a policy whose attribute is absent errors, is
   skipped, and the request is allowed (verified against cedarpy.is_authorized). We reproduce
   that with MustBePresent: false and report it, rather than silently hardening. fail_closed=True
   emits MustBePresent: true instead, as a declared deviation.
"""
from __future__ import annotations

import warnings
from typing import Any

# ACAL identifier shorthands. YACAL/JACAL accept the {name} brace form for reserved URNs.
_SUBJECT = "urn:oasis:names:tc:acal:1.0:subject-category:access-subject"
_ACTION = "urn:oasis:names:tc:acal:1.0:attribute-category:action"
_RESOURCE = "urn:oasis:names:tc:acal:1.0:attribute-category:resource"
_ENV = "urn:oasis:names:tc:acal:1.0:attribute-category:environment"

_FN = "urn:oasis:names:tc:acal:1.0:function"
_DENY_OVERRIDES = "urn:oasis:names:tc:acal:1.0:combining-algorithm:deny-overrides"
_DENY_UNLESS_PERMIT = "urn:oasis:names:tc:acal:1.0:combining-algorithm:deny-unless-permit"

# Reserved attributes carrying Cedar's entity model, which ACAL's flat categories lack.
_ENTITY_UID = "urn:cedar:1.0:entity-uid"
_ENTITY_TYPE = "urn:cedar:1.0:entity-type"
_ENTITY_ANCESTORS = "urn:cedar:1.0:entity-ancestors"

# Cedar's four request variables → ACAL attribute categories.
_VAR_CATEGORY = {
    "principal": _SUBJECT,
    "action": _ACTION,
    "resource": _RESOURCE,
    "context": _ENV,
}


class CedarSyntaxError(ValueError):
    """Raised when the input is not valid Cedar (parse failure)."""


class CedarUnsupportedFeatureError(ValueError):
    """Raised when a Cedar construct has no faithful ACAL mapping (disposition c),
    or when a disposition-(b) construct is met under strict mode."""


def load(path: str, strict: bool = False, fail_closed: bool = False) -> dict:
    """Parse a Cedar file and return a neutral ACAL dict.

    strict: promote every disposition-(b) warning to CedarUnsupportedFeatureError.
    fail_closed: emit MustBePresent: true on synthesized designators (deny where Cedar would
        allow on a missing attribute) — a declared deviation from Cedar's fail-open semantics.
    """
    try:
        import cedarpy
    except ImportError as exc:  # pragma: no cover - environment-dependent
        raise CedarUnsupportedFeatureError(
            "Reading Cedar policies requires the 'cedarpy' package (Cedar's own parser). "
            "Install it with:  pip install 'acal-core[cedar]'"
        ) from exc

    import json

    with open(path, encoding="utf-8") as fh:
        source = fh.read()

    try:
        est = json.loads(cedarpy.policies_to_json_str(source))
    except Exception as exc:
        # cedarpy raises a bare ValueError for syntax errors; distinguish it as ours.
        raise CedarSyntaxError(f"Cedar syntax error in {path!r}: {exc}") from exc

    return _Converter(strict=strict, fail_closed=fail_closed).convert(est)


# Cedar extension-type constructors → the datatype-map key they belong to. Cedar spells the
# ipaddr constructor `ip`, so the two names differ; everything else matches its type key.
_CONSTRUCTORS = {
    "decimal": "decimal",
    "datetime": "datetime",
    "duration": "duration",
    "ip": "ipaddr",
}


class _Converter:
    def __init__(self, strict: bool = False, fail_closed: bool = False) -> None:
        self._strict = strict
        self._fail_closed = fail_closed
        self._datamap = _load_datamap()
        # function name → (acal_function_suffix, owning_type, fidelity). Two datatypes must not
        # claim the same Cedar method name: the EST does not tell us an expression's type, so a
        # collision would silently map (say) a datetime lessThan to decimal's double-less-than.
        # A datamap that does this is misconfigured — fail loudly at construction, not at a
        # silent wrong mapping later.
        self._ext_functions: dict[str, tuple[str, str, str]] = {}
        for type_name, spec in self._datamap.items():
            fidelity = spec.get("fidelity", "exact")
            for cedar_fn, acal_fn in (spec.get("functions") or {}).items():
                if cedar_fn in self._ext_functions:
                    other = self._ext_functions[cedar_fn][1]
                    raise CedarUnsupportedFeatureError(
                        f"capabilities/cedar.yaml maps the Cedar function {cedar_fn!r} under both "
                        f"{other!r} and {type_name!r}. The EST carries no type at the call site, "
                        "so the reader cannot disambiguate — give each type distinct function names."
                    )
                self._ext_functions[cedar_fn] = (_suffix(acal_fn), type_name, fidelity)
        # approximate types already reported, so we warn once per type, not per use.
        self._noted_approximate: set[str] = set()

    def _warn_or_raise(self, msg: str) -> None:
        if self._strict:
            raise CedarUnsupportedFeatureError(msg)
        warnings.warn(msg, UserWarning, stacklevel=2)

    def _note_approximate(self, type_name: str) -> None:
        """Warn (or raise under --strict) the first time an approximate type is used."""
        if type_name in self._noted_approximate:
            return
        self._noted_approximate.add(type_name)
        note = (self._datamap.get(type_name, {}) or {}).get("note", "").strip()
        self._warn_or_raise(
            f"Cedar {type_name} maps to an approximate ACAL type; a decision may differ at a "
            f"value boundary. {note}"
        )

    def _resolve_constructor(self, type_key: str, args: list) -> dict:
        """A Cedar type constructor (decimal(...), ip(...)) → a typed ACAL value.

        Walks the datatype ladder: no acal_type -> hard error naming the missing entry;
        approximate -> warn; then unwrap the single literal argument.
        """
        spec = self._datamap.get(type_key)
        if spec is None or spec.get("acal_type") is None:
            note = (spec or {}).get("note", "").strip()
            raise CedarUnsupportedFeatureError(
                f"Cedar type {type_key!r} has no ACAL mapping. {note} "
                f"Add a datatypes.{type_key} entry with an acal_type to capabilities/cedar.yaml."
            )
        if spec.get("fidelity") == "approximate":
            self._note_approximate(type_key)
        if len(args) == 1 and isinstance(args[0], dict) and "Value" in args[0]:
            return {"Value": _coerce_literal(args[0]["Value"], spec["acal_type"])}
        # Non-literal constructor argument (e.g. ip(context.raw)) — not expressible.
        raise CedarUnsupportedFeatureError(
            f"Cedar {type_key}(...) with a non-literal argument has no ACAL mapping."
        )

    # -- presence ---------------------------------------------------------------------------

    def _designator(self, category: str, attribute_id: str, *, has_context: bool = False) -> dict:
        """An AttributeDesignator with presence semantics reproducing Cedar.

        has_context=True is used inside a `has` operand, where "is this attribute present?" is
        exactly the question — so MustBePresent stays False even under fail_closed, or the guard
        Cedar policies use to avoid the missing-attribute error would itself become Indeterminate.
        """
        d = {"Category": category, "AttributeId": attribute_id}
        d["MustBePresent"] = bool(self._fail_closed) and not has_context
        return {"AttributeDesignator": d}

    # -- top level --------------------------------------------------------------------------

    _MAIN_ID = "urn:cedar:policy:main"

    def convert(self, est: dict) -> dict:
        templates = est.get("templates") or {}
        static = est.get("staticPolicies") or {}

        # NB: `templateLinks` is intentionally not read. Cedar template *links* are runtime
        # instantiations supplied through the policy-set / entities API, never present in
        # policy *text* — policies_to_json_str() always returns templateLinks: []. So a
        # template in a .cedar file is uninstantiated: it binds to nothing and participates
        # in no decision. It is carried across as an inert parameterized definition (disp. b).

        template_policies: list[dict] = []
        for pid, tmpl in templates.items():
            template_policies.append(self._template_policy(pid, tmpl))
            self._warn_or_raise(
                f"Cedar template {tmpl.get('annotations', {}).get('id', pid)!r} is "
                "uninstantiated — template links are runtime instantiations absent from policy "
                "text. It is converted as a parameterized definition that participates in no "
                "decision until referenced."
            )

        # Static policies all land in one inner deny-overrides policy, so their Rule Ids must be
        # unique there. Cedar @id annotations are not guaranteed unique across policies, and a
        # collision would produce a document our own validator rejects (rule-id uniqueness).
        # Disambiguate on collision, preserving the author's id as the stem, and report it.
        rules: list[dict] = []
        seen_ids: set[str] = set()
        for pid, pol in static.items():
            rule = self._rule(pid, pol)
            if rule["Id"] in seen_ids:
                # '.' is a legal LocalIdentifierType separator; ':' is not.
                disambiguated = f"{rule['Id']}.{pid}"
                self._warn_or_raise(
                    f"Two Cedar policies share the id {rule['Id']!r}; ACAL rule ids must be "
                    f"unique within a policy, so this one was renamed to {disambiguated!r}."
                )
                rule["Id"] = disambiguated
            seen_ids.add(rule["Id"])
            rules.append({"Rule": rule})

        # The active policy: Cedar's combining semantics, outer deny-unless-permit ▸ inner
        # deny-overrides. See the truth table in docs/policy-language-expressiveness.md.
        main = None
        if rules:
            main = {
                "PolicyId": self._MAIN_ID,
                "Version": "1.0",
                "CombiningAlgId": _DENY_UNLESS_PERMIT,
                "CombinerInput": [
                    {
                        "Policy": {
                            "PolicyId": "urn:cedar:policy:main-inner",
                            "Version": "1.0",
                            "CombiningAlgId": _DENY_OVERRIDES,
                            "CombinerInput": rules,
                        }
                    }
                ],
            }

        # Structure by what is present:
        #  - active rules, no templates  → a single top-level Policy (no pool, no ambiguity)
        #  - templates present           → a Bundle: templates are the definition pool, and the
        #                                   entry point is named explicitly by PolicyReference
        #                                   so there is no ambiguity about which policy decides
        if not template_policies:
            if main is None:
                raise CedarUnsupportedFeatureError(
                    "The Cedar document contains no policies to convert."
                )
            return {"Policy": main}

        pool = list(template_policies)
        bundle: dict[str, Any] = {"Policy": pool}
        if main is not None:
            pool.append(main)
            bundle["PolicyReference"] = {"Id": self._MAIN_ID, "Version": "1.0"}
        else:
            # Templates only: a definition library with no active policy. Faithful to a Cedar
            # file of uninstantiated templates, which likewise decides nothing.
            self._warn_or_raise(
                "The Cedar document contains only uninstantiated templates and expresses no "
                "active policy; the converted Bundle has no decision entry point."
            )
        return {"Bundle": bundle}

    # -- rules ------------------------------------------------------------------------------

    def _rule(self, policy_id: str, pol: dict) -> dict:
        rule: dict[str, Any] = {}
        annotations = pol.get("annotations") or {}
        # Cedar @id is an arbitrary annotation string; ACAL Rule Ids are LocalIdentifierType
        # (letter-led, [A-Za-z0-9_] with -/. separators). policy_id (cedarpy's policyN) is always
        # valid, so it is the fallback when an @id cannot be sanitized to a legal identifier.
        raw_id = annotations.get("id")
        if raw_id is None:
            rule["Id"] = policy_id
        else:
            sanitized, changed = _sanitize_local_id(raw_id, fallback=policy_id)
            if changed:
                self._warn_or_raise(
                    f"Cedar @id {raw_id!r} is not a valid ACAL identifier; using {sanitized!r}."
                )
            rule["Id"] = sanitized
        rule["Effect"] = "Permit" if pol["effect"] == "permit" else "Deny"

        for name in annotations:
            if name != "id":
                self._warn_or_raise(
                    f"Cedar annotation @{name} has no ACAL equivalent and was dropped. "
                    "Cedar annotations other than @id carry no evaluation semantics."
                )

        conditions = self._scope_and_conditions(pol)
        if conditions is not None:
            rule["Condition"] = conditions
        return rule

    def _template_policy(self, policy_id: str, tmpl: dict) -> dict:
        """A Cedar template → an ACAL Policy with Parameter declarations."""
        params: list[dict] = []
        for slot in _template_slots(tmpl):
            params.append({"Name": slot.lstrip("?"), "DataType": "{string}"})

        inner_rule = self._rule(policy_id, tmpl)
        policy: dict[str, Any] = {
            "PolicyId": f"urn:cedar:template:{policy_id}",
            "Version": "1.0",
            "CombiningAlgId": _DENY_OVERRIDES,
        }
        if params:
            policy["Parameter"] = params
        policy["CombinerInput"] = [{"Rule": inner_rule}]
        return policy

    # -- scope + when/unless ----------------------------------------------------------------

    def _scope_and_conditions(self, pol: dict) -> dict | None:
        """Combine scope constraints and when/unless clauses into one ACAL Condition.

        Cedar semantics: a policy applies iff the scope matches AND every `when` is true AND
        every `unless` is false. That is a conjunction, with each `unless` negated.
        """
        terms: list[dict] = []

        terms.extend(self._scope_terms("principal", pol.get("principal") or {"op": "All"}))
        terms.extend(self._scope_terms("action", pol.get("action") or {"op": "All"}))
        terms.extend(self._scope_terms("resource", pol.get("resource") or {"op": "All"}))

        for cond in pol.get("conditions") or []:
            expr = self._expr(cond["body"])
            if cond["kind"] == "unless":
                expr = _apply("not", [expr])
            terms.append(expr)

        if not terms:
            return None
        if len(terms) == 1:
            return terms[0]
        return _apply("and", terms)

    def _scope_terms(self, var: str, scope: dict) -> list[dict]:
        op = scope.get("op")
        if op == "All":
            return []
        category = _VAR_CATEGORY[var]
        # In a template the operand is a ?slot rather than a literal entity; it becomes a
        # VariableReference to the Policy Parameter of the same name.
        if "slot" in scope:
            operand = {"VariableReference": {"VariableId": scope["slot"].lstrip("?")}}
        else:
            operand = None
        if op == "==":
            lhs = operand or {"Value": _entity_uid_string(scope["entity"])}
            return [_apply("string-equal", [lhs, self._designator(category, _ENTITY_UID)])]
        if op == "is":
            return [_apply("string-equal", [
                {"Value": scope["entity_type"]},
                self._designator(category, _ENTITY_TYPE),
            ])]
        if op == "in":
            lhs = operand or {"Value": _entity_uid_string(scope["entity"])}
            return [_apply("string-is-in", [lhs, self._designator(category, _ENTITY_ANCESTORS)])]
        raise CedarUnsupportedFeatureError(
            f"Cedar scope operator {op!r} on {var} is not recognised."
        )

    # -- expression tree --------------------------------------------------------------------

    _BINARY_FN = {
        "&&": "and",
        "||": "or",
        "==": "string-equal",       # overridden by literal type where inferable
        "<": "integer-less-than",
        "<=": "integer-less-than-or-equal",
        ">": "integer-greater-than",
        ">=": "integer-greater-than-or-equal",
        "+": "integer-add",
        "-": "integer-subtract",
        "*": "integer-multiply",
    }

    def _expr(self, node: dict) -> dict:
        if not isinstance(node, dict) or len(node) != 1:
            raise CedarUnsupportedFeatureError(f"Unrecognised Cedar expression node: {node!r}")
        (key, val), = node.items()

        if key == "Value":
            return {"Value": val}
        if key == "Var":
            # A bare variable reference in expression position (e.g. RHS `principal`).
            return self._designator(_VAR_CATEGORY.get(val, _ENV), _ENTITY_UID)
        if key == ".":
            return self._attr_access(val)
        if key == "Set":
            prefix = _type_prefix(node)  # element type where the members make it knowable
            return _apply(f"{prefix}-bag", [self._expr(e) for e in val])

        if key in self._BINARY_FN:
            return self._binary(key, val)
        if key == "!":
            return _apply("not", [self._expr(val["arg"] if "arg" in val else val)])
        if key == "!=":
            return _apply("not", [self._binary("==", val)])
        if key == "has":
            return self._has(val)
        if key in ("contains", "containsAny"):
            # `contains`: is the needle (right) in the set (left). `containsAny`: do the two
            # sets (left, right) share a member. Element type is inferred from whichever
            # operand the EST makes knowable.
            prefix = _type_prefix(val["right"], val["left"])
            op = "is-in" if key == "contains" else "at-least-one-member-of"
            return _apply(f"{prefix}-{op}", [self._expr(val["right"]), self._expr(val["left"])])
        if key == "containsAll":
            prefix = _type_prefix(val["right"], val["left"])
            return _apply(f"{prefix}-subset", [self._expr(val["right"]), self._expr(val["left"])])
        if key == "like":
            return self._like(val)
        if key in ("if-then-else", "if"):
            return self._if_then_else(val)

        # Extension-type constructors (decimal("0.5"), ip("10.0.0.1"), datetime(...)) walk the
        # datatype ladder: mapped-and-maybe-approximate, or a hard error naming the entry.
        if key in _CONSTRUCTORS:
            return self._resolve_constructor(_CONSTRUCTORS[key], val if isinstance(val, list) else [val])

        # Extension-type methods (x.lessThan(y), a.toDate()) resolve via the datamap's
        # per-type `functions:` maps.
        if key in self._ext_functions:
            acal_fn, type_name, fidelity = self._ext_functions[key]
            if fidelity == "approximate":
                self._note_approximate(type_name)
            operands = val if isinstance(val, list) else [val.get("left"), val.get("right")]
            return _apply(acal_fn, [self._expr(o) for o in operands])

        # Everything else — records, and any extension function with no datamap entry — is a
        # hard error naming the fix, never a silent drop.
        raise CedarUnsupportedFeatureError(
            f"Cedar operator/construct {key!r} has no ACAL mapping. If it is an extension "
            f"function, add it to a datatypes.<type>.functions map in capabilities/cedar.yaml; "
            "see the datatype ladder in the expressiveness doc."
        )

    def _binary(self, op: str, val: dict) -> dict:
        left = self._expr(val["left"])
        right = self._expr(val["right"])
        fn = self._BINARY_FN[op]
        if op == "==":
            fn = _equality_fn(val.get("left"), val.get("right"))
        return _apply(fn, [left, right])

    def _attr_access(self, val: dict) -> dict:
        """`principal.role` → AttributeDesignator on the principal category."""
        base = val["left"]
        attr = val["attr"]
        if isinstance(base, dict) and "Var" in base:
            category = _VAR_CATEGORY.get(base["Var"], _ENV)
            return self._designator(category, attr)
        raise CedarUnsupportedFeatureError(
            "Cedar nested attribute access (record traversal) has no flat-attribute ACAL "
            "mapping. See the `record` entry in capabilities/cedar.yaml."
        )

    def _has(self, val: dict) -> dict:
        """`principal has email` → the attribute's bag is non-empty.

        Inside the `has` operand MustBePresent stays false even under fail_closed — see
        _designator — because presence is exactly what is being tested.
        """
        base = val["left"]
        attr = val["attr"]
        if isinstance(base, dict) and "Var" in base:
            category = _VAR_CATEGORY.get(base["Var"], _ENV)
            desig = self._designator(category, attr, has_context=True)
            return _apply("integer-greater-than", [
                _apply("string-bag-size", [desig]),
                {"Value": 0},
            ])
        raise CedarUnsupportedFeatureError("Cedar `has` on a non-variable base is unsupported.")

    def _like(self, val: dict) -> dict:
        pattern = val.get("pattern")
        regex = _glob_to_regex(pattern)
        return _apply("string-regexp-match", [
            {"Value": regex},
            self._expr(val["left"]),
        ])

    def _if_then_else(self, val: dict) -> dict:
        cond = self._expr(val["if"])
        then = self._expr(val["then"])
        els = self._expr(val["else"])
        # Only sound when both branches are boolean: (c && t) || (!c && e).
        if not (_is_boolean(then) and _is_boolean(els)):
            raise CedarUnsupportedFeatureError(
                "Cedar if-then-else returning a non-boolean value has no ACAL equivalent "
                "(ACAL has no conditional expression). Only boolean-valued conditionals convert."
            )
        return _apply("or", [
            _apply("and", [cond, then]),
            _apply("and", [_apply("not", [cond]), els]),
        ])


# ---------------------------------------------------------------------------
# Module helpers
# ---------------------------------------------------------------------------

def _apply(fn_suffix: str, arguments: list[dict]) -> dict:
    return {"Apply": {"FunctionId": f"{_FN}:{fn_suffix}", "Argument": arguments}}


# ACAL LocalIdentifierType (used for Rule Id): letter-led (after optional underscores),
# alphanumeric/underscore runs joined by single '-' or '.' separators.
import re as _re_mod  # noqa: E402
_LOCAL_ID_RE = _re_mod.compile(r"^_*[A-Za-z][A-Za-z_0-9]*([-.]_*[A-Za-z_0-9]*)*$")


def _sanitize_local_id(raw: str, fallback: str) -> tuple[str, bool]:
    """Coerce an arbitrary Cedar @id to a legal ACAL LocalIdentifierType.

    Returns (id, changed). If `raw` is already legal it is returned unchanged. Otherwise
    illegal characters are replaced with '-' and a letter prefix is added if needed; if the
    result still is not legal (e.g. `raw` had no letters at all), `fallback` is used.
    """
    if _LOCAL_ID_RE.match(raw):
        return raw, False
    cleaned = _re_mod.sub(r"[^A-Za-z0-9_.-]", "-", raw)
    if not _re_mod.match(r"^_*[A-Za-z]", cleaned):
        cleaned = "id-" + cleaned
    if _LOCAL_ID_RE.match(cleaned):
        return cleaned, True
    return fallback, True


def _load_datamap() -> dict:
    """The `datatypes:` block of Cedar's capability matrix — the import-direction map."""
    from ..languages import capabilities
    return capabilities("cedar").get("datatypes") or {}


def _suffix(acal_fn: str) -> str:
    """Reduce a mapped ACAL function ('{double-less-than}' or a full URN) to its suffix."""
    s = acal_fn.strip().strip("{}")
    return s.rsplit(":", 1)[-1]


def _coerce_literal(value, acal_type: str) -> object:
    """Coerce a Cedar constructor's string literal to the ACAL target type's Python value."""
    t = acal_type.strip("{}")
    if t in ("double",) and not isinstance(value, bool):
        try:
            return float(value)
        except (TypeError, ValueError):
            return value
    if t in ("integer",) and not isinstance(value, bool):
        try:
            return int(value)
        except (TypeError, ValueError):
            return value
    return value


def _entity_uid_string(entity: dict) -> str:
    """Render a Cedar entity reference as its canonical 'Type::"id"' string."""
    if isinstance(entity, dict) and "type" in entity and "id" in entity:
        return f'{entity["type"]}::"{entity["id"]}"'
    if isinstance(entity, dict) and "__entity" in entity:
        e = entity["__entity"]
        return f'{e["type"]}::"{e["id"]}"'
    return str(entity)


def _scalar_type(node: Any) -> str | None:
    """The ACAL scalar type of a Cedar EST node, where the EST makes it knowable.

    Returns 'boolean' / 'integer' / 'double' / 'string' for a literal, the common element
    type of a homogeneous Set literal, or None when the type cannot be told from syntax alone
    (an attribute access, a variable — anything whose type needs Cedar's schema, which we do
    not have). Callers default None to 'string' and the boundary is documented as a known
    limitation in docs/policy-language-expressiveness.md.
    """
    if isinstance(node, dict) and "Value" in node:
        v = node["Value"]
        if isinstance(v, bool):
            return "boolean"
        if isinstance(v, int):
            return "integer"
        if isinstance(v, float):
            return "double"
        if isinstance(v, str):
            return "string"
        return None
    if isinstance(node, dict) and "Set" in node:
        member_types = {_scalar_type(e) for e in node["Set"]}
        member_types.discard(None)
        if len(member_types) == 1:
            return next(iter(member_types))
        return None
    return None


def _type_prefix(*nodes: Any) -> str:
    """The first inferable scalar type among nodes, defaulting to 'string'."""
    for node in nodes:
        t = _scalar_type(node)
        if t is not None:
            return t
    return "string"


def _equality_fn(left_node: Any, right_node: Any) -> str:
    """Infer the ACAL equality function from a literal on either side of ==.

    Checking both sides (not just the right) means `context.count == 5` and `5 == context.count`
    both resolve to integer-equal. Attribute == attribute, with no literal, is unknowable from
    the EST and falls back to string-equal.
    """
    return f"{_type_prefix(right_node, left_node)}-equal"


def _is_boolean(expr: dict) -> bool:
    """True if an already-converted expression is boolean-valued."""
    if "Apply" in expr:
        fn = expr["Apply"]["FunctionId"].rsplit(":", 1)[-1]
        return (
            fn in {"and", "or", "not"}
            or fn.endswith(("equal", "greater-than", "less-than",
                            "greater-than-or-equal", "less-than-or-equal",
                            "is-in", "subset", "at-least-one-member-of", "regexp-match"))
        )
    if "Value" in expr:
        return isinstance(expr["Value"], bool)
    return False


def _glob_to_regex(pattern: list) -> str:
    """Translate a Cedar `like` pattern to an anchored regex.

    Cedar's EST pre-tokenizes the pattern into a list of {"Literal": <char>} and the string
    "Wildcard", so there is no glob string to re-parse and no escaping ambiguity: a `*` that
    reached us as a Literal is a literal star, and only "Wildcard" means `.*`. Every literal is
    regex-escaped so a `.` in the pattern cannot silently match any character.
    """
    import re as _re

    out = ["^"]
    for tok in pattern:
        if tok == "Wildcard":
            out.append(".*")
        elif isinstance(tok, dict) and "Literal" in tok:
            out.append(_re.escape(tok["Literal"]))
        else:
            raise CedarUnsupportedFeatureError(
                f"Unrecognised Cedar `like` pattern token: {tok!r}"
            )
    out.append("$")
    return "".join(out)


def _template_slots(tmpl: dict) -> list[str]:
    """The ?slots a template declares, in principal/resource order."""
    slots: list[str] = []
    for key in ("principal", "resource"):
        scope = tmpl.get(key) or {}
        if "slot" in scope:
            slots.append(scope["slot"])
    return slots


# Content-sniff signature used by readers/__init__.detect_format_from_bytes.
def looks_like_cedar(chunk: bytes) -> bool:
    """A Cedar document opens with permit, forbid, or an @annotation (after // comments)."""
    text = chunk.decode("utf-8", "ignore")
    # strip // line comments and leading whitespace
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("//"):
            continue
        lines.append(stripped)
    body = " ".join(lines).lstrip()
    return body.startswith("permit") or body.startswith("forbid") or body.startswith("@")
