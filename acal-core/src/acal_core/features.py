"""Which ACAL features a document actually uses, and which a target dialect cannot hold.

This is the export precondition gate in embryo. `acal-explain` is its first consumer — it
reports what a policy could never say in its own source language — and the eventual
`acal-export` tool is the second: given a target dialect, refuse to emit a document whose
semantics that dialect cannot carry.

Keeping it here rather than in acal-explain is deliberate. The question "what can dialect X
say about ACAL?" is answered once, in the capability matrices, and every tool reads the same
answer.
"""
from __future__ import annotations

from .languages import capabilities, get_dialect


def used_features(doc: dict) -> set[str]:
    """ACAL feature names appearing anywhere in a neutral document.

    Feature names are the keys the capability matrices are written against
    (`SharedVariableDefinition`, `NoticeExpression`, `Bundle`, …), so this is a plain
    key sweep rather than a schema walk.
    """
    found: set[str] = set()

    def walk(node) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                found.add(key)
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(doc)
    return found


def export_gaps(doc: dict, dialect_id: str) -> dict[str, str]:
    """Features this document uses that the target dialect cannot express.

    Maps feature name → why not. Empty for a native dialect (the ACAL model itself can
    express all of ACAL), and empty for a document that happens to stay inside the target's
    subset.
    """
    dialect = get_dialect(dialect_id)
    if dialect.native:
        return {}

    matrix = capabilities(dialect_id).get("acal_features", {})
    present = used_features(doc)

    return {
        feature: spec.get("note", "").strip()
        for feature, spec in matrix.items()
        if feature in present and spec.get("exportable") is False
    }
