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

_INFIX_FUNCTION_MAP: dict[str, str] = {
    "==":  "urn:oasis:names:tc:acal:1.0:function:string-equal",
    "!=":  "urn:oasis:names:tc:acal:1.0:function:string-not-equal",
    ">":   "urn:oasis:names:tc:acal:1.0:function:integer-greater-than",
    "<":   "urn:oasis:names:tc:acal:1.0:function:integer-less-than",
    ">=":  "urn:oasis:names:tc:acal:1.0:function:integer-greater-than-or-equal",
    "<=":  "urn:oasis:names:tc:acal:1.0:function:integer-less-than-or-equal",
    "&&":  "urn:oasis:names:tc:acal:1.0:function:and",
    "||":  "urn:oasis:names:tc:acal:1.0:function:or",
    "!":   "urn:oasis:names:tc:acal:1.0:function:not",
}

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
        elif child.data == "attribute_decl":
            _process_attribute(child, st, parts, strict)
        elif child.data == "obligation_decl":
            _process_notice_decl(child, st, "obligation", parts)
        elif child.data == "advice_decl":
            _process_notice_decl(child, st, "advice", parts)

    # Track deepest namespace as PolicyId prefix
    if len(parts) >= len(st.namespace_parts):
        st.namespace_parts = parts


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

    st.attributes[local_name] = _AttributeDecl(
        id=attr_id, category=category_urn, type=attr_type, is_bag=is_bag
    )


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

    def __init__(self, symbols: _SymbolTable, strict: bool = False) -> None:
        super().__init__()
        self._symbols = symbols
        self._strict = strict
        self._current_vars: dict[str, str] = {}
        self._ns_parts: list[str] = list(symbols.namespace_parts)

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

    def policyset_decl(self, items: list) -> dict:
        # items: [Token('IDENTIFIER', name), optional_algo_str, optional_body_list]
        name = str(items[0])
        policy_id = ".".join(self._ns_parts + [name])
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
        p: dict = {"PolicyId": policy_id}
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
        return {"PolicySet": p}

    def policyset_body(self, items: list) -> list:
        return [i for i in items if i is not None]

    def ref_stmt(self, items: list) -> dict:
        name = str(items[0])
        return {"PolicyRef": name}

    # -----------------------------------------------------------------------
    # Policy
    # -----------------------------------------------------------------------

    def policy_decl(self, items: list) -> dict:
        # items: [Token('IDENTIFIER', name), optional_algo_str, optional_body_list]
        name = str(items[0])
        policy_id = ".".join(self._ns_parts + [name])
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
        p: dict = {"PolicyId": policy_id}
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
            elif "Rule" in item or "Policy" in item or "PolicySet" in item or "PolicyRef" in item:
                combiner_inputs.append(item)
            elif "VariableDefinition" in item:
                var_defs.append(item["VariableDefinition"])
        return notices, target, combiner_inputs, var_defs

    # -----------------------------------------------------------------------
    # Rule
    # -----------------------------------------------------------------------

    def rule_decl(self, items: list) -> dict:
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
        rule: dict = {"Effect": effect or "Permit"}
        if name:
            rule["Id"] = ".".join(self._ns_parts + [name])
        if target is not None:
            rule["Target"] = target
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

        lhs, rhs = non_tokens[0], non_tokens[1]
        op = str(tokens[0])

        lhs_is_bag = isinstance(lhs, dict) and lhs.get("_bag")
        rhs_is_bag = isinstance(rhs, dict) and rhs.get("_bag")
        lhs = _strip(lhs)
        rhs = _strip(rhs)

        # Bag overloading: attr_bag == scalar → <type>-is-in(scalar, bag)
        if (lhs_is_bag or rhs_is_bag) and op in ("==", "!="):
            bag = lhs if lhs_is_bag else rhs
            scalar = rhs if lhs_is_bag else lhs
            dtype = bag.get("AttributeDesignator", {}).get("DataType", "string")
            is_in_fn = _TYPE_IS_IN_MAP.get(dtype)
            if is_in_fn:
                base: dict = {"Apply": {"FunctionId": is_in_fn, "Argument": [scalar, bag]}}
                if op == "!=":
                    return {"Apply": {
                        "FunctionId": _INFIX_FUNCTION_MAP["!"],
                        "Argument": [base],
                    }}
                return base
            self._warn_or_raise(
                f"Bag attribute has unsupported type {dtype!r} for {op!r} comparison. "
                "Using string-equal as fallback; result may be semantically incorrect."
            )

        fn_id = _INFIX_FUNCTION_MAP.get(op)
        if fn_id is None:
            raise ALFAUnsupportedFeatureError(f"Unknown comparison operator: {op!r}")
        return {"Apply": {"FunctionId": fn_id, "Argument": [lhs, rhs]}}

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
            apply["Argument"] = args
        return {"Apply": apply}

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
                return {"AttributeDesignator": {"Category": cat_urn, "AttributeId": attr_id}}

        # Shorthand: declared attribute alias
        first = dotted.split(".")[0]
        if first in self._symbols.attributes:
            decl = self._symbols.attributes[first]
            rest = dotted[len(first):]
            attr_id = decl.id + rest if rest else decl.id
            desig: dict = {"Category": decl.category, "AttributeId": attr_id}
            if decl.type:
                desig["DataType"] = decl.type
            result: dict = {"AttributeDesignator": desig}
            if decl.is_bag:
                # Private marker consumed by cmp_expr for bag overloading.
                # Stripped before the dict is returned from any expression context.
                result["_bag"] = True
            return result

        # Unresolvable
        self._warn_or_raise(
            f"Attribute path {dotted!r} could not be resolved. "
            "Declare via 'attribute { }' block or use canonical 'Attributes.<category>.<id>' form."
        )
        return {"AttributeDesignator": {"Category": "", "AttributeId": dotted}}

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
        doc = AlfaTransformer(combined, strict=strict).transform(tree)
    except VisitError as exc:
        cause = exc.__context__
        if isinstance(cause, (ALFASyntaxError, ALFAUnsupportedFeatureError)):
            raise cause from None
        raise
    return _synthesize_rule_ids(doc)
