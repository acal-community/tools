"""Structured reporting of what a conversion lost on the way in.

Readers signal fidelity loss by emitting ``UserWarning``. ``load_with_report``
captures those into a ``ConversionReport`` so callers can present them as data
instead of scraping stderr.

The report is deliberately kept outside the ACAL document. The ACAL schemas set
``additionalProperties`` / ``unevaluatedProperties`` to false in several places,
so stamping provenance into the document would make acal-convert emit output
that fails our own validators.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# A construct was translated, but the translation is not faithful.
LOSSY = "lossy"
# A construct has no ACAL equivalent and was dropped or rejected.
UNSUPPORTED = "unsupported"
# A construct was mapped onto a near-equivalent that behaves differently at the edges.
APPROXIMATED = "approximated"


@dataclass(frozen=True)
class ConversionNote:
    kind: str
    message: str
    construct: str | None = None


@dataclass
class ConversionReport:
    """What the reader had to compromise on to produce the neutral document."""

    source_format: str
    # The dialect actually detected, e.g. "xacml-3.0" vs "xacml-4.0". The format alone is
    # not enough: an .xml file may be a foreign XACML 3.0 policy or the native ACAL XML
    # serialization, and only the dialect says which capability matrix applies.
    source_dialect: str | None = None
    strict: bool = False
    notes: list[ConversionNote] = field(default_factory=list)

    @property
    def lossy(self) -> bool:
        return bool(self.notes)

    def add(self, kind: str, message: str, construct: str | None = None) -> None:
        self.notes.append(ConversionNote(kind=kind, message=message, construct=construct))

    def as_dict(self) -> dict:
        return {
            "source_format": self.source_format,
            "source_dialect": self.source_dialect,
            "strict": self.strict,
            "lossy": self.lossy,
            "notes": [
                {"kind": n.kind, "construct": n.construct, "message": n.message}
                for n in self.notes
            ],
        }
