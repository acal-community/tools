"""
Axiomatics PDP 7.x ALFA dialect reader.

ALFA (Abbreviated Language for Authorization) was submitted to OASIS in March 2014
but was never published as a formally versioned standard. This reader targets the
Axiomatics PDP 7.x dialect, which is the de-facto reference implementation.
See https://alfa.guide/ for the canonical syntax and function reference.

Two-pass conversion:
  Pass 1: _collect_symbols(tree) — walk raw Lark Tree, build _SymbolTable
  Pass 2: AlfaTransformer(symbols, strict) — emit ACAL neutral dict

Grammar uses _ prefix on keyword terminals so they are auto-discarded from
transformer item lists; only value-carrying terminals (PERMIT_KW, CMP_OP, etc.)
remain visible to the transformer.

The grammar is defined inline as _ALFA_GRAMMAR below. It is maintained here
(not as a separate .lark file) to avoid packaging complexity — add the extract
to pyproject.toml package_data only if the grammar grows large enough to warrant
standalone diffing.
"""

from __future__ import annotations

import re
import warnings
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from lark import Lark, Token, Transformer, Tree, UnexpectedInput, v_args
from lark.exceptions import VisitError

# ---------------------------------------------------------------------------
# Exception types
# ---------------------------------------------------------------------------


class ALFASyntaxError(ValueError):
    """Raised when input is not valid ALFA syntax."""


class ALFAUnsupportedFeatureError(ValueError):
    """Raised when a syntactically valid ALFA construct has no ACAL 1.0 equivalent."""


# ---------------------------------------------------------------------------
# Lookup tables
# ---------------------------------------------------------------------------

ACAL_COMBINING_ALGO_MAP: dict[str, str] = {
    "denyOverrides":          "urn:oasis:names:tc:acal:1.0:combining-algorithm:deny-overrides",
    "permitOverrides":        "urn:oasis:names:tc:acal:1.0:combining-algorithm:permit-overrides",
    "firstApplicable":        "urn:oasis:names:tc:acal:1.0:combining-algorithm:first-applicable",
    "denyUnlessPermit":       "urn:oasis:names:tc:acal:1.0:combining-algorithm:deny-unless-permit",
    "permitUnlessDeny":       "urn:oasis:names:tc:acal:1.0:combining-algorithm:permit-unless-deny",
    "onlyOneApplicable":      "urn:oasis:names:tc:acal:1.0:combining-algorithm:only-one-applicable",
    # Ordered variants and onPermitApplySecond — documented on alfa.guide
    "orderedDenyOverrides":   "urn:oasis:names:tc:acal:1.0:combining-algorithm:ordered-deny-overrides",
    "orderedPermitOverrides": "urn:oasis:names:tc:acal:1.0:combining-algorithm:ordered-permit-overrides",
    "onPermitApplySecond":    "urn:oasis:names:tc:acal:1.0:combining-algorithm:on-permit-apply-second",
}

ACAL_CATEGORY_MAP: dict[str, str] = {
    "subject":     "urn:oasis:names:tc:acal:1.0:subject-category:access-subject",
    "resource":    "urn:oasis:names:tc:acal:1.0:attribute-category:resource",
    "action":      "urn:oasis:names:tc:acal:1.0:attribute-category:action",
    "environment": "urn:oasis:names:tc:acal:1.0:attribute-category:environment",
}

# Canonical Attributes.<category>.<id> form → resolved category URN
_CANONICAL_PREFIXES: dict[str, str] = {
    "Attributes.subject":     ACAL_CATEGORY_MAP["subject"],
    "Attributes.resource":    ACAL_CATEGORY_MAP["resource"],
    "Attributes.action":      ACAL_CATEGORY_MAP["action"],
    "Attributes.environment": ACAL_CATEGORY_MAP["environment"],
}

_ACAL_FN = "urn:oasis:names:tc:acal:1.0:function:"

_INFIX_FUNCTION_MAP: dict[str, str] = {
    "&&":  _ACAL_FN + "and",
    "||":  _ACAL_FN + "or",
    "!":   _ACAL_FN + "not",
}

# ACAL comparison functions are per-datatype: there is no generic `equal`, and no
# `*-not-equal` at all (`!=` is `not(<type>-equal(...))`). The datatype an infix operator
# resolves to therefore decides the function, and picking the wrong one silently changes
# the decision — `boolean == boolean` compiled as string-equal is not the same predicate.
#
# Types below are exactly those for which ACAL 1.0 defines the corresponding functions;
# nothing here is synthesized from a naming pattern.
_EQUALITY_TYPES: frozenset[str] = frozenset({
    "string", "boolean", "integer", "double", "date", "dateTime", "time",
    "anyURI", "hexBinary", "base64Binary", "rfc822Name", "x500Name",
    "dayTimeDuration", "yearMonthDuration",
})

# Ordering is defined for a strictly smaller set — notably *not* boolean or anyURI.
_ORDERED_TYPES: frozenset[str] = frozenset({
    "string", "integer", "double", "date", "dateTime", "time",
})

# Function families that take single values in every argument position — the comparisons,
# arithmetic, and the logical connectives. Used to decide whether a bag argument to an
# explicitly named function call has to be reduced. Suffix matching is safe against the
# bag-consuming families: "-set-equals" does not end with "-equal", and "-one-and-only",
# "-bag-size", "-is-in", "-subset" and "-at-least-one-member-of" match nothing here.
_SINGLE_VALUE_FUNCTION_SUFFIXES = (
    "-equal", "-greater-than", "-less-than",
    "-greater-than-or-equal", "-less-than-or-equal",
    "-add", "-subtract", "-multiply", "-divide", "-mod", "-abs",
)
_SINGLE_VALUE_FUNCTION_NAMES = frozenset({"and", "or", "not", "n-of"})

_ORDERING_SUFFIX: dict[str, str] = {
    ">":  "greater-than",
    "<":  "less-than",
    ">=": "greater-than-or-equal",
    "<=": "less-than-or-equal",
}

# Datatype assumed when neither operand reveals one. ACAL's own default for an unstated
# DataType is string, so equality follows that; ordering has no meaningful default, and
# an unresolved ordering comparison is reported rather than guessed.
_DEFAULT_COMPARISON_TYPE = "string"

# All named functions from system.alfa, converted to ACAL 1.0 URNs.
# See https://alfa.guide/ for the canonical Axiomatics PDP 7.x dialect reference.
_NAMED_FUNCTION_MAP: dict[str, str] = {
    # --- Equality ---
    "stringEqual":                   "urn:oasis:names:tc:acal:1.0:function:string-equal",
    "booleanEqual":                  "urn:oasis:names:tc:acal:1.0:function:boolean-equal",
    "integerEqual":                  "urn:oasis:names:tc:acal:1.0:function:integer-equal",
    "doubleEqual":                   "urn:oasis:names:tc:acal:1.0:function:double-equal",
    "dateEqual":                     "urn:oasis:names:tc:acal:1.0:function:date-equal",
    "timeEqual":                     "urn:oasis:names:tc:acal:1.0:function:time-equal",
    "dateTimeEqual":                 "urn:oasis:names:tc:acal:1.0:function:dateTime-equal",
    "dayTimeDurationEqual":          "urn:oasis:names:tc:acal:1.0:function:dayTimeDuration-equal",
    "yearMonthDurationEqual":        "urn:oasis:names:tc:acal:1.0:function:yearMonthDuration-equal",
    "stringEqualIgnoreCase":         "urn:oasis:names:tc:acal:1.0:function:string-equal-ignore-case",
    "anyURIEqual":                   "urn:oasis:names:tc:acal:1.0:function:anyURI-equal",
    "x500NameEqual":                 "urn:oasis:names:tc:acal:1.0:function:x500Name-equal",
    "rfc822NameEqual":               "urn:oasis:names:tc:acal:1.0:function:rfc822Name-equal",
    "hexBinaryEqual":                "urn:oasis:names:tc:acal:1.0:function:hexBinary-equal",
    "base64BinaryEqual":             "urn:oasis:names:tc:acal:1.0:function:base64Binary-equal",
    # --- Arithmetic ---
    "integerAdd":                    "urn:oasis:names:tc:acal:1.0:function:integer-add",
    "doubleAdd":                     "urn:oasis:names:tc:acal:1.0:function:double-add",
    "integerSubtract":               "urn:oasis:names:tc:acal:1.0:function:integer-subtract",
    "doubleSubtract":                "urn:oasis:names:tc:acal:1.0:function:double-subtract",
    "integerMultiply":               "urn:oasis:names:tc:acal:1.0:function:integer-multiply",
    "doubleMultiply":                "urn:oasis:names:tc:acal:1.0:function:double-multiply",
    "integerDivide":                 "urn:oasis:names:tc:acal:1.0:function:integer-divide",
    "doubleDivide":                  "urn:oasis:names:tc:acal:1.0:function:double-divide",
    "integerMod":                    "urn:oasis:names:tc:acal:1.0:function:integer-mod",
    "integerAbs":                    "urn:oasis:names:tc:acal:1.0:function:integer-abs",
    "doubleAbs":                     "urn:oasis:names:tc:acal:1.0:function:double-abs",
    "round":                         "urn:oasis:names:tc:acal:1.0:function:round",
    "floor":                         "urn:oasis:names:tc:acal:1.0:function:floor",
    # --- String manipulation ---
    "stringNormalizeSpace":          "urn:oasis:names:tc:acal:1.0:function:string-normalize-space",
    "stringNormalizeToLowerCase":    "urn:oasis:names:tc:acal:1.0:function:string-normalize-to-lower-case",
    "stringConcatenate":             "urn:oasis:names:tc:acal:1.0:function:string-concatenate",
    "stringContains":                "urn:oasis:names:tc:acal:1.0:function:string-contains",
    "stringStartsWith":              "urn:oasis:names:tc:acal:1.0:function:string-starts-with",
    "stringEndsWith":                "urn:oasis:names:tc:acal:1.0:function:string-ends-with",
    "stringSubString":               "urn:oasis:names:tc:acal:1.0:function:string-substring",
    "anyURIStartsWith":              "urn:oasis:names:tc:acal:1.0:function:anyURI-starts-with",
    "anyURIEndsWith":                "urn:oasis:names:tc:acal:1.0:function:anyURI-ends-with",
    "anyURIContains":                "urn:oasis:names:tc:acal:1.0:function:anyURI-contains",
    "anyURISubString":               "urn:oasis:names:tc:acal:1.0:function:anyURI-substring",
    # --- Type conversion ---
    "doubleToInteger":               "urn:oasis:names:tc:acal:1.0:function:double-to-integer",
    "integerToDouble":               "urn:oasis:names:tc:acal:1.0:function:integer-to-double",
    "booleanFromString":             "urn:oasis:names:tc:acal:1.0:function:boolean-from-string",
    "stringFromBoolean":             "urn:oasis:names:tc:acal:1.0:function:string-from-boolean",
    "integerFromString":             "urn:oasis:names:tc:acal:1.0:function:integer-from-string",
    "stringFromInteger":             "urn:oasis:names:tc:acal:1.0:function:string-from-integer",
    "doubleFromString":              "urn:oasis:names:tc:acal:1.0:function:double-from-string",
    "stringFromDouble":              "urn:oasis:names:tc:acal:1.0:function:string-from-double",
    "timeFromString":                "urn:oasis:names:tc:acal:1.0:function:time-from-string",
    "stringFromTime":                "urn:oasis:names:tc:acal:1.0:function:string-from-time",
    "dateFromString":                "urn:oasis:names:tc:acal:1.0:function:date-from-string",
    "stringFromDate":                "urn:oasis:names:tc:acal:1.0:function:string-from-date",
    "dateTimeFromString":            "urn:oasis:names:tc:acal:1.0:function:dateTime-from-string",
    "stringFromDateTime":            "urn:oasis:names:tc:acal:1.0:function:string-from-dateTime",
    "anyURIFromString":              "urn:oasis:names:tc:acal:1.0:function:anyURI-from-string",
    "stringFromAnyURI":              "urn:oasis:names:tc:acal:1.0:function:string-from-anyURI",
    "dayTimeDurationFromString":     "urn:oasis:names:tc:acal:1.0:function:dayTimeDuration-from-string",
    "stringFromDayTimeDuration":     "urn:oasis:names:tc:acal:1.0:function:string-from-dayTimeDuration",
    "yearMonthDurationFromString":   "urn:oasis:names:tc:acal:1.0:function:yearMonthDuration-from-string",
    "stringFromYearMonthDuration":   "urn:oasis:names:tc:acal:1.0:function:string-from-yearMonthDuration",
    "x500NameFromString":            "urn:oasis:names:tc:acal:1.0:function:x500Name-from-string",
    "stringFromX500Name":            "urn:oasis:names:tc:acal:1.0:function:string-from-x500Name",
    "rfc822NameFromString":          "urn:oasis:names:tc:acal:1.0:function:rfc822Name-from-string",
    "stringFromRfc822Name":          "urn:oasis:names:tc:acal:1.0:function:string-from-rfc822Name",
    "ipAddressFromString":           "urn:oasis:names:tc:acal:1.0:function:ipAddress-from-string",
    "stringFromIpAddress":           "urn:oasis:names:tc:acal:1.0:function:string-from-ipAddress",
    "dnsNameFromString":             "urn:oasis:names:tc:acal:1.0:function:dnsName-from-string",
    "stringFromDnsName":             "urn:oasis:names:tc:acal:1.0:function:string-from-dnsName",
    # --- Logical ---
    "not":                           "urn:oasis:names:tc:acal:1.0:function:not",
    "and":                           "urn:oasis:names:tc:acal:1.0:function:and",
    "or":                            "urn:oasis:names:tc:acal:1.0:function:or",
    "orFunction":                    "urn:oasis:names:tc:acal:1.0:function:or",
    "andFunction":                   "urn:oasis:names:tc:acal:1.0:function:and",
    "nOf":                           "urn:oasis:names:tc:acal:1.0:function:n-of",
    # --- Comparison (typed) ---
    "integerGreaterThan":            "urn:oasis:names:tc:acal:1.0:function:integer-greater-than",
    "integerGreaterThanOrEqual":     "urn:oasis:names:tc:acal:1.0:function:integer-greater-than-or-equal",
    "integerLessThan":               "urn:oasis:names:tc:acal:1.0:function:integer-less-than",
    "integerLessThanOrEqual":        "urn:oasis:names:tc:acal:1.0:function:integer-less-than-or-equal",
    "doubleGreaterThan":             "urn:oasis:names:tc:acal:1.0:function:double-greater-than",
    "doubleGreaterThanOrEqual":      "urn:oasis:names:tc:acal:1.0:function:double-greater-than-or-equal",
    "doubleLessThan":                "urn:oasis:names:tc:acal:1.0:function:double-less-than",
    "doubleLessThanOrEqual":         "urn:oasis:names:tc:acal:1.0:function:double-less-than-or-equal",
    "stringGreaterThan":             "urn:oasis:names:tc:acal:1.0:function:string-greater-than",
    "stringGreaterThanOrEqual":      "urn:oasis:names:tc:acal:1.0:function:string-greater-than-or-equal",
    "stringLessThan":                "urn:oasis:names:tc:acal:1.0:function:string-less-than",
    "stringLessThanOrEqual":         "urn:oasis:names:tc:acal:1.0:function:string-less-than-or-equal",
    "timeGreaterThan":               "urn:oasis:names:tc:acal:1.0:function:time-greater-than",
    "timeGreaterThanOrEqual":        "urn:oasis:names:tc:acal:1.0:function:time-greater-than-or-equal",
    "timeLessThan":                  "urn:oasis:names:tc:acal:1.0:function:time-less-than",
    "timeLessThanOrEqual":           "urn:oasis:names:tc:acal:1.0:function:time-less-than-or-equal",
    "timeInRange":                   "urn:oasis:names:tc:acal:1.0:function:time-in-range",
    "dateTimeGreaterThan":           "urn:oasis:names:tc:acal:1.0:function:dateTime-greater-than",
    "dateTimeGreaterThanOrEqual":    "urn:oasis:names:tc:acal:1.0:function:dateTime-greater-than-or-equal",
    "dateTimeLessThan":              "urn:oasis:names:tc:acal:1.0:function:dateTime-less-than",
    "dateTimeLessThanOrEqual":       "urn:oasis:names:tc:acal:1.0:function:dateTime-less-than-or-equal",
    "dateGreaterThan":               "urn:oasis:names:tc:acal:1.0:function:date-greater-than",
    "dateGreaterThanOrEqual":        "urn:oasis:names:tc:acal:1.0:function:date-greater-than-or-equal",
    "dateLessThan":                  "urn:oasis:names:tc:acal:1.0:function:date-less-than",
    "dateLessThanOrEqual":           "urn:oasis:names:tc:acal:1.0:function:date-less-than-or-equal",
    # --- Date/time arithmetic ---
    "dateTimeAddDayTimeDuration":    "urn:oasis:names:tc:acal:1.0:function:dateTime-add-dayTimeDuration",
    "dateTimeAddYearMonthDuration":  "urn:oasis:names:tc:acal:1.0:function:dateTime-add-yearMonthDuration",
    "dateTimeSubtractDayTimeDuration":   "urn:oasis:names:tc:acal:1.0:function:dateTime-subtract-dayTimeDuration",
    "dateTimeSubtractYearMonthDuration": "urn:oasis:names:tc:acal:1.0:function:dateTime-subtract-yearMonthDuration",
    "dateAddYearMonthDuration":      "urn:oasis:names:tc:acal:1.0:function:date-add-yearMonthDuration",
    "dateSubtractYearMonthDuration": "urn:oasis:names:tc:acal:1.0:function:date-subtract-yearMonthDuration",
    # --- Bag: one-and-only, bag-size, is-in, bag constructor ---
    "stringOneAndOnly":              "urn:oasis:names:tc:acal:1.0:function:string-one-and-only",
    "stringBagSize":                 "urn:oasis:names:tc:acal:1.0:function:string-bag-size",
    "stringIsIn":                    "urn:oasis:names:tc:acal:1.0:function:string-is-in",
    "stringBag":                     "urn:oasis:names:tc:acal:1.0:function:string-bag",
    "booleanOneAndOnly":             "urn:oasis:names:tc:acal:1.0:function:boolean-one-and-only",
    "booleanBagSize":                "urn:oasis:names:tc:acal:1.0:function:boolean-bag-size",
    "booleanIsIn":                   "urn:oasis:names:tc:acal:1.0:function:boolean-is-in",
    "booleanBag":                    "urn:oasis:names:tc:acal:1.0:function:boolean-bag",
    "integerOneAndOnly":             "urn:oasis:names:tc:acal:1.0:function:integer-one-and-only",
    "integerBagSize":                "urn:oasis:names:tc:acal:1.0:function:integer-bag-size",
    "integerIsIn":                   "urn:oasis:names:tc:acal:1.0:function:integer-is-in",
    "integerBag":                    "urn:oasis:names:tc:acal:1.0:function:integer-bag",
    "doubleOneAndOnly":              "urn:oasis:names:tc:acal:1.0:function:double-one-and-only",
    "doubleBagSize":                 "urn:oasis:names:tc:acal:1.0:function:double-bag-size",
    "doubleIsIn":                    "urn:oasis:names:tc:acal:1.0:function:double-is-in",
    "doubleBag":                     "urn:oasis:names:tc:acal:1.0:function:double-bag",
    "timeOneAndOnly":                "urn:oasis:names:tc:acal:1.0:function:time-one-and-only",
    "timeBagSize":                   "urn:oasis:names:tc:acal:1.0:function:time-bag-size",
    "timeIsIn":                      "urn:oasis:names:tc:acal:1.0:function:time-is-in",
    "timeBag":                       "urn:oasis:names:tc:acal:1.0:function:time-bag",
    "dateOneAndOnly":                "urn:oasis:names:tc:acal:1.0:function:date-one-and-only",
    "dateBagSize":                   "urn:oasis:names:tc:acal:1.0:function:date-bag-size",
    "dateIsIn":                      "urn:oasis:names:tc:acal:1.0:function:date-is-in",
    "dateBag":                       "urn:oasis:names:tc:acal:1.0:function:date-bag",
    "dateTimeOneAndOnly":            "urn:oasis:names:tc:acal:1.0:function:dateTime-one-and-only",
    "dateTimeBagSize":               "urn:oasis:names:tc:acal:1.0:function:dateTime-bag-size",
    "dateTimeIsIn":                  "urn:oasis:names:tc:acal:1.0:function:dateTime-is-in",
    "dateTimeBag":                   "urn:oasis:names:tc:acal:1.0:function:dateTime-bag",
    "anyURIOneAndOnly":              "urn:oasis:names:tc:acal:1.0:function:anyURI-one-and-only",
    "anyURIBagSize":                 "urn:oasis:names:tc:acal:1.0:function:anyURI-bag-size",
    "anyURIIsIn":                    "urn:oasis:names:tc:acal:1.0:function:anyURI-is-in",
    "anyURIBag":                     "urn:oasis:names:tc:acal:1.0:function:anyURI-bag",
    "hexBinaryOneAndOnly":           "urn:oasis:names:tc:acal:1.0:function:hexBinary-one-and-only",
    "hexBinaryBagSize":              "urn:oasis:names:tc:acal:1.0:function:hexBinary-bag-size",
    "hexBinaryIsIn":                 "urn:oasis:names:tc:acal:1.0:function:hexBinary-is-in",
    "hexBinaryBag":                  "urn:oasis:names:tc:acal:1.0:function:hexBinary-bag",
    "base64BinaryOneAndOnly":        "urn:oasis:names:tc:acal:1.0:function:base64Binary-one-and-only",
    "base64BinaryBagSize":           "urn:oasis:names:tc:acal:1.0:function:base64Binary-bag-size",
    "base64BinaryIsIn":              "urn:oasis:names:tc:acal:1.0:function:base64Binary-is-in",
    "base64BinaryBag":               "urn:oasis:names:tc:acal:1.0:function:base64Binary-bag",
    "dayTimeDurationOneAndOnly":     "urn:oasis:names:tc:acal:1.0:function:dayTimeDuration-one-and-only",
    "dayTimeDurationBagSize":        "urn:oasis:names:tc:acal:1.0:function:dayTimeDuration-bag-size",
    "dayTimeDurationIsIn":           "urn:oasis:names:tc:acal:1.0:function:dayTimeDuration-is-in",
    "dayTimeDurationBag":            "urn:oasis:names:tc:acal:1.0:function:dayTimeDuration-bag",
    "yearMonthDurationOneAndOnly":   "urn:oasis:names:tc:acal:1.0:function:yearMonthDuration-one-and-only",
    "yearMonthDurationBagSize":      "urn:oasis:names:tc:acal:1.0:function:yearMonthDuration-bag-size",
    "yearMonthDurationIsIn":         "urn:oasis:names:tc:acal:1.0:function:yearMonthDuration-is-in",
    "yearMonthDurationBag":          "urn:oasis:names:tc:acal:1.0:function:yearMonthDuration-bag",
    "x500NameOneAndOnly":            "urn:oasis:names:tc:acal:1.0:function:x500Name-one-and-only",
    "x500NameBagSize":               "urn:oasis:names:tc:acal:1.0:function:x500Name-bag-size",
    "x500NameIsIn":                  "urn:oasis:names:tc:acal:1.0:function:x500Name-is-in",
    "x500NameBag":                   "urn:oasis:names:tc:acal:1.0:function:x500Name-bag",
    "rfc822NameOneAndOnly":          "urn:oasis:names:tc:acal:1.0:function:rfc822Name-one-and-only",
    "rfc822NameBagSize":             "urn:oasis:names:tc:acal:1.0:function:rfc822Name-bag-size",
    "rfc822NameIsIn":                "urn:oasis:names:tc:acal:1.0:function:rfc822Name-is-in",
    "rfc822NameBag":                 "urn:oasis:names:tc:acal:1.0:function:rfc822Name-bag",
    "ipAddressOneAndOnly":           "urn:oasis:names:tc:acal:1.0:function:ipAddress-one-and-only",
    "ipAddressBagSize":              "urn:oasis:names:tc:acal:1.0:function:ipAddress-bag-size",
    "ipAddressBag":                  "urn:oasis:names:tc:acal:1.0:function:ipAddress-bag",
    "dnsNameOneAndOnly":             "urn:oasis:names:tc:acal:1.0:function:dnsName-one-and-only",
    "dnsNameBagSize":                "urn:oasis:names:tc:acal:1.0:function:dnsName-bag-size",
    "dnsNameBag":                    "urn:oasis:names:tc:acal:1.0:function:dnsName-bag",
    # --- Bag set operations ---
    "stringAtLeastOneMemberOf":      "urn:oasis:names:tc:acal:1.0:function:string-at-least-one-member-of",
    "stringSubset":                  "urn:oasis:names:tc:acal:1.0:function:string-subset",
    "stringSubSet":                  "urn:oasis:names:tc:acal:1.0:function:string-subset",
    "stringSetEquals":               "urn:oasis:names:tc:acal:1.0:function:string-set-equals",
    "stringIntersection":            "urn:oasis:names:tc:acal:1.0:function:string-intersection",
    "stringUnion":                   "urn:oasis:names:tc:acal:1.0:function:string-union",
    "booleanAtLeastOneMemberOf":     "urn:oasis:names:tc:acal:1.0:function:boolean-at-least-one-member-of",
    "booleanSubSet":                 "urn:oasis:names:tc:acal:1.0:function:boolean-subset",
    "booleanSetEquals":              "urn:oasis:names:tc:acal:1.0:function:boolean-set-equals",
    "booleanIntersection":           "urn:oasis:names:tc:acal:1.0:function:boolean-intersection",
    "booleanUnion":                  "urn:oasis:names:tc:acal:1.0:function:boolean-union",
    "integerAtLeastOneMemberOf":     "urn:oasis:names:tc:acal:1.0:function:integer-at-least-one-member-of",
    "integerSubSet":                 "urn:oasis:names:tc:acal:1.0:function:integer-subset",
    "integerSetEquals":              "urn:oasis:names:tc:acal:1.0:function:integer-set-equals",
    "integerIntersection":           "urn:oasis:names:tc:acal:1.0:function:integer-intersection",
    "integerUnion":                  "urn:oasis:names:tc:acal:1.0:function:integer-union",
    "doubleAtLeastOneMemberOf":      "urn:oasis:names:tc:acal:1.0:function:double-at-least-one-member-of",
    "doubleSubSet":                  "urn:oasis:names:tc:acal:1.0:function:double-subset",
    "doubleSetEquals":               "urn:oasis:names:tc:acal:1.0:function:double-set-equals",
    "doubleIntersection":            "urn:oasis:names:tc:acal:1.0:function:double-intersection",
    "doubleUnion":                   "urn:oasis:names:tc:acal:1.0:function:double-union",
    "timeAtLeastOneMemberOf":        "urn:oasis:names:tc:acal:1.0:function:time-at-least-one-member-of",
    "timeSubSet":                    "urn:oasis:names:tc:acal:1.0:function:time-subset",
    "timeSetEquals":                 "urn:oasis:names:tc:acal:1.0:function:time-set-equals",
    "timeIntersection":              "urn:oasis:names:tc:acal:1.0:function:time-intersection",
    "timeUnion":                     "urn:oasis:names:tc:acal:1.0:function:time-union",
    "dateAtLeastOneMemberOf":        "urn:oasis:names:tc:acal:1.0:function:date-at-least-one-member-of",
    "dateSubSet":                    "urn:oasis:names:tc:acal:1.0:function:date-subset",
    "dateSetEquals":                 "urn:oasis:names:tc:acal:1.0:function:date-set-equals",
    "dateIntersection":              "urn:oasis:names:tc:acal:1.0:function:date-intersection",
    "dateUnion":                     "urn:oasis:names:tc:acal:1.0:function:date-union",
    "dateTimeAtLeastOneMemberOf":    "urn:oasis:names:tc:acal:1.0:function:dateTime-at-least-one-member-of",
    "dateTimeSubSet":                "urn:oasis:names:tc:acal:1.0:function:dateTime-subset",
    "dateTimeSetEquals":             "urn:oasis:names:tc:acal:1.0:function:dateTime-set-equals",
    "dateTimeIntersection":          "urn:oasis:names:tc:acal:1.0:function:dateTime-intersection",
    "dateTimeUnion":                 "urn:oasis:names:tc:acal:1.0:function:dateTime-union",
    "anyURIAtLeastOneMemberOf":      "urn:oasis:names:tc:acal:1.0:function:anyURI-at-least-one-member-of",
    "anyURISubSet":                  "urn:oasis:names:tc:acal:1.0:function:anyURI-subset",
    "anyURISetEquals":               "urn:oasis:names:tc:acal:1.0:function:anyURI-set-equals",
    "anyURIIntersection":            "urn:oasis:names:tc:acal:1.0:function:anyURI-intersection",
    "anyURIUnion":                   "urn:oasis:names:tc:acal:1.0:function:anyURI-union",
    "hexBinaryAtLeastOneMemberOf":   "urn:oasis:names:tc:acal:1.0:function:hexBinary-at-least-one-member-of",
    "hexBinarySubSet":               "urn:oasis:names:tc:acal:1.0:function:hexBinary-subset",
    "hexBinarySetEquals":            "urn:oasis:names:tc:acal:1.0:function:hexBinary-set-equals",
    "hexBinaryIntersection":         "urn:oasis:names:tc:acal:1.0:function:hexBinary-intersection",
    "hexBinaryUnion":                "urn:oasis:names:tc:acal:1.0:function:hexBinary-union",
    "base64BinaryAtLeastOneMemberOf": "urn:oasis:names:tc:acal:1.0:function:base64Binary-at-least-one-member-of",
    "base64BinarySubSet":            "urn:oasis:names:tc:acal:1.0:function:base64Binary-subset",
    "base64BinarySetEquals":         "urn:oasis:names:tc:acal:1.0:function:base64Binary-set-equals",
    "base64BinaryIntersection":      "urn:oasis:names:tc:acal:1.0:function:base64Binary-intersection",
    "base64BinaryUnion":             "urn:oasis:names:tc:acal:1.0:function:base64Binary-union",
    "dayTimeDurationAtLeastOneMemberOf": "urn:oasis:names:tc:acal:1.0:function:dayTimeDuration-at-least-one-member-of",
    "dayTimeDurationSubSet":         "urn:oasis:names:tc:acal:1.0:function:dayTimeDuration-subset",
    "dayTimeDurationSetEquals":      "urn:oasis:names:tc:acal:1.0:function:dayTimeDuration-set-equals",
    "dayTimeDurationIntersection":   "urn:oasis:names:tc:acal:1.0:function:dayTimeDuration-intersection",
    "dayTimeDurationUnion":          "urn:oasis:names:tc:acal:1.0:function:dayTimeDuration-union",
    "yearMonthDurationAtLeastOneMemberOf": "urn:oasis:names:tc:acal:1.0:function:yearMonthDuration-at-least-one-member-of",
    "yearMonthDurationSubSet":       "urn:oasis:names:tc:acal:1.0:function:yearMonthDuration-subset",
    "yearMonthDurationSetEquals":    "urn:oasis:names:tc:acal:1.0:function:yearMonthDuration-set-equals",
    "yearMonthDurationIntersection": "urn:oasis:names:tc:acal:1.0:function:yearMonthDuration-intersection",
    "yearMonthDurationUnion":        "urn:oasis:names:tc:acal:1.0:function:yearMonthDuration-union",
    "x500NameAtLeastOneMemberOf":    "urn:oasis:names:tc:acal:1.0:function:x500Name-at-least-one-member-of",
    "x500NameSubSet":                "urn:oasis:names:tc:acal:1.0:function:x500Name-subset",
    "x500NameSetEquals":             "urn:oasis:names:tc:acal:1.0:function:x500Name-set-equals",
    "x500NameIntersection":          "urn:oasis:names:tc:acal:1.0:function:x500Name-intersection",
    "x500NameUnion":                 "urn:oasis:names:tc:acal:1.0:function:x500Name-union",
    "rfc822NameAtLeastOneMemberOf":  "urn:oasis:names:tc:acal:1.0:function:rfc822Name-at-least-one-member-of",
    "rfc822NameSubSet":              "urn:oasis:names:tc:acal:1.0:function:rfc822Name-subset",
    "rfc822NameSetEquals":           "urn:oasis:names:tc:acal:1.0:function:rfc822Name-set-equals",
    "rfc822NameIntersection":        "urn:oasis:names:tc:acal:1.0:function:rfc822Name-intersection",
    "rfc822NameUnion":               "urn:oasis:names:tc:acal:1.0:function:rfc822Name-union",
    # --- Higher-order bag functions ---
    "anyOf":                         "urn:oasis:names:tc:acal:1.0:function:any-of",
    "allOf":                         "urn:oasis:names:tc:acal:1.0:function:all-of",
    "anyOfAny":                      "urn:oasis:names:tc:acal:1.0:function:any-of-any",
    "allOfAny":                      "urn:oasis:names:tc:acal:1.0:function:all-of-any",
    "anyOfAll":                      "urn:oasis:names:tc:acal:1.0:function:any-of-all",
    "allOfAll":                      "urn:oasis:names:tc:acal:1.0:function:all-of-all",
    "map":                           "urn:oasis:names:tc:acal:1.0:function:map",
    # --- Match functions ---
    "x500NameMatch":                 "urn:oasis:names:tc:acal:1.0:function:x500Name-match",
    "rfc822NameMatch":               "urn:oasis:names:tc:acal:1.0:function:rfc822Name-match",
    "stringRegexpMatch":             "urn:oasis:names:tc:acal:1.0:function:string-regexp-match",
    "anyURIRegexpMatch":             "urn:oasis:names:tc:acal:1.0:function:anyURI-regexp-match",
    "ipAddressRegexpMatch":          "urn:oasis:names:tc:acal:1.0:function:ipAddress-regexp-match",
    "dnsNameRegexpMatch":            "urn:oasis:names:tc:acal:1.0:function:dnsName-regexp-match",
    "rfc822NameRegexpMatch":         "urn:oasis:names:tc:acal:1.0:function:rfc822Name-regexp-match",
    "x500NameRegexpMatch":           "urn:oasis:names:tc:acal:1.0:function:x500Name-regexp-match",
    # --- XPath functions (noted: xpath type has no ACAL 1.0 equivalent) ---
    "xpathNodeCount":                "urn:oasis:names:tc:acal:1.0:function:xpath-node-count",
    "xpathNodeEqual":                "urn:oasis:names:tc:acal:1.0:function:xpath-node-equal",
    "xpathNodeMatch":                "urn:oasis:names:tc:acal:1.0:function:xpath-node-match",
}

# Map from ALFA type name to the ACAL is-in function for bag membership tests.
# Used in cmp_expr when is_bag=True and operator is == or !=.
_ACAL_DATATYPE = "urn:oasis:names:tc:acal:1.0:data-type:"
_ACAL_STRING_DATATYPE = _ACAL_DATATYPE + "string"

# ALFA declares a datatype by short name (`type = boolean`); ACAL identifies it by URN.
# Every name here was checked to exist as urn:oasis:names:tc:acal:1.0:data-type:<name>.
# Two ALFA type names are deliberately absent:
#   `xpath` — has no ACAL 1.0 equivalent, already reported by _process_attribute;
#   `bag`   — a cardinality modifier, stripped at declaration time and never a DataType.
_ALFA_DATATYPE_NAMES: frozenset[str] = frozenset({
    "string", "boolean", "integer", "double", "date", "dateTime", "time",
    "dayTimeDuration", "yearMonthDuration", "anyURI", "dnsName", "ipAddress",
    "x500Name", "rfc822Name", "hexBinary", "base64Binary",
})


def _apply_return_type(fn_id: str) -> str | None:
    """Datatype an Apply yields, where the function's own name settles it.

    Only shapes whose return type is unambiguous from the ACAL function name are read:
    ``<type>-one-and-only`` yields that type, ``<type>-bag-size`` yields integer, and
    ``<type>-from-string`` yields that type. Anything else returns None rather than a guess.
    """
    tail = fn_id.rsplit(":", 1)[-1]
    if tail.endswith("-bag-size"):
        return "integer"
    for suffix in ("-one-and-only", "-from-string"):
        if tail.endswith(suffix):
            candidate = tail[: -len(suffix)]
            if candidate in _EQUALITY_TYPES:
                return candidate
    return None


# Functions whose result is a bag rather than a single value. `<type>-bag-size` is
# deliberately not matched by the `-bag` suffix — it returns an integer.
_BAG_RETURNING_SUFFIXES = ("-bag", "-bag-intersection", "-bag-union")


def _is_bag_valued(node: Any) -> bool:
    """Whether an operand yields a bag rather than a single value.

    An attribute designator always yields a bag — that is the model, not a property of how
    the attribute was declared — so a comparison against one has to be bridged even when
    the source treats the attribute as single-valued.
    """
    if not isinstance(node, dict):
        return False
    if "AttributeDesignator" in node or "AttributeSelector" in node:
        return True
    if "Apply" in node:
        tail = node["Apply"].get("FunctionId", "").rsplit(":", 1)[-1]
        return tail == "map" or tail.endswith(_BAG_RETURNING_SUFFIXES)
    return False


def _operand_datatype(node: Any) -> tuple[str | None, bool]:
    """(datatype, is_declared) for a comparison operand.

    ``is_declared`` marks evidence that settles the type — a designator's declared
    DataType, a resolvable function return type, or a non-string literal. A bare string
    literal is *not* declarative: ALFA compares string literals against several datatypes,
    so it must not override the other operand's declared type.
    """
    if not isinstance(node, dict):
        return None, False
    if "AttributeDesignator" in node:
        return node["AttributeDesignator"].get("DataType") or None, True
    if "Apply" in node:
        return _apply_return_type(node["Apply"].get("FunctionId", "")), True
    if "Value" in node:
        value = node["Value"]
        # bool before int: bool is a subclass of int in Python.
        if isinstance(value, bool):
            return "boolean", True
        if isinstance(value, int):
            return "integer", True
        if isinstance(value, float):
            return "double", True
        if isinstance(value, str):
            return "string", False
    return None, False


_TYPE_IS_IN_MAP: dict[str, str] = {
    "string":              "urn:oasis:names:tc:acal:1.0:function:string-is-in",
    "integer":             "urn:oasis:names:tc:acal:1.0:function:integer-is-in",
    "boolean":             "urn:oasis:names:tc:acal:1.0:function:boolean-is-in",
    "double":              "urn:oasis:names:tc:acal:1.0:function:double-is-in",
    "date":                "urn:oasis:names:tc:acal:1.0:function:date-is-in",
    "time":                "urn:oasis:names:tc:acal:1.0:function:time-is-in",
    "dateTime":            "urn:oasis:names:tc:acal:1.0:function:dateTime-is-in",
    "anyURI":              "urn:oasis:names:tc:acal:1.0:function:anyURI-is-in",
    "hexBinary":           "urn:oasis:names:tc:acal:1.0:function:hexBinary-is-in",
    "base64Binary":        "urn:oasis:names:tc:acal:1.0:function:base64Binary-is-in",
    "x500Name":            "urn:oasis:names:tc:acal:1.0:function:x500Name-is-in",
    "rfc822Name":          "urn:oasis:names:tc:acal:1.0:function:rfc822Name-is-in",
    "dayTimeDuration":     "urn:oasis:names:tc:acal:1.0:function:dayTimeDuration-is-in",
    "yearMonthDuration":   "urn:oasis:names:tc:acal:1.0:function:yearMonthDuration-is-in",
}

# ---------------------------------------------------------------------------
# Symbol table
# ---------------------------------------------------------------------------


@dataclass
class _AttributeDecl:
    id: str       # full AttributeId (URN or qualified name)
    category: str  # ACAL category URN
    type: str      # "string", "integer", etc.  ("" if unknown)
    is_bag: bool


@dataclass
class _SymbolTable:
    namespace_parts: list[str] = field(default_factory=list)
    attributes: dict[str, _AttributeDecl] = field(default_factory=dict)
    obligations: dict[str, str] = field(default_factory=dict)
    advice: dict[str, str] = field(default_factory=dict)
    # id(Tree.meta) of each policy_decl/policyset_decl node -> the namespace path
    # enclosing it. Tree.meta is the same object across the symbol-collection pass
    # and the transform pass (both walk the one parse tree), so its identity is a
    # stable key even though Transformer processes bottom-up and can't otherwise
    # tell a policy_decl which namespace it's nested in.
    decl_namespace: dict[int, list[str]] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Grammar
#
# Covers the Axiomatics PDP 7.x ALFA dialect as documented on https://alfa.guide/
# Structural keywords use _ prefix so Lark discards them from transformer
# item lists.  Value-carrying terminals (PERMIT_KW, DENY_KW, CMP_OP, etc.)
# keep their names so the transformer can read their values.
# ---------------------------------------------------------------------------

_ALFA_GRAMMAR = r"""
start: namespace_decl+

namespace_decl: _NAMESPACE_KW DOTTED_ID "{" namespace_body "}"
namespace_body: (namespace_decl
               | import_stmt
               | attribute_decl
               | obligation_decl
               | advice_decl
               | policyset_decl
               | policy_decl
               | rulecombinator_decl
               | policycombinator_decl
               | type_sys_decl
               | category_sys_decl
               | function_decl
               | infix_decl)*

import_stmt: _IMPORT_KW DOTTED_ID

attribute_decl: _ATTRIBUTE_KW IDENTIFIER "{" attribute_body "}"
attribute_body: (category_clause | id_clause | type_clause | datatype_clause)*
category_clause: _CATEGORY_KW "=" category_value ";"?
id_clause: _ID_KW "=" STRING ";"?
type_clause: _TYPE_KW "=" IDENTIFIER ";"?
datatype_clause: _DATATYPE_KW "=" IDENTIFIER ";"?
category_value: DOTTED_ID

obligation_decl: _OBLIGATION_KW DOTTED_ID ("=" STRING | STRING)? ";"?
advice_decl:     _ADVICE_KW     DOTTED_ID ("=" STRING | STRING)? ";"?

// system.alfa-style runtime config declarations — parsed and discarded
rulecombinator_decl:   "ruleCombinator"   IDENTIFIER "=" STRING ";"?
policycombinator_decl: "policyCombinator" IDENTIFIER "=" STRING ";"?
type_sys_decl:         _TYPE_KW           IDENTIFIER "=" STRING ";"?
category_sys_decl:     _CATEGORY_KW       IDENTIFIER "=" STRING ";"?
function_decl:         "function"         IDENTIFIER "=" STRING SYS_DECL_TAIL?
infix_decl:            "infix"            SYS_DECL_HEADER "{" INFIX_BODY? "}" SYS_DECL_TAIL?

SYS_DECL_TAIL:   /[^\n\r]+/
SYS_DECL_HEADER: /[^{\n\r]+/
INFIX_BODY:      /[^}]+/

policyset_decl: _POLICYSET_KW IDENTIFIER applying_kw? "{" policyset_body "}"
policyset_body: (namespace_decl | policyset_decl | policy_decl | target_clause | on_clause | var_decl | ref_stmt | applying_kw)*
applying_kw: _APPLY_KW (DOTTED_ID | IDENTIFIER)

// Bare policy/policyset reference (e.g. cross-references within a namespace)
ref_stmt: DOTTED_ID

policy_decl: _POLICY_KW IDENTIFIER applying_kw? "{" policy_body "}"
policy_body: (rule_decl | target_clause | on_clause | var_decl | applying_kw)*

rule_decl: _RULE_KW IDENTIFIER? "{" rule_body "}"
rule_body: (effect_clause | target_clause | condition_clause | on_clause)*

effect_clause: (PERMIT_KW | DENY_KW)
target_clause:    _TARGET_KW    _CLAUSE_KW? condition_expr
condition_clause: _CONDITION_KW condition_expr

on_clause: _ON_KW (PERMIT_KW | DENY_KW) "{" on_body "}"
on_body: (obligation_ref | advice_ref)*
obligation_ref: _OBLIGATION_KW DOTTED_ID ("{" aae_block "}" | ("(" aae_list? ")")? ";"?)
advice_ref:     _ADVICE_KW     DOTTED_ID ("{" aae_block "}" | ("(" aae_list? ")")? ";"?)
aae_block: aae_entry*
aae_list: aae_entry ("," aae_entry)*
aae_entry: DOTTED_ID "=" expr

var_decl: _VAR_KW IDENTIFIER "=" expr ";"?

// Expressions — precedence encoded in rule nesting
condition_expr: or_expr
or_expr:   and_expr ((OR_OP | OR_WORD_OP) and_expr)*
and_expr:  not_expr ((AND_OP | AND_WORD_OP) not_expr)*
not_expr:  NOT_OP not_expr  -> not_expr
          | cmp_expr
cmp_expr:  primary_expr (CMP_OP primary_expr)?
primary_expr: "(" condition_expr ")"   -> paren_expr
            | func_call
            | var_ref
            | attr_path
            | literal

func_call: DOTTED_ID "(" arg_list? ")"
arg_list:  expr ("," expr)*
expr:      condition_expr

var_ref: VAR_REF_KW "(" IDENTIFIER ")"

attr_path: DOTTED_ID

literal: STRING    -> string_literal
       | INTEGER   -> integer_literal
       | FLOAT     -> float_literal
       | BOOL_KW   -> bool_literal

// Terminals — _ prefix means Lark auto-discards from parse tree
_NAMESPACE_KW:  "namespace"
_IMPORT_KW:     "import"
_POLICYSET_KW:  "policyset"
_POLICY_KW:     "policy"
_RULE_KW:       "rule"
_ATTRIBUTE_KW:  "attribute"
_OBLIGATION_KW: "obligation"
_ADVICE_KW:     "advice"
_APPLY_KW:      "apply"
_TARGET_KW:     "target"
_CONDITION_KW:  "condition"
_ON_KW:         "on"
_VAR_KW:        "var"
_CATEGORY_KW:   "category"
_ID_KW:         "id"
_TYPE_KW:       "type"
_DATATYPE_KW:   "datatype"
_CLAUSE_KW:     "clause"

// Value-carrying terminals — kept in parse tree
PERMIT_KW:  "permit"
DENY_KW:    "deny"
BOOL_KW:    "true" | "false"
VAR_REF_KW: "variable"

OR_OP:       "||"
AND_OP:      "&&"
OR_WORD_OP:  /or(?![a-zA-Z0-9_-])/
AND_WORD_OP: /and(?![a-zA-Z0-9_-])/
NOT_OP: "!"
CMP_OP: "==" | "!=" | ">=" | "<=" | ">" | "<"

// DOTTED_ID must not match ALFA reserved words that have their own terminals.
// The negative lookahead excludes exact keyword matches at start of the token.
DOTTED_ID: /(?!(namespace|import|policyset|policy|rule|attribute|obligation|advice|apply|target|clause|condition|permit|deny|on\b|var\b|variable|category|id\b|type\b|datatype|true|false|and\b|or\b|function\b|infix\b|ruleCombinator\b|policyCombinator\b)[^a-zA-Z0-9_])[a-zA-Z_][a-zA-Z0-9_-]*(\.[a-zA-Z_][a-zA-Z0-9_-]*)*/
IDENTIFIER: /[a-zA-Z_][a-zA-Z0-9_]*/
INTEGER: /[0-9]+/
FLOAT:   /[0-9]+\.[0-9]*/
STRING:  /\"[^\"]*\"|'[^']*'/

%import common.WS
%ignore WS
%ignore /\/\/[^\n]*/
%ignore /\/\*(.|\n)*?\*\//
"""

_PARSER = Lark(_ALFA_GRAMMAR, parser="earley", ambiguity="resolve")


# ---------------------------------------------------------------------------
# Pass 1: symbol collection (works on raw Tree, before transformer)
# ---------------------------------------------------------------------------


def _token_value(node: Tree, token_type: str) -> str | None:
    """Return the value of the first Token with the given type among direct children."""
    for child in node.children:
        if isinstance(child, Token) and child.type == token_type:
            return str(child)
    return None


def _collect_symbols(tree: Tree, strict: bool = False) -> _SymbolTable:
    st = _SymbolTable()
    _walk_tree_for_namespaces(tree, st, [], strict)
    return st


def _merge_into(base: _SymbolTable, other: _SymbolTable) -> None:
    """Merge other's symbols into base in-place.

    Attribute, obligation, and advice mappings from other are added to base;
    keys already in base are overwritten (main file wins when processed last).
    namespace_parts: whichever is deeper wins — the main policy file is always
    processed after includes, so its namespace_parts take precedence when equal.
    """
    base.attributes.update(other.attributes)
    base.obligations.update(other.obligations)
    base.advice.update(other.advice)
    base.decl_namespace.update(other.decl_namespace)
    if len(other.namespace_parts) >= len(base.namespace_parts):
        base.namespace_parts = other.namespace_parts


def _walk_tree_for_namespaces(
    tree: Tree, st: _SymbolTable, parent_parts: list[str], strict: bool = False
) -> None:
    for child in tree.children:
        if isinstance(child, Tree) and child.data == "namespace_decl":
            _process_namespace(child, st, parent_parts, strict)


def _process_namespace(
    node: Tree, st: _SymbolTable, parent_parts: list[str], strict: bool = False
) -> None:
    dotted_id = _token_value(node, "DOTTED_ID")
    if dotted_id is None:
        return
    parts = parent_parts + dotted_id.split(".")

    body = next((c for c in node.children if isinstance(c, Tree) and c.data == "namespace_body"), None)
    if body is None:
        return

    for child in body.children:
        if not isinstance(child, Tree):
            continue
        if child.data == "namespace_decl":
            _process_namespace(child, st, parts, strict)
        elif child.data == "policy_decl":
            _process_policy_decl(child, st, parts)
        elif child.data == "policyset_decl":
            _process_policyset_decl(child, st, parts, strict)
        elif child.data == "attribute_decl":
            _process_attribute(child, st, parts, strict)
        elif child.data == "obligation_decl":
            _process_notice_decl(child, st, "obligation", parts)
        elif child.data == "advice_decl":
            _process_notice_decl(child, st, "advice", parts)

    # Track deepest namespace as PolicyId prefix
    if len(parts) >= len(st.namespace_parts):
        st.namespace_parts = parts


def _process_policy_decl(node: Tree, st: _SymbolTable, parts: list[str]) -> None:
    """Record the namespace enclosing this policy, and each of its rules (a policy
    body can only ever contain rules, never a nested policy/policyset — see grammar)."""
    st.decl_namespace[id(node.meta)] = parts
    body = next((c for c in node.children if isinstance(c, Tree) and c.data == "policy_body"), None)
    if body is None:
        return
    for child in body.children:
        if isinstance(child, Tree) and child.data == "rule_decl":
            st.decl_namespace[id(child.meta)] = parts


def _process_policyset_decl(
    node: Tree, st: _SymbolTable, parts: list[str], strict: bool = False
) -> None:
    """Record the namespace enclosing this policyset, then recurse: a policyset body
    may itself contain namespace_decl, policy_decl and policyset_decl (unlike a plain
    policy body), so nested declarations need the same treatment as top-level ones."""
    st.decl_namespace[id(node.meta)] = parts
    body = next((c for c in node.children if isinstance(c, Tree) and c.data == "policyset_body"), None)
    if body is None:
        return
    for child in body.children:
        if not isinstance(child, Tree):
            continue
        if child.data == "namespace_decl":
            _process_namespace(child, st, parts, strict)
        elif child.data == "policy_decl":
            _process_policy_decl(child, st, parts)
        elif child.data == "policyset_decl":
            _process_policyset_decl(child, st, parts, strict)


def _process_attribute(
    node: Tree, st: _SymbolTable, ns_parts: list[str], strict: bool = False
) -> None:
    local_name = _token_value(node, "IDENTIFIER")
    if local_name is None:
        return

    body = next((c for c in node.children if isinstance(c, Tree) and c.data == "attribute_body"), None)
    category_urn = ""
    attr_id = ".".join(ns_parts + [local_name])
    attr_type = ""
    is_bag = False

    if body:
        for clause in body.children:
            if not isinstance(clause, Tree):
                continue
            if clause.data == "category_clause":
                cat_node = next(
                    (c for c in clause.children if isinstance(c, Tree) and c.data == "category_value"),
                    None,
                )
                if cat_node:
                    raw = _token_value(cat_node, "DOTTED_ID") or ""
                    # Resolve shorthand category aliases (subjectCat → subject)
                    raw_lower = raw.replace("Cat", "").lower()
                    category_urn = ACAL_CATEGORY_MAP.get(raw_lower, ACAL_CATEGORY_MAP.get(raw, raw))
            elif clause.data == "id_clause":
                raw_str = _token_value(clause, "STRING") or ""
                attr_id = raw_str.strip("\"'")
            elif clause.data == "type_clause":
                attr_type = _token_value(clause, "IDENTIFIER") or ""
                if attr_type == "bag":
                    is_bag = True
                    attr_type = ""  # "bag" is a cardinality modifier, not a data type
            elif clause.data == "datatype_clause":
                if not attr_type:
                    attr_type = _token_value(clause, "IDENTIFIER") or ""

    if not category_urn:
        raise ALFASyntaxError(
            f"Attribute {local_name!r} has no 'category' clause. "
            "Every attribute block must declare a category."
        )

    if attr_type == "xpath":
        msg = (
            f"Attribute {local_name!r} declares type 'xpath', which has no ACAL 1.0 equivalent "
            "(ACAL 1.0 does not include the xpathExpression data type). "
            "The attribute will pass through as-is; XPath-dependent evaluation at the PDP may fail."
        )
        if strict:
            raise ALFAUnsupportedFeatureError(msg)
        warnings.warn(msg, UserWarning, stacklevel=4)

    decl = _AttributeDecl(id=attr_id, category=category_urn, type=attr_type, is_bag=is_bag)
    st.attributes[local_name] = decl
    # Also index by the namespace-qualified name (e.g. "resource.kind"), so a
    # reference written that way resolves even when it differs from the bare
    # local name — common idiomatic ALFA style, independent of what `id` is set to.
    qualified_name = ".".join(ns_parts + [local_name])
    if qualified_name != local_name:
        st.attributes.setdefault(qualified_name, decl)


def _process_notice_decl(
    node: Tree, st: _SymbolTable, kind: str, ns_parts: list[str]
) -> None:
    dotted = _token_value(node, "DOTTED_ID")
    if dotted is None:
        return
    local_name = dotted.split(".")[-1]
    # Use the explicit STRING URN if given, otherwise synthesize from namespace
    explicit_urn = _token_value(node, "STRING")
    if explicit_urn:
        urn = explicit_urn.strip("\"'")
    elif ":" in dotted:
        urn = dotted
    else:
        urn = "urn:" + ".".join(ns_parts + dotted.split("."))
    if kind == "obligation":
        st.obligations[local_name] = urn
    else:
        st.advice[local_name] = urn


# ---------------------------------------------------------------------------
# Pass 2: transformer
# ---------------------------------------------------------------------------


@v_args(inline=False)
class AlfaTransformer(Transformer):

    def __init__(self, symbols: _SymbolTable, strict: bool = False, fail_closed: bool = False) -> None:
        super().__init__()
        self._symbols = symbols
        self._strict = strict
        self._fail_closed = fail_closed
        self._current_vars: dict[str, str] = {}
        self._ns_parts: list[str] = list(symbols.namespace_parts)

    def _decl_ns_parts(self, meta) -> list[str]:
        """The namespace path actually enclosing this policy/policyset/rule
        declaration (recorded per-node during symbol collection, since Transformer
        runs bottom-up and can't otherwise tell a node which namespace it's in).

        Falls back to the single global namespace_parts (matching the reader's
        pre-fix behaviour) if this node wasn't seen during symbol collection —
        should not happen given the grammar, but keeps this from ever raising.
        """
        return self._symbols.decl_namespace.get(id(meta), self._ns_parts)

    def _must_be_present(self) -> bool:
        """ALFA compiles to XACML 3.0, whose MustBePresent default is False, so ALFA's real
        runtime behaviour is fail-open on a missing attribute. Emitted explicitly (never
        omitted) per presence-semantics-must-be-explicit; fail_closed flips it to deny."""
        return bool(self._fail_closed)

    def _warn_or_raise(self, msg: str) -> None:
        if self._strict:
            raise ALFAUnsupportedFeatureError(msg)
        warnings.warn(msg, UserWarning, stacklevel=4)

    # -----------------------------------------------------------------------
    # Top-level
    # -----------------------------------------------------------------------

    def start(self, items: list) -> dict:
        policies: list[dict] = []
        for item in items:
            if isinstance(item, dict):
                if "Policy" in item:
                    policies.append(item["Policy"])
                elif "PolicySet" in item:
                    policies.append(item["PolicySet"])
                elif "Bundle" in item:
                    policies.extend(item["Bundle"].get("Policy", []))
        if len(policies) == 1:
            return {"Policy": policies[0]}
        if policies:
            return {"Bundle": {"Policy": policies}}
        return {}

    def namespace_decl(self, items: list) -> dict:
        # items: [Token('DOTTED_ID', ...), namespace_body_result]
        # (NAMESPACE_KW is discarded via _ prefix)
        body = next((i for i in items if isinstance(i, list)), [])
        policies = []
        for item in body:
            if isinstance(item, dict):
                if "Policy" in item:
                    policies.append(item["Policy"])
                elif "PolicySet" in item:
                    # PolicySet at namespace level: expose as top-level Policy in neutral dict
                    policies.append(item["PolicySet"])
                elif "Bundle" in item:
                    policies.extend(item["Bundle"].get("Policy", []))
        if len(policies) == 1:
            return {"Policy": policies[0]}
        if policies:
            return {"Bundle": {"Policy": policies}}
        return {}

    def namespace_body(self, items: list) -> list:
        return [i for i in items if isinstance(i, dict)]

    # -----------------------------------------------------------------------
    # Declarations handled in pass 1; return None here
    # -----------------------------------------------------------------------

    def attribute_decl(self, items: list) -> None:
        return None

    def attribute_body(self, items: list) -> None:
        return None

    def category_clause(self, items: list) -> None:
        return None

    def id_clause(self, items: list) -> None:
        return None

    def type_clause(self, items: list) -> None:
        return None

    def datatype_clause(self, items: list) -> None:
        return None

    def category_value(self, items: list) -> None:
        return None

    def obligation_decl(self, items: list) -> None:
        return None

    def advice_decl(self, items: list) -> None:
        return None

    def import_stmt(self, items: list) -> None:
        # "import <namespace>" is a runtime PDP hint; symbols are loaded via --include at CLI level.
        return None

    def rulecombinator_decl(self, items: list) -> None:
        return None

    def policycombinator_decl(self, items: list) -> None:
        return None

    def type_sys_decl(self, items: list) -> None:
        return None

    def category_sys_decl(self, items: list) -> None:
        return None

    def function_decl(self, items: list) -> None:
        return None

    def infix_decl(self, items: list) -> None:
        return None

    # -----------------------------------------------------------------------
    # PolicySet
    # -----------------------------------------------------------------------

    @v_args(meta=True)
    def policyset_decl(self, meta, items: list) -> dict:
        # items: [Token('IDENTIFIER', name), optional_algo_str, optional_body_list]
        name = str(items[0])
        policy_id = ".".join(self._decl_ns_parts(meta) + [name])
        combining = None
        body_items: list = []
        for item in items[1:]:
            if isinstance(item, str):
                combining = item
            elif isinstance(item, list):
                body_items = item
        # applying_kw may appear inside body (Axiomatics style)
        if combining is None:
            for item in body_items:
                if isinstance(item, str):
                    combining = item
                    break
        body_items = [i for i in body_items if not isinstance(i, str)]
        notices, target, combiner_inputs, var_defs = self._split_body(body_items)
        p: dict = {"PolicyId": policy_id, "Version": "1.0"}
        if combining:
            p["CombiningAlgId"] = combining
        if target is not None:
            p["Target"] = target
        if var_defs:
            p["VariableDefinition"] = var_defs
        if combiner_inputs:
            p["CombinerInput"] = combiner_inputs
        if notices:
            p["NoticeExpression"] = notices
        # ACAL 1.0 absorbed PolicySet into Policy — there is no PolicySet object, and
        # CombinerInput admits only Rule / Policy / PolicyReference. Emitting a
        # {"PolicySet": ...} member made every nested `policyset` structurally invalid.
        return {"Policy": p}

    def policyset_body(self, items: list) -> list:
        return [i for i in items if i is not None]

    def ref_stmt(self, items: list) -> dict:
        name = str(items[0])
        return {"PolicyReference": {"Id": name}}

    # -----------------------------------------------------------------------
    # Policy
    # -----------------------------------------------------------------------

    @v_args(meta=True)
    def policy_decl(self, meta, items: list) -> dict:
        # items: [Token('IDENTIFIER', name), optional_algo_str, optional_body_list]
        name = str(items[0])
        policy_id = ".".join(self._decl_ns_parts(meta) + [name])
        combining = None
        body_items: list = []
        self._current_vars = {}
        for item in items[1:]:
            if isinstance(item, str):
                combining = item
            elif isinstance(item, list):
                body_items = item
        # applying_kw may appear inside body (Axiomatics style)
        if combining is None:
            for item in body_items:
                if isinstance(item, str):
                    combining = item
                    break
        body_items = [i for i in body_items if not isinstance(i, str)]
        notices, target, combiner_inputs, var_defs = self._split_body(body_items)
        p: dict = {"PolicyId": policy_id, "Version": "1.0"}
        if combining:
            p["CombiningAlgId"] = combining
        if target is not None:
            p["Target"] = target
        if var_defs:
            p["VariableDefinition"] = var_defs
        if combiner_inputs:
            p["CombinerInput"] = combiner_inputs
        if notices:
            p["NoticeExpression"] = notices
        return {"Policy": p}

    def policy_body(self, items: list) -> list:
        return [i for i in items if i is not None]

    def applying_kw(self, items: list) -> str:
        # items: [Token('DOTTED_ID'|'IDENTIFIER', algo_name)]
        # (_APPLY_KW is discarded)
        algo_name = str(items[0])
        if algo_name in ACAL_COMBINING_ALGO_MAP:
            return ACAL_COMBINING_ALGO_MAP[algo_name]
        self._warn_or_raise(
            f"Unknown combining algorithm {algo_name!r}. Passing through as-is. "
            "Standard: denyOverrides, permitOverrides, firstApplicable, "
            "denyUnlessPermit, permitUnlessDeny, onlyOneApplicable."
        )
        return algo_name

    def _split_body(self, body_items: list) -> tuple[list, Any, list, list]:
        notices: list = []
        target = None
        combiner_inputs: list = []
        var_defs: list = []
        for item in body_items:
            if not isinstance(item, dict):
                continue
            if "NoticeExpression" in item:
                notices.extend(item["NoticeExpression"])
            elif "Target" in item:
                target = item["Target"]
            elif "Rule" in item or "Policy" in item or "PolicyReference" in item:
                combiner_inputs.append(item)
            elif "VariableDefinition" in item:
                var_defs.append(item["VariableDefinition"])
        return notices, target, combiner_inputs, var_defs

    # -----------------------------------------------------------------------
    # Rule
    # -----------------------------------------------------------------------

    @v_args(meta=True)
    def rule_decl(self, meta, items: list) -> dict:
        # items: [Token('IDENTIFIER', name)?, rule_body_list]
        # (_RULE_KW discarded; IDENTIFIER is optional)
        name: str | None = None
        body_items: list = []
        for item in items:
            if isinstance(item, Token):
                name = str(item)
            elif isinstance(item, list):
                body_items = item
        effect = None
        target = None
        condition = None
        notices: list = []
        for item in body_items:
            if isinstance(item, dict):
                if "Effect" in item:
                    effect = item["Effect"]
                elif "Target" in item:
                    target = item["Target"]
                elif "Condition" in item:
                    condition = item["Condition"]
                elif "NoticeExpression" in item:
                    notices.extend(item["NoticeExpression"])
        # ACAL 1.0 RuleType has no Target — unlike PolicyType, a rule's applicability is
        # carried entirely by Condition (RuleType sets additionalProperties: false, so a
        # Rule.Target made the whole document structurally invalid). ALFA's rule-level
        # `target clause` and `condition` are both conjunctive applicability predicates,
        # so folding them under `and` preserves the source's meaning.
        if target is not None:
            condition = target if condition is None else {"Apply": {
                "FunctionId": _INFIX_FUNCTION_MAP["&&"],
                "Argument": [target, condition],
            }}

        rule: dict = {"Effect": effect or "Permit"}
        if name:
            rule["Id"] = ".".join(self._decl_ns_parts(meta) + [name])
        if condition is not None:
            rule["Condition"] = condition
        if notices:
            rule["NoticeExpression"] = notices
        return {"Rule": rule}

    def rule_body(self, items: list) -> list:
        return [i for i in items if i is not None]

    def effect_clause(self, items: list) -> dict:
        val = str(items[0])  # PERMIT_KW or DENY_KW
        return {"Effect": "Permit" if val == "permit" else "Deny"}

    def target_clause(self, items: list) -> dict:
        # items: [expr]  (_TARGET_KW discarded)
        return {"Target": items[0]}

    def condition_clause(self, items: list) -> dict:
        # items: [expr]  (_CONDITION_KW discarded)
        return {"Condition": items[0]}

    # -----------------------------------------------------------------------
    # On clauses (obligations / advice)
    # -----------------------------------------------------------------------

    def on_clause(self, items: list) -> dict:
        # items: [PERMIT_KW|DENY_KW, on_body_list]  (_ON_KW discarded)
        applies_to = "Permit" if str(items[0]) == "permit" else "Deny"
        body = items[1] if len(items) > 1 and isinstance(items[1], list) else []
        notices = []
        for notice_dict in body:
            if isinstance(notice_dict, dict):
                notice_dict["AppliesTo"] = applies_to
                notices.append(notice_dict)
        return {"NoticeExpression": notices}

    def on_body(self, items: list) -> list:
        return [i for i in items if i is not None]

    def obligation_ref(self, items: list) -> dict:
        return self._notice_ref(items, is_obligation=True)

    def advice_ref(self, items: list) -> dict:
        return self._notice_ref(items, is_obligation=False)

    def _notice_ref(self, items: list, is_obligation: bool) -> dict:
        dotted = str(items[0])
        local_name = dotted.split(".")[-1]
        lookup = self._symbols.obligations if is_obligation else self._symbols.advice
        if local_name in lookup:
            urn = lookup[local_name]
        elif ":" in dotted:
            urn = dotted
        else:
            self._warn_or_raise(
                f"{'Obligation' if is_obligation else 'Advice'} {local_name!r} "
                "not declared in the namespace. Using name as-is."
            )
            urn = dotted
        notice: dict = {"Id": urn, "IsObligation": is_obligation}
        aae = items[1] if len(items) > 1 and isinstance(items[1], list) else []
        if aae:
            notice["AttributeAssignmentExpression"] = aae
        return notice

    def aae_block(self, items: list) -> list:
        return [i for i in items if i is not None]

    def aae_list(self, items: list) -> list:
        return [i for i in items if i is not None]

    def aae_entry(self, items: list) -> dict:
        attr_id = str(items[0])
        expr = items[1] if len(items) > 1 else None
        entry: dict = {"AttributeId": attr_id}
        if expr is not None:
            entry["Expression"] = expr
        return entry

    # -----------------------------------------------------------------------
    # Variables
    # -----------------------------------------------------------------------

    def var_decl(self, items: list) -> dict:
        # items: [Token('IDENTIFIER', name), expr]  (_VAR_KW discarded)
        name = str(items[0])
        expr = items[1] if len(items) > 1 else None
        var_id = ".".join(self._ns_parts + [name])
        self._current_vars[name] = var_id
        vd: dict = {"VariableId": var_id}
        if expr is not None:
            vd["Expression"] = expr
        return {"VariableDefinition": vd}

    def var_ref(self, items: list) -> dict:
        # items: [Token('IDENTIFIER', name)]  (VAR_REF_KW kept but value not needed)
        name = str(items[-1])  # last item is IDENTIFIER; VAR_REF_KW may or may not appear
        var_id = self._current_vars.get(name, ".".join(self._ns_parts + [name]))
        return {"VariableReference": {"VariableId": var_id}}

    # -----------------------------------------------------------------------
    # Expression tree
    # -----------------------------------------------------------------------

    def condition_expr(self, items: list) -> Any:
        return items[0]

    def or_expr(self, items: list) -> Any:
        exprs = [i for i in items if not isinstance(i, Token)]
        if len(exprs) == 1:
            return exprs[0]
        return {"Apply": {"FunctionId": _INFIX_FUNCTION_MAP["||"], "Argument": exprs}}

    def and_expr(self, items: list) -> Any:
        exprs = [i for i in items if not isinstance(i, Token)]
        if len(exprs) == 1:
            return exprs[0]
        return {"Apply": {"FunctionId": _INFIX_FUNCTION_MAP["&&"], "Argument": exprs}}

    def not_expr(self, items: list) -> Any:
        # Called for both "NOT_OP not_expr" and "| cmp_expr" alternatives.
        # Distinguish by whether NOT_OP token is present.
        has_not = any(isinstance(i, Token) and i.type == "NOT_OP" for i in items)
        operand = next(i for i in items if not isinstance(i, Token))
        if has_not:
            return {"Apply": {"FunctionId": _INFIX_FUNCTION_MAP["!"], "Argument": [operand]}}
        return operand

    def cmp_expr(self, items: list) -> Any:
        non_tokens = [i for i in items if not isinstance(i, Token)]
        tokens = [i for i in items if isinstance(i, Token)]

        def _strip(node: Any) -> Any:
            if isinstance(node, dict) and "_bag" in node:
                return {k: v for k, v in node.items() if k != "_bag"}
            return node

        if len(non_tokens) == 1:
            return _strip(non_tokens[0])

        lhs = _strip(non_tokens[0])
        rhs = _strip(non_tokens[1])
        op = str(tokens[0])

        if op in _INFIX_FUNCTION_MAP:  # && || ! — not comparisons, no datatype involved
            return {"Apply": {"FunctionId": _INFIX_FUNCTION_MAP[op], "Argument": [lhs, rhs]}}
        return self._typed_comparison(op, lhs, rhs)

    def _typed_comparison(self, op: str, lhs: Any, rhs: Any) -> dict:
        """Build a comparison Apply for the operands' datatype, bridging bag operands.

        Two rules combine here. ACAL has no generic equality and no `*-not-equal`, so the
        datatype decides the function and `!=` is `not(<type>-equal(...))`. And the typed
        comparison functions take *single* values while an attribute designator yields a
        *bag*, so a comparison involving a designator must be lifted rather than applied
        directly — passing a bag straight in is a type error the schema does not catch.
        """
        if op not in _ORDERING_SUFFIX and op not in ("==", "!="):
            raise ALFAUnsupportedFeatureError(f"Unknown comparison operator: {op!r}")

        dtype = self._comparison_datatype(op, lhs, rhs)
        negate = op == "!="

        if op in ("==", "!="):
            if dtype not in _EQUALITY_TYPES:
                self._warn_or_raise(
                    f"No ACAL equality function for datatype {dtype!r}; "
                    f"using {_DEFAULT_COMPARISON_TYPE}-equal."
                )
                dtype = _DEFAULT_COMPARISON_TYPE
            fn_id = f"{_ACAL_FN}{dtype}-equal"
        else:
            if dtype not in _ORDERED_TYPES:
                raise ALFAUnsupportedFeatureError(
                    f"ACAL defines no {op!r} comparison for datatype {dtype!r}. "
                    f"Ordering is defined for {sorted(_ORDERED_TYPES)}. "
                    "Declare the attribute's type, or compare a datatype that is ordered."
                )
            fn_id = f"{_ACAL_FN}{dtype}-{_ORDERING_SUFFIX[op]}"

        result = self._bridge_bags(fn_id, dtype, negate or op == "==", lhs, rhs)
        if negate:
            # ALFA's `!=` on a bag means no member matches, which is the negation of the
            # existential form above — the same shape the declared-bag path always used.
            return {"Apply": {"FunctionId": _INFIX_FUNCTION_MAP["!"], "Argument": [result]}}
        return result

    def _bridge_bags(
        self, fn_id: str, dtype: str, is_equality: bool, lhs: Any, rhs: Any
    ) -> dict:
        """Apply `fn_id` to operands that may be bags.

        Three shapes, in order of how specifically they fit:

        * neither operand is a bag — apply the function directly;
        * equality with exactly one bag — ``<type>-is-in(single, bag)``, the two-argument
          idiom for membership, and what the reader already emitted for attributes
          declared ``type = bag``;
        * anything else (two bags, or an ordering against a bag) — ``any-of-any``, which
          takes the function plus operands that may each be a single value or a bag and
          applies it across their cross product. Operand order is preserved, so an
          ordering comparison keeps its orientation.
        """
        lhs_bag = _is_bag_valued(lhs)
        rhs_bag = _is_bag_valued(rhs)

        if not lhs_bag and not rhs_bag:
            return {"Apply": {"FunctionId": fn_id, "Argument": [lhs, rhs]}}

        if is_equality and lhs_bag != rhs_bag:
            is_in = _TYPE_IS_IN_MAP.get(dtype)
            if is_in:
                single, bag = (rhs, lhs) if lhs_bag else (lhs, rhs)
                return {"Apply": {"FunctionId": is_in, "Argument": [single, bag]}}

        return {"Apply": {
            "FunctionId": f"{_ACAL_FN}any-of-any",
            "Argument": [{"Function": {"Id": fn_id}}, lhs, rhs],
        }}

    def _comparison_datatype(self, op: str, lhs: Any, rhs: Any) -> str:
        """The datatype an infix comparison operates on.

        A declared type on either side wins over a bare string literal. When both sides
        declare and disagree, the source has a type mismatch that no single function can
        honour, so it is reported rather than silently resolved to one side.
        """
        left, left_declared = _operand_datatype(lhs)
        right, right_declared = _operand_datatype(rhs)

        if left_declared and right_declared and left and right and left != right:
            self._warn_or_raise(
                f"Comparison {op!r} between {left!r} and {right!r} mixes datatypes; "
                f"using {left!r}. Convert one side explicitly in the source."
            )
            return left

        for dtype, declared in ((left, left_declared), (right, right_declared)):
            if declared and dtype:
                return dtype
        # Only weak evidence (a string literal), or none at all.
        for dtype, _ in ((left, left_declared), (right, right_declared)):
            if dtype:
                return dtype
        if op in _ORDERING_SUFFIX:
            self._warn_or_raise(
                f"Cannot determine the datatype of an {op!r} comparison — neither operand "
                "declares one. Declare the attribute's type with 'type =' so the correct "
                "ordering function can be selected."
            )
        return _DEFAULT_COMPARISON_TYPE

    def primary_expr(self, items: list) -> Any:
        return items[0]

    def paren_expr(self, items: list) -> Any:
        return items[0]

    def func_call(self, items: list) -> dict:
        # items: [Token('DOTTED_ID', name), optional_arg_list]
        name = str(items[0])
        args = items[1] if len(items) > 1 and isinstance(items[1], list) else []
        fn_id = _NAMED_FUNCTION_MAP.get(name)
        if fn_id is None:
            fn_id = f"urn:custom:function:{name}"
            self._warn_or_raise(
                f"Unknown ALFA function {name!r}. Mapping to {fn_id!r}. "
                "Add to _NAMED_FUNCTION_MAP if an ACAL equivalent exists."
            )
        apply: dict = {"FunctionId": fn_id}
        if args:
            apply["Argument"] = [self._reduce_bag_argument(a, fn_id) for a in args]
        return {"Apply": apply}

    def _reduce_bag_argument(self, argument: Any, fn_id: str) -> Any:
        """Reduce a bag passed to an explicitly named single-value function.

        Bridged by reduction (`<type>-one-and-only`) rather than by the existential lift
        used for infix comparisons, and the difference is deliberate. An infix `==` is ALFA
        sugar whose bag behaviour the reference compiler defines existentially. A written-out
        `dateGreaterThan(hireDate, …)` instead names a function whose signature takes single
        values, so the faithful reading is that the author means the single value. Reduction
        also works for functions that do not return a boolean — `any-of-any` cannot lift
        those, since it requires a Boolean function.
        """
        if not fn_id.startswith(_ACAL_FN):
            return argument  # custom function: signature unknown, nothing to conclude
        name = fn_id[len(_ACAL_FN):]
        if not (name in _SINGLE_VALUE_FUNCTION_NAMES
                or name.endswith(_SINGLE_VALUE_FUNCTION_SUFFIXES)):
            return argument
        if not _is_bag_valued(argument):
            return argument
        dtype, _ = _operand_datatype(argument)
        if dtype not in _EQUALITY_TYPES:
            return argument  # no <type>-one-and-only to reduce with
        return {"Apply": {
            "FunctionId": f"{_ACAL_FN}{dtype}-one-and-only",
            "Argument": [argument],
        }}

    def arg_list(self, items: list) -> list:
        return list(items)

    def expr(self, items: list) -> Any:
        return items[0]

    def attr_path(self, items: list) -> dict:
        # items: [Token('DOTTED_ID', 'Attributes.subject.role')]
        dotted = str(items[0])
        return self._resolve_attr_path(dotted)

    def _resolve_attr_path(self, dotted: str) -> dict:
        # Canonical: Attributes.<category>.<id>
        for prefix, cat_urn in _CANONICAL_PREFIXES.items():
            if dotted.startswith(prefix + "."):
                attr_id = dotted[len(prefix) + 1:]
                return {"AttributeDesignator": {
                    "Category": cat_urn, "AttributeId": attr_id,
                    "MustBePresent": self._must_be_present(),
                }}

        decl, rest = self._lookup_attribute(dotted)
        if decl is not None:
            attr_id = decl.id + rest if rest else decl.id
            desig: dict = {"Category": decl.category, "AttributeId": attr_id}
            if decl.type:
                desig["DataType"] = decl.type
            desig["MustBePresent"] = self._must_be_present()
            result: dict = {"AttributeDesignator": desig}
            if decl.is_bag:
                # Private marker consumed by cmp_expr for bag overloading.
                # Stripped before the dict is returned from any expression context.
                result["_bag"] = True
            return result

        # Unresolvable. This raises unconditionally rather than warning, per ADR-0002
        # (docs/design/0002-no-silent-drops.md): the reader has no mapping for this
        # reference, and the only alternative is a designator with an empty Category —
        # which the ACAL schema rejects (Category is required, minLength 1) and no PDP
        # could evaluate. There is no useful lenient output here, so --no-strict does not
        # soften it; a wrong or unusable document is worse than a clear failure.
        raise ALFAUnsupportedFeatureError(
            f"Attribute path {dotted!r} could not be resolved to a declared attribute. "
            "Declare it in an 'attribute { }' block, pass the registry that declares it "
            "with --include, or write the canonical 'Attributes.<category>.<id>' form."
        )

    def _lookup_attribute(self, dotted: str) -> tuple[_AttributeDecl | None, str]:
        """Find the declaration a reference names, plus any trailing path to append.

        Tried in order of specificity:

        1. the whole path as a declared name (a qualified name, or a single-segment local);
        2. the whole path as a unique *suffix* of a declared qualified name — ALFA resolves
           a reference relative to its enclosing namespace, so ``user.role`` written inside
           ``namespace axiomatics.demo`` names ``axiomatics.demo.user.role``. This is the
           partially-qualified form real ALFA policies are written in;
        3. the leading segment as a declared local name, with the remainder appended to its
           id — the compound-path fallback (``someAttr.sub.field``).

        Suffix matching is tried before the leading-segment fallback because it consumes the
        whole reference: matching only the first segment and blind-appending the rest would
        resolve ``user.role`` against an unrelated attribute named ``user`` and silently
        fabricate the id ``<user's id>.role``.
        """
        attrs = self._symbols.attributes

        decl = attrs.get(dotted)
        if decl is not None:
            return decl, ""

        candidates = sorted(key for key in attrs if key.endswith("." + dotted))
        distinct_ids = {attrs[key].id for key in candidates}
        if len(distinct_ids) == 1:
            return attrs[candidates[0]], ""
        if len(distinct_ids) > 1:
            raise ALFAUnsupportedFeatureError(
                f"Attribute reference {dotted!r} is ambiguous: it matches "
                f"{sorted(distinct_ids)}. Qualify the reference to disambiguate."
            )

        first = dotted.split(".")[0]
        decl = attrs.get(first)
        if decl is not None:
            return decl, dotted[len(first):]
        return None, ""

    # -----------------------------------------------------------------------
    # Literals
    # -----------------------------------------------------------------------

    def string_literal(self, items: list) -> dict:
        return {"Value": str(items[0]).strip("\"'")}

    def integer_literal(self, items: list) -> dict:
        return {"Value": int(str(items[0]))}

    def float_literal(self, items: list) -> dict:
        return {"Value": float(str(items[0]))}

    def bool_literal(self, items: list) -> dict:
        return {"Value": str(items[0]) == "true"}


# ---------------------------------------------------------------------------
# Post-processing: synthesize anonymous Rule IDs
# ---------------------------------------------------------------------------


def _bundle_policies(doc: dict) -> list[dict]:
    """Top-level policies, whether the document is a Bundle or a bare Policy."""
    if "Bundle" in doc:
        return doc["Bundle"].get("Policy", [])
    if "Policy" in doc:
        return [doc["Policy"]]
    return []


def _walk_policy_refs(node: Any, out: list[dict]) -> None:
    """Collect every PolicyReference object anywhere in the document."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "PolicyReference" and isinstance(value, dict):
                out.append(value)
            else:
                _walk_policy_refs(value, out)
    elif isinstance(node, list):
        for item in node:
            _walk_policy_refs(item, out)


def _all_policy_ids(node: Any, out: set[str]) -> None:
    if isinstance(node, dict):
        pid = node.get("PolicyId")
        if isinstance(pid, str):
            out.add(pid)
        for value in node.values():
            _all_policy_ids(value, out)
    elif isinstance(node, list):
        for item in node:
            _all_policy_ids(item, out)


def _resolve_policy_references(doc: dict, strict: bool = False) -> dict:
    """Rewrite relative cross-references to the PolicyId they actually name.

    ALFA resolves a reference relative to its enclosing namespace: inside
    ``namespace aerospace``, the statement ``globalchecks`` names
    ``aerospace.globalchecks``. The transformer records the reference as written, so a
    relative reference would otherwise point at a PolicyId no policy in the document has
    — a dangling reference the ACAL schema does not reject (an Id is just a URI).

    Resolution is by unique suffix match against the real PolicyIds, which handles the
    relative and already-qualified forms without needing namespace context here. A
    reference that resolves to nothing is left untouched: it may legitimately target a
    policy in another file, which is the validator's ``--include`` case, not an error.
    """
    known: set[str] = set()
    _all_policy_ids(doc, known)
    refs: list[dict] = []
    _walk_policy_refs(doc, refs)

    for ref in refs:
        name = ref.get("Id")
        if not isinstance(name, str) or name in known:
            continue
        candidates = sorted(pid for pid in known if pid.endswith("." + name))
        if len(candidates) == 1:
            ref["Id"] = candidates[0]
        elif len(candidates) > 1:
            msg = (
                f"Policy reference {name!r} is ambiguous — it matches {candidates}. "
                "Qualify the reference in the source to disambiguate."
            )
            if strict:
                raise ALFAUnsupportedFeatureError(msg)
            warnings.warn(msg, UserWarning, stacklevel=3)
    return doc


def _designate_bundle_entry_point(doc: dict, strict: bool = False) -> dict:
    """Name the policy that decides, per ADR-0004 (docs/design/0004-unambiguous-output.md).

    ``Bundle.Policy[]`` is a definition pool; ``Bundle.PolicyReference`` names the entry
    point. Without it, a multi-policy Bundle is schema-valid but does not say which policy
    is the decision. ALFA has no explicit "main policy" declaration, so the entry point is
    inferred structurally: the one top-level policy that nothing else references.

    No Version is emitted on the reference. ALFA has no policy-version syntax, and Version
    on a reference is an optional *match* pattern — omitting it matches any version, which
    is the faithful reading of a language that does not express versions at all.
    """
    bundle = doc.get("Bundle")
    if not isinstance(bundle, dict) or "PolicyReference" in bundle:
        return doc
    policies = bundle.get("Policy", [])
    if len(policies) < 2:
        return doc  # a single policy is the decision by construction

    top_ids = [p["PolicyId"] for p in policies if isinstance(p.get("PolicyId"), str)]
    refs: list[dict] = []
    _walk_policy_refs(bundle, refs)
    referenced = {r["Id"] for r in refs if isinstance(r.get("Id"), str)}
    roots = [pid for pid in top_ids if pid not in referenced]

    if len(roots) == 1:
        bundle["PolicyReference"] = {"Id": roots[0]}
        return doc

    detail = (
        f"none of them are unreferenced (a reference cycle): {top_ids}"
        if not roots else
        f"these are all unreferenced: {roots}"
    )
    msg = (
        f"Cannot determine which policy decides — {detail}. The Bundle is a definition pool "
        "with no entry point, so which policy produces the decision is undefined. Give the "
        "source a single top-level policyset that references the others."
    )
    if strict:
        raise ALFAUnsupportedFeatureError(msg)
    warnings.warn(msg, UserWarning, stacklevel=3)
    return doc


def _normalize_datatypes(node: Any) -> None:
    """Rewrite ALFA short-name DataTypes as ACAL data-type URNs, in place.

    Runs as a post-pass rather than at emission because the reader's own type logic keys
    off the ALFA short names — typed comparison selection (`_operand_datatype`) and bag
    function selection (`_TYPE_IS_IN_MAP`) both look up `boolean`, `double` and friends.
    Normalizing at emission would force every one of those consumers to parse URNs back
    into short names.

    A DataType resolving to the ACAL default is dropped rather than restated, matching the
    XACML reader's ``optional_datatype()`` and the convention in ``test_attribute_omits_datatype``:
    the schema already defaults DataType to string, so spelling it out adds bytes, not meaning.

    Values that already contain ``:`` are left alone, so this is idempotent, and an
    unrecognized short name (``xpath``) passes through — its lack of an ACAL equivalent was
    already reported when the attribute was declared.
    """
    if isinstance(node, dict):
        dtype = node.get("DataType")
        if isinstance(dtype, str) and ":" not in dtype and dtype in _ALFA_DATATYPE_NAMES:
            if dtype == "string":
                del node["DataType"]
            else:
                node["DataType"] = _ACAL_DATATYPE + dtype
        for value in node.values():
            _normalize_datatypes(value)
    elif isinstance(node, list):
        for item in node:
            _normalize_datatypes(item)


def _synthesize_rule_ids(doc: dict) -> dict:
    if "Policy" in doc:
        _fill_rule_ids(doc["Policy"])
    elif "Bundle" in doc:
        for policy in doc["Bundle"].get("Policy", []):
            _fill_rule_ids(policy)
    return doc


def _fill_rule_ids(policy: dict) -> None:
    counter = 0
    policy_id = policy.get("PolicyId", "")
    for entry in policy.get("CombinerInput", []):
        if "Rule" in entry:
            rule = entry["Rule"]
            if "Id" not in rule:
                rule["Id"] = f"{policy_id}:rule_{counter}"
                counter += 1
        elif "Policy" in entry:
            _fill_rule_ids(entry["Policy"])


# ---------------------------------------------------------------------------
# Content-sniff helper
# ---------------------------------------------------------------------------

_UTF8_BOM = b"\xef\xbb\xbf"
_C_LINE_COMMENT = re.compile(r"//[^\n]*")
_C_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)


def _looks_like_alfa(chunk: bytes) -> bool:
    """Return True if chunk looks like an ALFA document."""
    text = chunk.lstrip(_UTF8_BOM).decode("utf-8", errors="replace")
    text = _C_LINE_COMMENT.sub("", text)
    text = _C_BLOCK_COMMENT.sub("", text)
    text = text.lstrip()
    if not text:
        return False
    m = re.match(r"([a-zA-Z_][a-zA-Z0-9_]*)", text)
    if m is None:
        return False
    word = m.group(1)
    if word not in ("namespace", "import"):
        return False
    rest = text[len(word):].lstrip()
    # "namespace:" is a YAML key — not ALFA
    return not rest.startswith(":")


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def _syntax_error(label: str, exc: UnexpectedInput) -> ALFASyntaxError:
    """Build an ALFASyntaxError with location info when the parser provides it."""
    line = getattr(exc, "line", None)
    col = getattr(exc, "column", None)
    if line is not None and col is not None:
        loc = f" at line {line}, col {col}"
    else:
        loc = ""
    return ALFASyntaxError(f"Syntax error in {label}{loc}: {exc}")


def _dump_symbol_table(st: _SymbolTable) -> None:
    import json as _json
    data = {
        "namespace": ".".join(st.namespace_parts),
        "attributes": {
            k: {"id": v.id, "category": v.category, "type": v.type, "is_bag": v.is_bag}
            for k, v in st.attributes.items()
        },
        "obligations": st.obligations,
        "advice": st.advice,
    }
    import sys as _sys
    print("=== ALFA symbol table ===", file=_sys.stderr)
    print(_json.dumps(data, indent=2), file=_sys.stderr)
    print("=========================", file=_sys.stderr)


def load(
    path: str,
    strict: bool = False,
    include: Sequence[str] = (),
    debug: bool = False,
    fail_closed: bool = False,
) -> dict[str, Any]:
    """Parse an ALFA policy file and return a neutral ACAL dict.

    include: zero or more additional ALFA files (attribute registries, standard
    namespaces) whose symbol tables are merged before the main file is converted.
    These files contribute only to symbol resolution; no output is generated from
    them.  This mirrors how real ALFA compilers handle separate attribute-registry
    files and ``import`` statements.

    debug: if True, dump the combined symbol table to stderr before transforming.
    Useful for troubleshooting shorthand resolution or namespace issues.
    """
    combined = _SymbolTable()

    for inc_path in include:
        with open(inc_path, encoding="utf-8") as fh:
            inc_source = fh.read()
        try:
            inc_tree = _PARSER.parse(inc_source)
        except UnexpectedInput as exc:
            raise _syntax_error(f"include file {inc_path!r}", exc) from exc
        _merge_into(combined, _collect_symbols(inc_tree, strict=strict))

    with open(path, encoding="utf-8") as fh:
        source = fh.read()
    try:
        tree = _PARSER.parse(source)
    except UnexpectedInput as exc:
        raise _syntax_error(f"ALFA file {path!r}", exc) from exc

    _merge_into(combined, _collect_symbols(tree, strict=strict))

    if debug:
        _dump_symbol_table(combined)

    try:
        doc = AlfaTransformer(combined, strict=strict, fail_closed=fail_closed).transform(tree)
    except VisitError as exc:
        cause = exc.__context__
        if isinstance(cause, (ALFASyntaxError, ALFAUnsupportedFeatureError)):
            raise cause from None
        raise
    doc = _synthesize_rule_ids(doc)
    # Order matters: references must be resolved to real PolicyIds before the entry point
    # can be inferred, since inference asks which top-level policy nothing references.
    doc = _resolve_policy_references(doc, strict=strict)
    doc = _designate_bundle_entry_point(doc, strict=strict)
    # Must stay outside the transformer: the type logic in cmp_expr matches ALFA short
    # names, so normalizing at the designator instead would make every lookup miss and
    # silently fall back to string-equal. Position among the post-passes does not matter.
    _normalize_datatypes(doc)
    return doc
