"""
XACML 3.0 / 4.0  →  YACAL v1.0 converter.

Entry point: convert_file(path) → dict  (ready for ruamel.yaml serialisation).

XACML 4.0 (namespace urn:oasis:names:tc:xacml:4.0:core:schema) is the XML
profile of ACAL v1.0.  Its identifiers already use urn:oasis:names:tc:acal:
prefixes, so only element-structure mapping is needed.

XACML 3.0 (namespace urn:oasis:names:tc:xacml:3.0:core:schema:wd-17) needs
both structure mapping AND identifier remapping (xacml URNs / XSD types →
acal URNs, plus AnyOf/AllOf/Match → Apply trees).
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any

from ._identifiers import optional_datatype, remap_identifier

XACML3_NS = "urn:oasis:names:tc:xacml:3.0:core:schema:wd-17"
XACML4_NS = "urn:oasis:names:tc:xacml:4.0:core:schema"

_ACAL_OR = "urn:oasis:names:tc:acal:1.0:function:or"
_ACAL_AND = "urn:oasis:names:tc:acal:1.0:function:and"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_ns(elem: ET.Element) -> str:
    tag = elem.tag
    return tag[1 : tag.index("}")] if tag.startswith("{") else ""


def _local(elem: ET.Element) -> str:
    tag = elem.tag
    return tag[tag.index("}") + 1 :] if "}" in tag else tag


def _bool_attr(elem: ET.Element, name: str, default: str = "false") -> bool:
    return elem.get(name, default).lower() == "true"


def _int_attr(elem: ET.Element, name: str) -> int | None:
    val = elem.get(name)
    return int(val) if val is not None else None


def _coerce_value(text: str, data_type: str) -> Any:
    """Convert a string literal to a Python type matching its XACML DataType."""
    if "integer" in data_type:
        try:
            return int(text)
        except ValueError:
            pass
    if "boolean" in data_type:
        if text.lower() == "true":
            return True
        if text.lower() == "false":
            return False
    if "double" in data_type or "float" in data_type:
        try:
            return float(text)
        except ValueError:
            pass
    return text


def _set_if(d: dict, key: str, value: Any) -> None:
    """Add key→value to d only when value is not None."""
    if value is not None:
        d[key] = value


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def convert_file(path: str) -> dict[str, Any]:
    """Parse an XACML 3.0 or 4.0 XML file and return a YACAL dict."""
    tree = ET.parse(path)
    root = tree.getroot()
    ns = _extract_ns(root)
    if ns == XACML3_NS:
        version = "3.0"
    elif ns == XACML4_NS:
        version = "4.0"
    else:
        raise ValueError(f"Unrecognised XACML namespace: {ns!r}")
    return _Converter(ns, version).convert_root(root)


# ---------------------------------------------------------------------------
# Converter
# ---------------------------------------------------------------------------


class _Converter:
    def __init__(self, ns: str, version: str) -> None:
        self._ns = ns
        self._version = version
        # Identifier remapping is only needed for XACML 3.0 inputs.
        self._remap: bool = version == "3.0"

    def _t(self, name: str) -> str:
        return f"{{{self._ns}}}{name}"

    def _ident(self, value: str | None) -> str | None:
        return remap_identifier(value) if self._remap else value

    def _dt(self, value: str | None) -> str | None:
        return optional_datatype(value) if self._remap else value

    def _text(self, parent: ET.Element, child_name: str) -> str | None:
        child = parent.find(self._t(child_name))
        if child is not None and child.text:
            return child.text.strip()
        return None

    # -----------------------------------------------------------------------
    # Root dispatch
    # -----------------------------------------------------------------------

    def convert_root(self, root: ET.Element) -> dict:
        name = _local(root)
        if name == "Policy":
            return {"Policy": self._policy(root)}
        if name == "PolicySet" and self._version == "3.0":
            return {"Policy": self._policyset(root)}
        if name == "Bundle":
            return {"Bundle": self._bundle(root)}
        if name == "Request":
            return {"Request": self._request(root)}
        if name == "Response":
            return {"Response": self._response(root)}
        raise ValueError(f"Unsupported root element: {name!r}")

    # -----------------------------------------------------------------------
    # Policy (XACML 3.0 and 4.0)
    # -----------------------------------------------------------------------

    def _policy(self, elem: ET.Element) -> dict:
        p: dict = {
            "PolicyId": elem.get("PolicyId"),
            "Version": elem.get("Version"),
            # XACML 3.0 uses RuleCombiningAlgId; 4.0 uses CombiningAlgId
            "CombiningAlgId": self._ident(
                elem.get("CombiningAlgId") or elem.get("RuleCombiningAlgId")
            ),
        }
        _set_if(p, "Description", self._text(elem, "Description"))
        _set_if(p, "MaxDelegationDepth", _int_attr(elem, "MaxDelegationDepth"))

        target = elem.find(self._t("Target"))
        if target is not None:
            expr = self._target(target)
            _set_if(p, "Target", expr)

        var_defs = [self._variable_definition(v)
                    for v in elem.findall(self._t("VariableDefinition"))]
        _set_if(p, "VariableDefinition", var_defs or None)

        combiner = self._policy_combiner_input(elem)
        _set_if(p, "CombinerInput", combiner or None)

        notices = self._notice_expressions(elem)
        _set_if(p, "NoticeExpression", notices or None)

        return p

    # XACML 3.0 PolicySet → YACAL Policy (Policy absorbs PolicySet per ACAL 1.0)
    def _policyset(self, elem: ET.Element) -> dict:
        p: dict = {
            "PolicyId": elem.get("PolicySetId"),
            "Version": elem.get("Version"),
            "CombiningAlgId": self._ident(elem.get("PolicyCombiningAlgId")),
        }
        _set_if(p, "Description", self._text(elem, "Description"))

        target = elem.find(self._t("Target"))
        if target is not None:
            _set_if(p, "Target", self._target(target))

        combiner = self._policyset_combiner_input(elem)
        _set_if(p, "CombinerInput", combiner or None)

        notices = self._notice_expressions(elem)
        _set_if(p, "NoticeExpression", notices or None)

        return p

    def _policy_combiner_input(self, policy_elem: ET.Element) -> list:
        items = []
        for child in policy_elem:
            name = _local(child)
            if name == "Rule":
                items.append({"Rule": self._rule(child)})
            elif name == "Policy":
                items.append({"Policy": self._policy(child)})
            elif name == "PolicySet" and self._version == "3.0":
                items.append({"Policy": self._policyset(child)})
            elif name == "PolicyIdReference" and self._version == "3.0":
                items.append({"PolicyReference": self._policy_id_ref(child)})
            elif name == "PolicySetIdReference" and self._version == "3.0":
                items.append({"PolicyReference": self._policy_id_ref(child)})
            elif name == "PolicyReference" and self._version == "4.0":
                items.append({"PolicyReference": self._policy_ref_4(child)})
        return items

    def _policyset_combiner_input(self, elem: ET.Element) -> list:
        items = []
        for child in elem:
            name = _local(child)
            if name == "Policy":
                items.append({"Policy": self._policy(child)})
            elif name == "PolicySet":
                items.append({"Policy": self._policyset(child)})
            elif name == "PolicyIdReference":
                items.append({"PolicyReference": self._policy_id_ref(child)})
            elif name == "PolicySetIdReference":
                items.append({"PolicyReference": self._policy_id_ref(child)})
        return items

    def _policy_id_ref(self, elem: ET.Element) -> dict:
        ref: dict = {"PolicyId": (elem.text or "").strip()}
        _set_if(ref, "Version", elem.get("Version"))
        return ref

    def _policy_ref_4(self, elem: ET.Element) -> dict:
        ref: dict = {"PolicyId": elem.get("PolicyId", "")}
        _set_if(ref, "Version", elem.get("Version"))
        return ref

    # -----------------------------------------------------------------------
    # Rule
    # -----------------------------------------------------------------------

    def _rule(self, elem: ET.Element) -> dict:
        r: dict = {
            # XACML 3.0 uses RuleId; XACML 4.0 uses Id
            "Id": elem.get("Id") or elem.get("RuleId"),
            "Effect": elem.get("Effect"),
        }
        _set_if(r, "Description", self._text(elem, "Description"))

        var_defs = [self._variable_definition(v)
                    for v in elem.findall(self._t("VariableDefinition"))]
        _set_if(r, "VariableDefinition", var_defs or None)

        cond = elem.find(self._t("Condition"))
        if cond is not None:
            _set_if(r, "Condition", self._expr_child(cond))

        notices = self._notice_expressions(elem)
        _set_if(r, "NoticeExpression", notices or None)

        return r

    # -----------------------------------------------------------------------
    # Target
    # -----------------------------------------------------------------------

    def _target(self, elem: ET.Element) -> dict | None:
        if self._version == "3.0":
            return self._target_xacml3(elem)
        # XACML 4.0: Target is BooleanExpressionType — one NonLiteralExpression child
        return self._expr_child(elem)

    def _target_xacml3(self, elem: ET.Element) -> dict | None:
        """Convert XACML 3.0 AnyOf / AllOf / Match to a boolean Apply tree."""
        anyof_elems = elem.findall(self._t("AnyOf"))
        if not anyof_elems:
            return None  # empty Target = always match; omit in YACAL

        anyof_exprs = [self._anyof(ao) for ao in anyof_elems]
        if len(anyof_exprs) == 1:
            return anyof_exprs[0]
        return {"Apply": {"FunctionId": _ACAL_OR, "Argument": anyof_exprs}}

    def _anyof(self, elem: ET.Element) -> dict:
        allof_elems = elem.findall(self._t("AllOf"))
        allof_exprs = [self._allof(ao) for ao in allof_elems]
        if len(allof_exprs) == 1:
            return allof_exprs[0]
        # Multiple AllOf inside one AnyOf → OR (any AllOf block must match)
        return {"Apply": {"FunctionId": _ACAL_OR, "Argument": allof_exprs}}

    def _allof(self, elem: ET.Element) -> dict:
        match_elems = elem.findall(self._t("Match"))
        match_exprs = [self._match(m) for m in match_elems]
        if len(match_exprs) == 1:
            return match_exprs[0]
        return {"Apply": {"FunctionId": _ACAL_AND, "Argument": match_exprs}}

    def _match(self, elem: ET.Element) -> dict:
        fn_id = self._ident(elem.get("MatchId"))

        av = elem.find(self._t("AttributeValue"))
        ad = elem.find(self._t("AttributeDesignator"))
        as_ = elem.find(self._t("AttributeSelector"))

        arg0 = self._attribute_value(av)
        arg1 = (
            {"AttributeDesignator": self._attr_desig(ad)}
            if ad is not None
            else {"AttributeSelector": self._attr_sel(as_)}
        )
        return {"Apply": {"FunctionId": fn_id, "Argument": [arg0, arg1]}}

    # -----------------------------------------------------------------------
    # Expressions
    # -----------------------------------------------------------------------

    def _expr_child(self, parent: ET.Element) -> dict | None:
        """Return the first child converted as a wrapper-key expression dict."""
        for child in parent:
            expr = self._expr_elem(child)
            if expr is not None:
                return expr
        return None

    def _expr_elem(self, elem: ET.Element) -> dict | None:
        """Convert a single expression element to its YACAL wrapper-key form."""
        name = _local(elem)

        if name == "Apply":
            return {"Apply": self._apply(elem)}
        # XACML 3.0 uses AttributeValue; XACML 4.0 uses Value
        if name in ("Value", "AttributeValue"):
            return self._attribute_value(elem)
        if name == "AttributeDesignator":
            return {"AttributeDesignator": self._attr_desig(elem)}
        if name == "AttributeSelector":
            return {"AttributeSelector": self._attr_sel(elem)}
        if name == "VariableReference":
            return {"VariableReference": {"VariableId": elem.get("VariableId")}}
        if name == "SharedVariableReference":
            return {"SharedVariableReference": {"Id": elem.get("Id")}}
        if name == "Function":
            return {"Function": {"FunctionId": self._ident(elem.get("FunctionId"))}}
        if name in ("ForAny", "ForAll", "Select", "Map"):
            return {name: self._quantified_expr(elem)}
        # Skip non-expression children (Description, etc.)
        return None

    def _apply(self, elem: ET.Element) -> dict:
        apply: dict = {"FunctionId": self._ident(elem.get("FunctionId"))}
        _set_if(apply, "Description", self._text(elem, "Description"))

        args: list = []
        named: list = []
        for child in elem:
            name = _local(child)
            if name == "Description":
                continue
            if name == "NamedArgument":
                named.append(self._named_argument(child))
            else:
                expr = self._expr_elem(child)
                if expr is not None:
                    args.append(expr)

        _set_if(apply, "Argument", args or None)
        _set_if(apply, "NamedArgument", named or None)
        return apply

    def _named_argument(self, elem: ET.Element) -> dict:
        entry: dict = {"Name": elem.get("Name")}
        expr = self._expr_child(elem)
        if expr:
            entry.update(expr)
        return entry

    def _attribute_value(self, elem: ET.Element | None) -> dict:
        if elem is None:
            return {"Value": None}
        text = (elem.text or "").strip()
        return {"Value": _coerce_value(text, elem.get("DataType", ""))}

    def _attr_desig(self, elem: ET.Element) -> dict:
        d: dict = {
            "Category": self._ident(elem.get("Category")),
            "AttributeId": self._ident(elem.get("AttributeId")),
        }
        _set_if(d, "DataType", self._dt(elem.get("DataType")))
        if _bool_attr(elem, "MustBePresent"):
            d["MustBePresent"] = True
        _set_if(d, "Issuer", elem.get("Issuer"))
        return d

    def _attr_sel(self, elem: ET.Element) -> dict:
        # XACML 3.0 uses RequestContextPath; XACML 4.0 uses Path
        path = elem.get("Path") or elem.get("RequestContextPath", "")
        d: dict = {
            "Category": self._ident(elem.get("Category")),
            "Path": path,
        }
        _set_if(d, "DataType", self._dt(elem.get("DataType")))
        if _bool_attr(elem, "MustBePresent"):
            d["MustBePresent"] = True
        return d

    def _quantified_expr(self, elem: ET.Element) -> dict:
        q: dict = {"VariableId": elem.get("VariableId")}
        for child_name in ("Domain", "Iterant", "Predicate"):
            child = elem.find(self._t(child_name))
            if child is not None:
                _set_if(q, child_name, self._expr_child(child))
        return q

    # -----------------------------------------------------------------------
    # VariableDefinition
    # -----------------------------------------------------------------------

    def _variable_definition(self, elem: ET.Element) -> dict:
        vd: dict = {"VariableId": elem.get("VariableId")}
        _set_if(vd, "Expression", self._expr_child(elem))
        return vd

    # -----------------------------------------------------------------------
    # NoticeExpression (XACML 4.0) / Obligation + Advice (XACML 3.0)
    # -----------------------------------------------------------------------

    def _notice_expressions(self, elem: ET.Element) -> list:
        if self._version == "3.0":
            return self._notices_from_xacml3(elem)
        return [self._notice_expr(ne)
                for ne in elem.findall(self._t("NoticeExpression"))]

    def _notices_from_xacml3(self, elem: ET.Element) -> list:
        notices: list = []
        obl_root = elem.find(self._t("ObligationExpressions"))
        if obl_root is not None:
            for obl in obl_root.findall(self._t("ObligationExpression")):
                notice: dict = {
                    "Id": self._ident(obl.get("ObligationId")),
                    "IsObligation": True,
                }
                _set_if(notice, "AppliesTo", obl.get("FulfillOn"))
                aae = self._aae_list(obl)
                _set_if(notice, "AttributeAssignmentExpression", aae or None)
                notices.append(notice)

        adv_root = elem.find(self._t("AdviceExpressions"))
        if adv_root is not None:
            for adv in adv_root.findall(self._t("AdviceExpression")):
                notice = {"Id": self._ident(adv.get("AdviceId"))}
                _set_if(notice, "AppliesTo", adv.get("AppliesTo"))
                aae = self._aae_list(adv)
                _set_if(notice, "AttributeAssignmentExpression", aae or None)
                notices.append(notice)

        return notices

    def _notice_expr(self, elem: ET.Element) -> dict:
        notice: dict = {"Id": self._ident(elem.get("Id"))}
        if _bool_attr(elem, "IsObligation"):
            notice["IsObligation"] = True
        _set_if(notice, "AppliesTo", elem.get("AppliesTo"))
        cond = elem.find(self._t("Condition"))
        if cond is not None:
            _set_if(notice, "Condition", self._expr_child(cond))
        aae = self._aae_list(elem)
        _set_if(notice, "AttributeAssignmentExpression", aae or None)
        return notice

    def _aae_list(self, parent: ET.Element) -> list:
        result = []
        for aae in parent.findall(self._t("AttributeAssignmentExpression")):
            entry: dict = {"AttributeId": self._ident(aae.get("AttributeId"))}
            cat = aae.get("Category")
            if cat:
                entry["Category"] = self._ident(cat)
            _set_if(entry, "Issuer", aae.get("Issuer"))
            _set_if(entry, "DataType", self._dt(aae.get("DataType")))
            _set_if(entry, "Expression", self._expr_child(aae))
            result.append(entry)
        return result

    # -----------------------------------------------------------------------
    # Bundle
    # -----------------------------------------------------------------------

    def _bundle(self, elem: ET.Element) -> dict:
        bundle: dict = {}

        short_id_sets = [self._short_id_set(s)
                         for s in elem.findall(self._t("ShortIdSet"))]
        _set_if(bundle, "ShortIdSet", short_id_sets or None)

        shared_vars = [self._shared_var_def(s)
                       for s in elem.findall(self._t("SharedVariableDefinition"))]
        _set_if(bundle, "SharedVariableDefinition", shared_vars or None)

        policies = [self._policy(p) for p in elem.findall(self._t("Policy"))]
        _set_if(bundle, "Policy", policies or None)

        ref = elem.find(self._t("PolicyReference"))
        if ref is not None:
            bundle["PolicyReference"] = self._policy_ref_4(ref)

        return bundle

    def _short_id_set(self, elem: ET.Element) -> dict:
        sid: dict = {}
        _set_if(sid, "Id", elem.get("Id"))
        entries = []
        for child in elem:
            if _local(child) == "ShortId":
                entries.append({"Id": child.get("Id"), "URI": child.get("URI")})
        _set_if(sid, "ShortId", entries or None)
        return sid

    def _shared_var_def(self, elem: ET.Element) -> dict:
        svd: dict = {"Id": elem.get("Id"), "Version": elem.get("Version")}
        _set_if(svd, "Expression", self._expr_child(elem))
        return svd

    # -----------------------------------------------------------------------
    # Request / Response (structural conversion, no deep evaluation)
    # -----------------------------------------------------------------------

    def _request(self, elem: ET.Element) -> dict:
        req: dict = {}
        if _bool_attr(elem, "ReturnPolicyIdList"):
            req["ReturnPolicyIdList"] = True
        if _bool_attr(elem, "CombinedDecision"):
            req["CombinedDecision"] = True

        entities = [self._request_entity(re)
                    for re in elem.findall(self._t("RequestEntity"))]
        _set_if(req, "RequestEntity", entities or None)
        return req

    def _request_entity(self, elem: ET.Element) -> dict:
        entity: dict = {"Category": self._ident(elem.get("Category"))}
        _set_if(entity, "Id", elem.get("Id"))
        attrs = [self._request_attribute(ra)
                 for ra in elem.findall(self._t("RequestAttribute"))]
        _set_if(entity, "RequestAttribute", attrs or None)
        return entity

    def _request_attribute(self, elem: ET.Element) -> dict:
        attr: dict = {"AttributeId": self._ident(elem.get("AttributeId"))}
        _set_if(attr, "DataType", self._dt(elem.get("DataType")))
        _set_if(attr, "Issuer", elem.get("Issuer"))
        values = [(v.text or "").strip() for v in elem.findall(self._t("Value"))]
        if len(values) == 1:
            attr["Value"] = values[0]
        elif values:
            attr["Value"] = values
        return attr

    def _response(self, elem: ET.Element) -> dict:
        resp: dict = {}
        results = [self._result(r) for r in elem.findall(self._t("Result"))]
        _set_if(resp, "Result", results or None)
        return resp

    def _result(self, elem: ET.Element) -> dict:
        result: dict = {"Decision": elem.get("Decision")}
        status = elem.find(self._t("Status"))
        if status is not None:
            result["Status"] = self._status(status)
        return result

    def _status(self, elem: ET.Element) -> dict:
        status: dict = {}
        sc = elem.find(self._t("StatusCode"))
        if sc is not None:
            status["StatusCode"] = {"Value": self._ident(sc.get("Value"))}
        _set_if(status, "StatusMessage", self._text(elem, "StatusMessage"))
        return status
