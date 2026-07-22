"""Detected modifier spans over the user's question (Task 24 §2.4).

Emits bounded, typed spans for the modifiers that are *structurally*
recognizable in text: quoted values, comparisons, numeric bounds, units,
floor/level references, negation, and references to the active model, the
previous result, or the viewer selection.

Two contracts depend on this module:

1. **Coverage.** Every MATERIAL span must be covered by the binding or
   explicitly marked unresolved. "A required modifier may never be silently
   dropped so a broader query can execute" (§2.4).
2. **Scope is not a condition.** §1.3: "A reference that identifies the active
   model is a scope selection. A predicate that restricts results to a spatial
   subset is a condition. Represent these as different typed fields so one
   cannot accidentally become the other."

The second is the general fix for a whole family of recorded failures in which
a phrase naming the model as a whole ("this building", "the entire building")
was turned into a floor predicate, and a perfectly ordinary question was then
refused with "could not read a specific floor from 'this building'". Here such a
phrase produces a `SCOPE_REFERENCE` span that is explicitly **not material**:
it selects what to look at, it narrows nothing, and it can never become a
condition.

Distinguishing a floor *reference* from a floor *subject* is likewise
structural, not phrase-matched: floor language only becomes a
`FLOOR_REFERENCE` when it carries a positional qualifier (an ordinal, or
top/ground/lowest). "How many floors does this building have?" therefore yields
no floor condition at all — the floors are what is being counted.

Field/value matches (the remaining §2.4 span kind) are added by the slate
builder, which alone knows the model's fields; this module stays purely lexical
so it is testable without a database.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from app.query.semantic.spatial import (
    BOTTOM_WORDS,
    FLOOR_WORDS,
    ORDINAL_WORDS,
    TOP_WORDS,
)

__all__ = [
    "ModifierKind",
    "ModifierSpan",
    "detect_spans",
    "material_spans",
]


class ModifierKind(str, Enum):
    """What a detected span DOES to the query — the typed distinction §1.3 requires."""

    #: An exact value the user quoted. Demands exact matching (§4.2).
    QUOTED_VALUE = "quoted_value"
    #: Comparative language ("wider than", "at least", "more than").
    COMPARISON = "comparison"
    #: A bare numeric bound, optionally carrying a unit.
    NUMERIC_BOUND = "numeric_bound"
    #: An explicit unit token.
    UNIT = "unit"
    #: A POSITIONAL floor/level reference ("the second floor", "top floor").
    #: Narrows results, so it is material.
    FLOOR_REFERENCE = "floor_reference"
    #: Negation / exclusion ("not load bearing", "without a fire rating").
    NEGATION = "negation"
    #: Names the active model as a whole. Selects scope; narrows NOTHING.
    SCOPE_REFERENCE = "scope_reference"
    #: Refers to the previous accepted result ("how many of those…").
    PREVIOUS_RESULT_REFERENCE = "previous_result_reference"
    #: Refers to the current viewer selection.
    SELECTION_REFERENCE = "selection_reference"


#: Spans that narrow the result and must therefore be honoured or reported
#: unresolved. A scope reference is deliberately absent: it chooses what to look
#: at, and treating it as a constraint is precisely the recorded defect.
_MATERIAL_KINDS = frozenset(
    {
        ModifierKind.QUOTED_VALUE,
        ModifierKind.COMPARISON,
        ModifierKind.NUMERIC_BOUND,
        ModifierKind.FLOOR_REFERENCE,
        ModifierKind.NEGATION,
        ModifierKind.PREVIOUS_RESULT_REFERENCE,
        ModifierKind.SELECTION_REFERENCE,
    }
)


@dataclass(frozen=True)
class ModifierSpan:
    """One detected modifier, with its exact source span (§2.2 provenance)."""

    kind: ModifierKind
    text: str
    start: int
    end: int

    @property
    def material(self) -> bool:
        """True when the binding must honour this span or mark it unresolved."""
        return self.kind in _MATERIAL_KINDS


# ---------------------------------------------------------------------------
# Patterns. All general English/BIM structure — no sample question appears here.
# ---------------------------------------------------------------------------

_QUOTED_RE = re.compile(r"'([^']{1,120})'|\"([^\"]{1,120})\"|‘([^’]{1,120})’")

_COMPARISON_RE = re.compile(
    r"\b("
    r"wider than|taller than|larger than|smaller than|longer than|shorter than|"
    r"greater than or equal to|less than or equal to|"
    r"greater than|less than|more than|fewer than|"
    r"at least|at most|no more than|no less than|"
    r"bigger than|heavier than|lighter than|"
    r"over|under|above|below|exceeding|between"
    r")\b",
    re.IGNORECASE,
)

_NUMBER_UNIT_RE = re.compile(
    r"(?<![\w.])(-?\d+(?:[.,]\d+)?)\s*"
    r"(mm|cm|m2|m3|m|sqm|millimet(?:re|er)s?|centimet(?:re|er)s?|met(?:re|er)s?|"
    r"deg|degrees?)?(?![\w])",
    re.IGNORECASE,
)

_NEGATION_RE = re.compile(
    r"\b(not|non|no|without|excluding|exclude|except|aren't|isn't|don't|doesn't|neither|nor)\b",
    re.IGNORECASE,
)

_PREVIOUS_RESULT_RE = re.compile(
    r"\b(those|them|these|that result|the previous (?:result|answer|ones?)|"
    r"the (?:above|former)|of (?:those|these|them))\b",
    re.IGNORECASE,
)

_SELECTION_RE = re.compile(
    r"\b(selected|the selection|highlighted|currently selected|what i(?:'ve| have) selected|"
    r"this object|these objects)\b",
    re.IGNORECASE,
)

#: Nouns that denote the modelled artefact as a WHOLE. General vocabulary, not a
#: list of question phrases: any determiner may precede them, and any question
#: naming one of them without a positional qualifier is selecting scope.
_SCOPE_NOUNS = ("building", "model", "project", "structure", "facility", "site plan")
_SCOPE_RE = re.compile(
    r"\b((?:the|this|that|our|whole|entire|active|current|complete|full)\s+)*"
    r"(?:" + "|".join(_SCOPE_NOUNS) + r")\b",
    re.IGNORECASE,
)

_ORDINAL_SUFFIX_RE = re.compile(r"\b(\d{1,2})\s*(?:st|nd|rd|th)\b", re.IGNORECASE)
_FLOOR_ALT = "|".join(FLOOR_WORDS)
_POSITIONAL_ALT = "|".join(
    sorted((*ORDINAL_WORDS.keys(), *TOP_WORDS, *BOTTOM_WORDS), key=len, reverse=True)
)

#: A floor reference needs floor language AND a positional qualifier, in either
#: order: "the second floor", "floor 2", "level 3", "the top storey".
_FLOOR_REFERENCE_RES = (
    re.compile(
        rf"\b(?:the\s+)?({_POSITIONAL_ALT})\s+(?:{_FLOOR_ALT})\b",
        re.IGNORECASE,
    ),
    re.compile(rf"\b(?:{_FLOOR_ALT})\s*[-#]?\s*(\d{{1,2}})\b", re.IGNORECASE),
    re.compile(rf"\b(\d{{1,2}})\s*(?:st|nd|rd|th)\s+(?:{_FLOOR_ALT})\b", re.IGNORECASE),
)


def _add(spans: list[ModifierSpan], kind: ModifierKind, text: str, start: int, end: int) -> None:
    if not text.strip():
        return
    spans.append(ModifierSpan(kind=kind, text=text.strip(), start=start, end=end))


def detect_spans(question: str | None, *, max_spans: int = 24) -> list[ModifierSpan]:
    """Bounded, ordered modifier spans for one question (§2.4).

    Ordered by position so the binding can be checked against them
    deterministically, and capped so a pathological input cannot produce an
    unbounded slate.
    """
    if not question:
        return []
    spans: list[ModifierSpan] = []

    for match in _QUOTED_RE.finditer(question):
        value = next((g for g in match.groups() if g is not None), "")
        _add(spans, ModifierKind.QUOTED_VALUE, value, match.start(), match.end())

    for match in _COMPARISON_RE.finditer(question):
        _add(spans, ModifierKind.COMPARISON, match.group(0), match.start(), match.end())

    for match in _NUMBER_UNIT_RE.finditer(question):
        _add(spans, ModifierKind.NUMERIC_BOUND, match.group(0), match.start(), match.end())
        if match.group(2):
            _add(spans, ModifierKind.UNIT, match.group(2), match.start(2), match.end(2))

    for match in _NEGATION_RE.finditer(question):
        _add(spans, ModifierKind.NEGATION, match.group(0), match.start(), match.end())

    for match in _PREVIOUS_RESULT_RE.finditer(question):
        _add(
            spans,
            ModifierKind.PREVIOUS_RESULT_REFERENCE,
            match.group(0),
            match.start(),
            match.end(),
        )

    for match in _SELECTION_RE.finditer(question):
        _add(spans, ModifierKind.SELECTION_REFERENCE, match.group(0), match.start(), match.end())

    floor_ranges: list[tuple[int, int]] = []
    for pattern in _FLOOR_REFERENCE_RES:
        for match in pattern.finditer(question):
            floor_ranges.append((match.start(), match.end()))
            _add(spans, ModifierKind.FLOOR_REFERENCE, match.group(0), match.start(), match.end())

    # A scope reference is only a scope reference when it is not part of a floor
    # reference — "the top floor of this building" carries both, and the floor
    # part must stay a condition while the building part stays scope.
    for match in _SCOPE_RE.finditer(question):
        if any(start <= match.start() < end for start, end in floor_ranges):
            continue
        _add(spans, ModifierKind.SCOPE_REFERENCE, match.group(0), match.start(), match.end())

    spans = _dedupe(spans)
    spans.sort(key=lambda s: (s.start, s.end, s.kind.value))
    return spans[:max_spans]


def _dedupe(spans: list[ModifierSpan]) -> list[ModifierSpan]:
    """Drop spans of the same kind fully contained in another of that kind."""
    kept: list[ModifierSpan] = []
    for span in sorted(spans, key=lambda s: (s.kind.value, s.start, -(s.end - s.start))):
        if any(
            other.kind is span.kind and other.start <= span.start and span.end <= other.end
            for other in kept
        ):
            continue
        kept.append(span)
    return kept


def material_spans(spans: list[ModifierSpan]) -> list[ModifierSpan]:
    """Only the spans the binding must account for (§2.4)."""
    return [s for s in spans if s.material]
