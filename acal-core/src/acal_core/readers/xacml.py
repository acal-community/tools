"""
XACML 2.0 / 3.0 / 4.0 reader — converts an XACML document to a neutral ACAL dict.

XACML 4.0 is the XML profile of ACAL v1.0 and requires only structural mapping.
XACML 3.0 and 2.0 require both structural mapping and identifier remapping.

XACMLVersion enum drives namespace detection, remapping behavior, and
unsupported-feature checks. The internal ACAL dict is version-agnostic
(except for optional SourceVersion metadata).

Unsupported constructs raise XACMLUnsupportedFeatureError. This is deliberate
to avoid silent data loss.
"""

from __future__ import annotations

import warnings
import xml.etree.ElementTree as ET
from enum import Enum
from typing import Any

from ._xacml_identifiers import optional_datatype, remap_identifier


class XACMLVersion(Enum):
    """XACML versions supported as input.

    Used to drive namespace detection, identifier remapping, and feature
    compatibility checks. Future ACAL versions may introduce XACMLVersion.V5_0
    or similar.
    """
    V2_0 = "2.0"
    V3_0 = "3.0"
    V4_0 = "4.0"


XACML2_NS = "urn:oasis:names:tc:xacml:2.0:core:schema:os"
XACML3_NS = "urn:oasis:names:tc:xacml:3.0:core:schema:wd-17"
XACML4_NS = "urn:oasis:names:tc:xacml:4.0:core:schema"

_ACAL_OR = "urn:oasis:names:tc:acal:1.0:function:or"
_ACAL_AND = "urn:oasis:names:tc:acal:1.0:function:and"

# XACML 2.0 uses specialized AttributeDesignator element names; the implied
# ACAL category URN is fixed per element type.  Subject category comes from
# the SubjectCategory attribute (or the XACML 1.0 default) and is remapped.
_ACAL_CAT_BASE = "urn:oasis:names:tc:acal:1.0:attribute-category"
_XACML2_DESIG_CATEGORY: dict[str, str] = {
    "ResourceAttributeDesignator": f"{_ACAL_CAT_BASE}:resource",
    "ActionAttributeDesignator": f"{_ACAL_CAT_BASE}:action",
    "EnvironmentAttributeDesignator": f"{_ACAL_CAT_BASE}:environment",
}
_XACML2_SUBJECT_DEFAULT = "urn:oasis:names:tc:xacml:1.0:subject-category:access-subject"

# All four XACML 2.0 Target section configurations.
_XACML2_SECTIONS = [
    ("Subjects",     "Subject",     "SubjectMatch"),
    ("Resources",    "Resource",    "ResourceMatch"),
    ("Actions",      "Action",      "ActionMatch"),
    ("Environments", "Environment", "EnvironmentMatch"),
]


class XACMLUnsupportedFeatureError(ValueError):
    """Raised when an XACML construct has no ACAL 1.0 equivalent."""


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
    if value is not None:
        d[key] = value


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def available() -> bool:
    return True


def load(path: str, strict: bool = False) -> dict[str, Any]:
    """Parse an XACML 2.0/3.0/4.0 file and return a neutral ACAL dict.

    If strict=True, deprecated but semantically harmless constructs
    (e.g. IncludeInResult) raise XACMLUnsupportedFeatureError.
    """
    tree = ET.parse(path)
    root = tree.getroot()
    ns = _extract_ns(root)
    version = _version_for_namespace(ns)
    doc = _Converter(ns, version, strict=strict).convert_root(root)
    return _strip_nulls(doc)


def _version_for_namespace(ns: str) -> XACMLVersion:
    if ns == XACML2_NS:
        return XACMLVersion.V2_0
    if ns == XACML3_NS:
        return XACMLVersion.V3_0
    if ns == XACML4_NS:
        return XACMLVersion.V4_0
    raise ValueError(f"Unrecognised XACML namespace: {ns!r}")


def detect_version(path: str) -> XACMLVersion:
    """Which XACML version a document is written in, from its namespace.

    XACML 4.0 is the XML serialization of ACAL 1.0 itself; 2.0 and 3.0 are foreign
    dialects that get remapped on import. Callers need the distinction to know which
    capability matrix (if any) applies.
    """
    for _, elem in ET.iterparse(path, events=("start",)):
        return _version_for_namespace(_extract_ns(elem))
    raise ValueError(f"Empty XACML document: {path!r}")


def _strip_nulls(value):
    """Drop keys whose value is None.

    An absent optional XACML attribute (`Version`, `Issuer`, …) reaches the builders as
    None. Emitting it produces `Version:` — a YAML null — and YACAL prohibits nulls
    outright, so the converter would be writing documents that our own yacal-validate
    rejects. Omitting the key is also the more useful failure: a genuinely required field
    then surfaces as "required property missing" rather than as a confusing null error.
    """
    if isinstance(value, dict):
        return {k: _strip_nulls(v) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        return [_strip_nulls(v) for v in value]
    return value


# ---------------------------------------------------------------------------
# Converter
# ---------------------------------------------------------------------------


class _Converter:
    def __init__(self, ns: str, version: XACMLVersion, strict: bool = False) -> None:
        self._ns = ns
        self._version = version
        self._strict = strict
        self._remap: bool = version in (XACMLVersion.V2_0, XACMLVersion.V3_0)

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
        if name == "PolicySet" and self._version in (XACMLVersion.V2_0, XACMLVersion.V3_0):
            # XACML 2.0 and 3.0 PolicySet maps to ACAL Policy (ACAL 1.0 absorbed PolicySet)
            return {"Policy": self._policyset(root)}
        if name == "Bundle":
            return {"Bundle": self._bundle(root)}
        if name == "Request":
            return {"Request": self._request(root)}
        if name == "Response":
            return {"Response": self._response(root)}
        raise ValueError(f"Unsupported root element: {name!r} for XACML {self._version.value}")

    # -----------------------------------------------------------------------
    # Policy (XACML 2.0/3.0/4.0)
    # -----------------------------------------------------------------------

    def _version_attr(self, elem: ET.Element) -> str | None:
        """Policy/PolicySet Version, applying the XACML 2.0/3.0 schema default.

        ACAL requires Version. XACML 2.0/3.0 declare it optional with a schema default of
        "1.0", so an absent attribute *means* 1.0 and supplying it is faithful, not invented.
        XACML 4.0 declares Version use="required", so an absent one means the input is
        malformed — we return None rather than fabricating a value, and the missing required
        field surfaces downstream (`acal-convert --validate`) instead of being papered over.
        """
        version = elem.get("Version")
        if version is None and self._version in (XACMLVersion.V2_0, XACMLVersion.V3_0):
            return "1.0"
        return version

    def _policy(self, elem: ET.Element) -> dict:
        self._check_xpath_version(elem)

        p: dict = {}
        _set_if(p, "PolicyId", elem.get("PolicyId"))
        _set_if(p, "Version", self._version_attr(elem))
        # XACML 3.0 uses RuleCombiningAlgId; 4.0 uses CombiningAlgId
        _set_if(p, "CombiningAlgId", self._ident(
            elem.get("CombiningAlgId") or elem.get("RuleCombiningAlgId")
        ))
        _set_if(p, "Description", self._text(elem, "Description"))
        _set_if(p, "MaxDelegationDepth", _int_attr(elem, "MaxDelegationDepth"))

        target = elem.find(self._t("Target"))
        if target is not None:
            _set_if(p, "Target", self._target(target))

        var_defs = [self._variable_definition(v)
                    for v in elem.findall(self._t("VariableDefinition"))]
        _set_if(p, "VariableDefinition", var_defs or None)

        combiner = self._policy_combiner_input(elem)
        _set_if(p, "CombinerInput", combiner or None)

        notices = self._notice_expressions(elem)
        _set_if(p, "NoticeExpression", notices or None)

        return p

    # XACML 3.0 PolicySet → ACAL Policy (Policy absorbs PolicySet per ACAL 1.0)
    def _policyset(self, elem: ET.Element) -> dict:
        self._check_xpath_version(elem)

        p: dict = {}
        _set_if(p, "PolicyId", elem.get("PolicySetId"))
        _set_if(p, "Version", self._version_attr(elem))
        _set_if(p, "CombiningAlgId", self._ident(elem.get("PolicyCombiningAlgId")))
        _set_if(p, "Description", self._text(elem, "Description"))

        target = elem.find(self._t("Target"))
        if target is not None:
            _set_if(p, "Target", self._target(target))

        combiner = self._policyset_combiner_input(elem)
        _set_if(p, "CombinerInput", combiner or None)

        notices = self._notice_expressions(elem)
        _set_if(p, "NoticeExpression", notices or None)

        return p

    def _check_xpath_version(self, policy_elem: ET.Element) -> None:
        """Raise if PolicyDefaults/XPathVersion is present."""
        defaults = policy_elem.find(self._t("PolicyDefaults"))
        if defaults is None:
            return
        xpath_ver = defaults.find(self._t("XPathVersion"))
        if xpath_ver is not None:
            raise XACMLUnsupportedFeatureError(
                "<XPathVersion> inside <PolicyDefaults> is not supported. "
                "XPath profile conversion is not currently implemented in this tool. "
                "Remove <XPathVersion> from your policy or contact the XACML TC for guidance."
            )

    # Children of a Policy element that are handled elsewhere and are not combiner inputs.
    # "Obligations" is the XACML 2.0 name; "ObligationExpressions" is XACML 3.0+.
    _POLICY_NON_COMBINER_CHILDREN = frozenset({
        "Description", "PolicyIssuer", "PolicyDefaults",
        "Target", "VariableDefinition",
        "Obligations", "ObligationExpressions", "AdviceExpressions", "NoticeExpression",
    })

    def _policy_combiner_input(self, policy_elem: ET.Element) -> list:
        items = []
        for child in policy_elem:
            name = _local(child)
            if name == "Rule":
                items.append({"Rule": self._rule(child)})
            elif name == "Policy":
                items.append({"Policy": self._policy(child)})
            elif name == "PolicySet" and self._version in (XACMLVersion.V2_0, XACMLVersion.V3_0):
                items.append({"Policy": self._policyset(child)})
            elif name in ("PolicyIdReference", "PolicySetIdReference") and self._version in (XACMLVersion.V2_0, XACMLVersion.V3_0):
                items.append({"PolicyReference": self._policy_id_ref(child)})
            elif name == "PolicyReference" and self._version == XACMLVersion.V4_0:
                items.append({"PolicyReference": self._policy_ref_4(child)})
            elif name in ("CombinerParameters", "RuleCombinerParameters"):
                raise XACMLUnsupportedFeatureError(
                    f"<{name}> is no longer supported in ACAL 1.0. "
                    "Please contact the XACML TC for help. "
                    "You may consider re-designing your combining algorithm without CombinerParameters."
                )
            elif name not in self._POLICY_NON_COMBINER_CHILDREN:
                raise XACMLUnsupportedFeatureError(
                    f"<{name}> is not a recognised child element of <Policy>. "
                    "If this is a valid XACML construct, it is not yet implemented in acal-convert."
                )
        return items

    # Children of a PolicySet element that are handled elsewhere and are not combiner inputs.
    _POLICYSET_NON_COMBINER_CHILDREN = frozenset({
        "Description", "PolicyIssuer", "PolicySetDefaults",
        "Target", "ObligationExpressions", "AdviceExpressions", "NoticeExpression",
    })

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
            elif name in ("CombinerParameters", "PolicyCombinerParameters"):
                raise XACMLUnsupportedFeatureError(
                    f"<{name}> is no longer supported in ACAL 1.0. "
                    "Please contact the XACML TC for help. "
                    "You may consider re-designing your combining algorithm without CombinerParameters."
                )
            elif name not in self._POLICYSET_NON_COMBINER_CHILDREN:
                raise XACMLUnsupportedFeatureError(
                    f"<{name}> is not a recognised child element of <PolicySet>. "
                    "If this is a valid XACML construct, it is not yet implemented in acal-convert."
                )
        return items

    def _policy_id_ref(self, elem: ET.Element) -> dict:
        for attr in ("EarliestVersion", "LatestVersion"):
            if elem.get(attr) is not None:
                raise XACMLUnsupportedFeatureError(
                    f"The '{attr}' attribute on <{_local(elem)}> is no longer supported in ACAL 1.0. "
                    "Alternatives: use an explicit Version, a version pattern in the Version attribute, "
                    "or encode version constraints in the PolicyId URI (e.g. as query or matrix parameters)."
                )
        ref: dict = {"PolicyId": (elem.text or "").strip()}
        _set_if(ref, "Version", elem.get("Version"))
        return ref

    def _policy_ref_4(self, elem: ET.Element) -> dict:
        ref: dict = {"PolicyId": elem.get("PolicyId", "")}
        _set_if(ref, "Version", elem.get("Version"))
        return ref

    def _condition_xacml2(self, elem: ET.Element) -> dict | None:
        """Convert XACML 2.0 <Condition FunctionId="..."> to an Apply expression.

        In XACML 2.0 the Condition element itself is an implicit Apply: it
        carries a FunctionId and its child elements are the arguments.  In
        XACML 3.0+ the Condition is a transparent wrapper around a nested Apply.
        """
        fn_id = elem.get("FunctionId")
        if fn_id is None:
            return self._expr_child(elem)  # malformed 2.0 or 3.0 document
        args = [expr for child in elem
                for expr in [self._expr_elem(child)] if expr is not None]
        apply: dict = {"FunctionId": self._ident(fn_id)}
        if args:
            apply["Argument"] = args
        return {"Apply": apply}

    # -----------------------------------------------------------------------
    # Rule
    # -----------------------------------------------------------------------

    # Every child element a <Rule> may legally carry, across all supported versions.
    # Anything outside this set is rejected rather than ignored: a Rule child that is
    # read by no branch below would otherwise be dropped in silence, and a dropped
    # Rule child can change which requests the rule applies to.
    _RULE_KNOWN_CHILDREN = frozenset({
        "Description", "Target", "Condition", "VariableDefinition",
        "Obligations", "ObligationExpressions", "AdviceExpressions", "NoticeExpression",
    })

    def _rule(self, elem: ET.Element) -> dict:
        r: dict = {}
        # XACML 3.0 uses RuleId; XACML 4.0 uses Id
        _set_if(r, "Id", elem.get("Id") or elem.get("RuleId"))
        _set_if(r, "Effect", elem.get("Effect"))
        _set_if(r, "Description", self._text(elem, "Description"))

        for child in elem:
            name = _local(child)
            if name not in self._RULE_KNOWN_CHILDREN:
                raise XACMLUnsupportedFeatureError(
                    f"<{name}> is not a recognised child element of <Rule>. "
                    "If this is a valid XACML construct, it is not yet implemented in acal-convert."
                )

        target = elem.find(self._t("Target"))
        if target is not None:
            _set_if(r, "Target", self._target(target))

        var_defs = [self._variable_definition(v)
                    for v in elem.findall(self._t("VariableDefinition"))]
        _set_if(r, "VariableDefinition", var_defs or None)

        cond = elem.find(self._t("Condition"))
        if cond is not None:
            if self._version == XACMLVersion.V2_0:
                _set_if(r, "Condition", self._condition_xacml2(cond))
            else:
                _set_if(r, "Condition", self._expr_child(cond))

        notices = self._notice_expressions(elem)
        _set_if(r, "NoticeExpression", notices or None)

        return r

    # -----------------------------------------------------------------------
    # Target
    # -----------------------------------------------------------------------

    def _target(self, elem: ET.Element) -> dict | None:
        if self._version == XACMLVersion.V2_0:
            return self._target_xacml2(elem)
        if self._version == XACMLVersion.V3_0:
            return self._target_xacml3(elem)
        return self._expr_child(elem)  # V4_0: Target is a BooleanExpression

    def _target_xacml2(self, elem: ET.Element) -> dict | None:
        """Convert XACML 2.0 Subjects/Resources/Actions/Environments to an Apply tree.

        Each section that contains items contributes one AND clause.  Multiple
        items within a section (e.g. two <Subject> blocks) are OR'd — any one
        of them must match.  Absent or empty sections impose no constraint.
        """
        clauses = []
        for section_tag, item_tag, match_tag in _XACML2_SECTIONS:
            section = elem.find(self._t(section_tag))
            if section is None:
                continue
            items = section.findall(self._t(item_tag))
            if not items:
                continue
            item_exprs = [self._xacml2_item(item, match_tag) for item in items]
            item_exprs = [e for e in item_exprs if e is not None]
            if not item_exprs:
                continue
            if len(item_exprs) == 1:
                clauses.append(item_exprs[0])
            else:
                clauses.append({"Apply": {"FunctionId": _ACAL_OR, "Argument": item_exprs}})

        if not clauses:
            return None
        if len(clauses) == 1:
            return clauses[0]
        return {"Apply": {"FunctionId": _ACAL_AND, "Argument": clauses}}

    def _xacml2_item(self, item_elem: ET.Element, match_tag: str) -> dict | None:
        """Convert a single Subject/Resource/Action/Environment to a boolean expression."""
        matches = item_elem.findall(self._t(match_tag))
        match_exprs = [self._xacml2_match(m) for m in matches]
        match_exprs = [e for e in match_exprs if e is not None]
        if not match_exprs:
            return None
        if len(match_exprs) == 1:
            return match_exprs[0]
        return {"Apply": {"FunctionId": _ACAL_AND, "Argument": match_exprs}}

    def _xacml2_match(self, elem: ET.Element) -> dict | None:
        """Convert a XACML 2.0 *Match element to an Apply expression."""
        fn_id = self._ident(elem.get("MatchId"))
        av = elem.find(self._t("AttributeValue"))
        arg0 = self._attribute_value(av)

        # Try each specialized designator type first, then generic.
        for desig_name in (
            "SubjectAttributeDesignator", "ResourceAttributeDesignator",
            "ActionAttributeDesignator", "EnvironmentAttributeDesignator",
            "AttributeDesignator",
        ):
            ad = elem.find(self._t(desig_name))
            if ad is not None:
                arg1 = {"AttributeDesignator": self._xacml2_attr_desig(ad, desig_name)}
                break
        else:
            as_ = elem.find(self._t("AttributeSelector"))
            arg1 = {"AttributeSelector": self._attr_sel(as_)} if as_ is not None else {"Value": None}

        return {"Apply": {"FunctionId": fn_id, "Argument": [arg0, arg1]}}

    def _xacml2_attr_desig(self, elem: ET.Element, desig_name: str) -> dict:
        """Convert a XACML 2.0 specialized AttributeDesignator to generic form."""
        if desig_name == "SubjectAttributeDesignator":
            raw_cat = elem.get("SubjectCategory", _XACML2_SUBJECT_DEFAULT)
            category = self._ident(raw_cat)
        elif desig_name in _XACML2_DESIG_CATEGORY:
            category = _XACML2_DESIG_CATEGORY[desig_name]  # already an ACAL URN
        else:
            category = self._ident(elem.get("Category"))
        d: dict = {
            "Category": category,
            "AttributeId": self._ident(elem.get("AttributeId")),
        }
        _set_if(d, "DataType", self._dt(elem.get("DataType")))
        if _bool_attr(elem, "MustBePresent"):
            d["MustBePresent"] = True
        _set_if(d, "Issuer", elem.get("Issuer"))
        return d

    def _target_xacml3(self, elem: ET.Element) -> dict | None:
        """Convert XACML 3.0 AnyOf/AllOf/Match to a boolean Apply tree."""
        anyof_elems = elem.findall(self._t("AnyOf"))
        if not anyof_elems:
            return None
        anyof_exprs = [self._anyof(ao) for ao in anyof_elems]
        if len(anyof_exprs) == 1:
            return anyof_exprs[0]
        return {"Apply": {"FunctionId": _ACAL_OR, "Argument": anyof_exprs}}

    def _anyof(self, elem: ET.Element) -> dict:
        allof_elems = elem.findall(self._t("AllOf"))
        allof_exprs = [self._allof(ao) for ao in allof_elems]
        if len(allof_exprs) == 1:
            return allof_exprs[0]
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
        for child in parent:
            expr = self._expr_elem(child)
            if expr is not None:
                return expr
        return None

    def _expr_elem(self, elem: ET.Element) -> dict | None:
        name = _local(elem)
        if name == "Apply":
            return {"Apply": self._apply(elem)}
        if name in ("Value", "AttributeValue"):
            return self._attribute_value(elem)
        if name == "AttributeDesignator":
            return {"AttributeDesignator": self._attr_desig(elem)}
        if name in _XACML2_DESIG_CATEGORY or name == "SubjectAttributeDesignator":
            return {"AttributeDesignator": self._xacml2_attr_desig(elem, name)}
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
        raise XACMLUnsupportedFeatureError(
            f"Unsupported expression element <{name}>. "
            "If this is a valid XACML construct, it is not yet implemented in acal-convert. "
            "Contact the XACML TC or open an issue if you believe this element should be supported."
        )

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
        if self._version == XACMLVersion.V2_0:
            return self._notices_from_xacml2(elem)
        if self._version == XACMLVersion.V3_0:
            return self._notices_from_xacml3(elem)
        return [self._notice_expr(ne)
                for ne in elem.findall(self._t("NoticeExpression"))]

    def _notices_from_xacml2(self, elem: ET.Element) -> list:
        """XACML 2.0: <Obligations>/<Obligation>/<AttributeAssignment> (text values only)."""
        notices: list = []
        obl_root = elem.find(self._t("Obligations"))
        if obl_root is None:
            return notices
        for obl in obl_root.findall(self._t("Obligation")):
            notice: dict = {
                "Id": self._ident(obl.get("ObligationId")),
                "IsObligation": True,
            }
            _set_if(notice, "AppliesTo", obl.get("FulfillOn"))
            aae = self._xacml2_attr_assignments(obl)
            _set_if(notice, "AttributeAssignmentExpression", aae or None)
            notices.append(notice)
        return notices

    def _xacml2_attr_assignments(self, parent: ET.Element) -> list:
        """Convert XACML 2.0 <AttributeAssignment> (literal text) to ACAL format.

        XACML 2.0 obligations carry only literal values; XACML 3.0+
        AttributeAssignmentExpression can hold arbitrary expressions (Apply,
        AttributeDesignator, etc.).  We wrap the literal in a Value expression.
        """
        result = []
        for aa in parent.findall(self._t("AttributeAssignment")):
            entry: dict = {"AttributeId": self._ident(aa.get("AttributeId"))}
            cat = aa.get("Category")
            if cat:
                entry["Category"] = self._ident(cat)
            _set_if(entry, "Issuer", aa.get("Issuer"))
            _set_if(entry, "DataType", self._dt(aa.get("DataType")))
            text = (aa.text or "").strip()
            entry["Expression"] = {"Value": _coerce_value(text, aa.get("DataType", ""))}
            result.append(entry)
        return result

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

    _NOTICE_KNOWN_CHILDREN = frozenset({"Condition", "AttributeAssignmentExpression"})

    def _notice_expr(self, elem: ET.Element) -> dict:
        self._guard_children(elem, self._NOTICE_KNOWN_CHILDREN, "NoticeExpression")
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

    def _guard_children(self, elem: ET.Element, known: frozenset, container: str) -> None:
        """Reject any child element no branch below will read.

        These builders are written as targeted find()/findall() calls, which means an
        element nobody asks for is dropped in silence. That is how Rule-level <Target> went
        missing in every XACML version: a rule scoped to doctors converted into a rule that
        permitted everyone. Every find()-based builder needs one of these.
        """
        for child in elem:
            name = _local(child)
            if name not in known:
                raise XACMLUnsupportedFeatureError(
                    f"<{name}> is not a recognised child element of <{container}>. "
                    "If this is a valid XACML construct, it is not yet implemented in "
                    "acal-convert. It is rejected rather than ignored: silently dropping "
                    "policy content produces a different policy from the one you wrote."
                )

    _BUNDLE_KNOWN_CHILDREN = frozenset({
        "Description", "ShortIdSet", "SharedVariableDefinition", "Policy", "PolicyReference",
    })

    def _bundle(self, elem: ET.Element) -> dict:
        self._guard_children(elem, self._BUNDLE_KNOWN_CHILDREN, "Bundle")
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
            name = _local(child)
            if name == "ShortId":
                entries.append({"Id": child.get("Id"), "URI": child.get("URI")})
            else:
                raise XACMLUnsupportedFeatureError(
                    f"Unexpected child element <{name}> inside <ShortIdSet>. "
                    "If this is a valid XACML construct, it is not yet implemented in acal-convert."
                )
        _set_if(sid, "ShortId", entries or None)
        return sid

    def _shared_var_def(self, elem: ET.Element) -> dict:
        svd: dict = {}
        _set_if(svd, "Id", elem.get("Id"))
        _set_if(svd, "Version", elem.get("Version"))
        _set_if(svd, "Expression", self._expr_child(elem))
        return svd

    # -----------------------------------------------------------------------
    # Request / Response
    # -----------------------------------------------------------------------

    def _request(self, elem: ET.Element) -> dict:
        req: dict = {}
        if _bool_attr(elem, "ReturnPolicyIdList"):
            req["ReturnPolicyIdList"] = True
        if _bool_attr(elem, "CombinedDecision"):
            req["CombinedDecision"] = True

        if self._version in (XACMLVersion.V2_0, XACMLVersion.V3_0):
            # XACML 2.0/3.0 uses <Attributes Category="..."><Attribute ...> nesting.
            # IncludeInResult is removed from ACAL 1.0; warn if set to true.
            attrs_elems = elem.findall(self._t("Attributes"))
            for attrs_elem in attrs_elems:
                for attr in attrs_elem.findall(self._t("Attribute")):
                    if _bool_attr(attr, "IncludeInResult"):
                        attr_id = attr.get("AttributeId", "(unknown)")
                        msg = (
                            f"IncludeInResult=\"true\" on attribute '{attr_id}' is no longer "
                            "supported in ACAL 1.0 and has been ignored."
                        )
                        if self._strict:
                            raise XACMLUnsupportedFeatureError(msg)
                        warnings.warn(msg, UserWarning, stacklevel=2)
            if attrs_elems:
                raise XACMLUnsupportedFeatureError(
                    f"XACML {self._version.value} <Request> bodies using <Attributes> elements "
                    "are not yet implemented in acal-convert. "
                    "Only XACML 4.0 <Request> (using <RequestEntity>) is fully supported."
                )

        entities = [self._request_entity(re)
                    for re in elem.findall(self._t("RequestEntity"))]
        _set_if(req, "RequestEntity", entities or None)
        return req

    _REQUEST_ENTITY_KNOWN_CHILDREN = frozenset({"RequestAttribute", "Content"})

    def _request_entity(self, elem: ET.Element) -> dict:
        self._guard_children(elem, self._REQUEST_ENTITY_KNOWN_CHILDREN, "RequestEntity")
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

    _RESPONSE_KNOWN_CHILDREN = frozenset({"Result"})

    def _response(self, elem: ET.Element) -> dict:
        self._guard_children(elem, self._RESPONSE_KNOWN_CHILDREN, "Response")
        resp: dict = {}
        results = [self._result(r) for r in elem.findall(self._t("Result"))]
        _set_if(resp, "Result", results or None)
        return resp

    # A <Result> may also carry Obligations, AssociatedAdvice, Attributes, and
    # PolicyIdentifierList. None of those are converted yet, and all four were being
    # dropped without a word — an obligation that vanishes from a Result is an
    # enforcement requirement the PEP will never see. They raise until implemented.
    _RESULT_KNOWN_CHILDREN = frozenset({"Status"})

    def _result(self, elem: ET.Element) -> dict:
        self._guard_children(elem, self._RESULT_KNOWN_CHILDREN, "Result")
        result: dict = {}
        _set_if(result, "Decision", elem.get("Decision"))
        status = elem.find(self._t("Status"))
        if status is not None:
            result["Status"] = self._status(status)
        return result

    _STATUS_KNOWN_CHILDREN = frozenset({"StatusCode", "StatusMessage", "StatusDetail"})

    def _status(self, elem: ET.Element) -> dict:
        self._guard_children(elem, self._STATUS_KNOWN_CHILDREN, "Status")
        status: dict = {}
        sc = elem.find(self._t("StatusCode"))
        if sc is not None:
            status["StatusCode"] = {"Value": self._ident(sc.get("Value"))}
        _set_if(status, "StatusMessage", self._text(elem, "StatusMessage"))
        return status
