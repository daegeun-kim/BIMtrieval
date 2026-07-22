"""Typed constraint ledger (task25 §3.2).

Every material element of a request becomes a ledger item with a stable
request-local ID and typed provenance. The binder must then account for each
REQUIRED item explicitly: bound as a subject, condition, scope, output,
relationship intent, redundant with another cited item, ambiguous, or
unavailable. Deterministic validation rejects a binding that leaves one
undisposed (§3.3).

Why this replaces the Task 24 token heuristic
---------------------------------------------
Task 24 approximated the same guarantee by collecting question tokens and
checking whether the binding "explained" them. The set of explainers included
`output_field_candidate_ids` — fields the answer should REPORT — which carry no
filtering semantics at all. So this binding validated:

    "how many external walls?"
    subject = IfcWall, conditions = [], output_fields = [Pset_WallCommon.IsExternal]

The word "external" was considered accounted for because a field named
`IsExternal` was being reported, and the executed predicate counted every wall
in the model, reported as EXACT.

A ledger makes that unrepresentable rather than merely detected. Items carry a
ROLE, and discharging one requires a disposition of the matching kind: an item
whose role is `condition` can only be discharged by a bound condition, never by
an output field. The distinction is structural, so it cannot be reintroduced by
a prompt change or a new explainer.

Items come from two sources, and both are needed:

- typed SPANS (quoted values, comparisons, numbers, units, negation, floor and
  scope references) — `spans.py` already detects these well;
- content RUNS (contiguous meaningful words such as "external walls" or "fire
  rated doors"). Task 24's `spans.py` docstring promised field/value spans and
  nothing ever produced them, which is precisely why the token heuristic had to
  exist alongside it. Compound-noun qualifiers get first-class representation
  here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from app.query.binding.lexical import singularize
from app.query.binding.spans import ModifierKind, ModifierSpan, detect_spans

__all__ = [
    "LedgerRole",
    "LedgerSource",
    "LedgerItem",
    "ConstraintLedger",
    "build_ledger",
]


class LedgerRole(str, Enum):
    """What the item is asking the pipeline to do.

    Tentative at build time — the binder may reclassify, but only by DECLARING
    the reclassification, never by silently ignoring the item.
    """

    #: A thing to count, list, or describe.
    SUBJECT = "subject"
    #: A restriction on which things qualify.
    CONDITION = "condition"
    #: Where to look, which is not a restriction on what qualifies.
    SCOPE = "scope"
    #: A field the answer should report, or a requested aggregate.
    OUTPUT = "output"
    #: A traversal between things.
    RELATIONSHIP = "relationship"


class LedgerSource(str, Enum):
    """Where the item came from, so provenance is typed rather than guessed."""

    #: An exact span of the current question.
    QUESTION_SPAN = "question_span"
    #: Inherited from the previous accepted result's typed scope.
    INHERITED_SCOPE = "inherited_scope"
    #: The user's current viewer selection.
    SELECTION = "selection"


@dataclass(frozen=True)
class LedgerItem:
    item_id: str
    text: str
    role: LedgerRole
    source: LedgerSource
    required: bool = True
    #: Boolean grouping, so AND/OR structure cannot be flattened silently.
    bool_group: str | None = None
    negated: bool = False
    start: int = -1
    end: int = -1
    #: The typed span kind when this item came from one.
    span_kind: str | None = None

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.item_id,
            "text": self.text,
            "role": self.role.value,
            "source": self.source.value,
            "required": self.required,
        }
        if self.span_kind:
            payload["kind"] = self.span_kind
        if self.bool_group:
            payload["group"] = self.bool_group
        if self.negated:
            payload["negated"] = True
        return payload


@dataclass
class ConstraintLedger:
    question: str
    items: list[LedgerItem] = field(default_factory=list)
    spans: list[ModifierSpan] = field(default_factory=list)

    def item(self, item_id: str) -> LedgerItem | None:
        return next((i for i in self.items if i.item_id == item_id), None)

    def required_items(self) -> list[LedgerItem]:
        return [i for i in self.items if i.required]

    def items_with_role(self, *roles: LedgerRole) -> list[LedgerItem]:
        wanted = frozenset(roles)
        return [i for i in self.items if i.role in wanted]

    def to_payload(self) -> dict[str, Any]:
        return {"items": [i.to_payload() for i in self.items]}

    def size_report(self) -> dict[str, int]:
        return {
            "items": len(self.items),
            "required": len(self.required_items()),
            "spans": len(self.spans),
        }


# ---------------------------------------------------------------------------
# Vocabulary that carries no request content
# ---------------------------------------------------------------------------

#: Interrogatives, determiners, and operation verbs. These shape a request but
#: are not themselves things to bind, so they never become required items.
#:
#: Deliberately contains NO domain noun. A building word placed here would make
#: the pipeline silently ignore a real constraint — which is the exact failure
#: this module exists to prevent.
_STRUCTURAL_WORDS = frozenset(
    {
        "a",
        "all",
        "am",
        "an",
        "and",
        "any",
        "are",
        "as",
        "at",
        "be",
        "been",
        "being",
        "between",
        "both",
        "but",
        "by",
        "can",
        "could",
        "did",
        "do",
        "does",
        "each",
        "every",
        "for",
        "from",
        "get",
        "give",
        "had",
        "has",
        "have",
        "how",
        "i",
        "if",
        "in",
        "into",
        "is",
        "it",
        "its",
        "just",
        "list",
        "many",
        "me",
        "much",
        "must",
        "my",
        "of",
        "on",
        "or",
        "our",
        "out",
        "please",
        "show",
        "some",
        "tell",
        "than",
        "that",
        "the",
        "their",
        "them",
        "then",
        "there",
        "these",
        "they",
        "this",
        "those",
        "to",
        "total",
        "us",
        "was",
        "we",
        "were",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "will",
        "with",
        "would",
        "you",
        "your",
        "count",
        "number",
        "amount",
        "find",
        "display",
        "highlight",
        "select",
        "summarize",
        "describe",
        "average",
        "sum",
        "min",
        "max",
        "most",
        "least",
        "compare",
    }
)

#: Words that mark the item as an OUTPUT request rather than a restriction.
_OUTPUT_MARKERS = frozenset({"list", "show", "display", "name", "names", "detail", "details"})

_WORD_RE = re.compile(r"[^\W\d_]+", re.UNICODE)


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------


def build_ledger(
    question: str,
    *,
    previous_scope: Any | None = None,
    selected_entities: list[dict[str, Any]] | None = None,
) -> ConstraintLedger:
    """Derive the typed ledger for one request."""
    ledger = ConstraintLedger(question=question or "")
    ledger.spans = detect_spans(question)

    counter = _Counter()

    for span in ledger.spans:
        item = _item_from_span(span, counter)
        if item is not None:
            ledger.items.append(item)

    for item in _items_from_content(question, ledger.spans, counter):
        ledger.items.append(item)

    # Typed inherited provenance — §3.2 requires explicitly inherited scope to
    # be a ledger item too, so a binding that silently drops "of those" is
    # detectable in exactly the same way as a dropped word.
    if previous_scope is not None:
        ledger.items.append(
            LedgerItem(
                item_id=counter.next("L"),
                text="the previous result",
                role=LedgerRole.SCOPE,
                source=LedgerSource.INHERITED_SCOPE,
                required=False,
            )
        )
    if selected_entities:
        ledger.items.append(
            LedgerItem(
                item_id=counter.next("L"),
                text="the current viewer selection",
                role=LedgerRole.SCOPE,
                source=LedgerSource.SELECTION,
                required=False,
            )
        )

    return ledger


class _Counter:
    def __init__(self) -> None:
        self._n = 0

    def next(self, prefix: str) -> str:
        self._n += 1
        return f"{prefix}{self._n}"


#: Span kinds that restrict which objects qualify.
_CONDITION_SPANS = {
    ModifierKind.QUOTED_VALUE,
    ModifierKind.COMPARISON,
    ModifierKind.NUMERIC_BOUND,
    ModifierKind.NEGATION,
}
#: Span kinds that choose where to look.
_SCOPE_SPANS = {
    ModifierKind.SCOPE_REFERENCE,
    ModifierKind.PREVIOUS_RESULT_REFERENCE,
    ModifierKind.SELECTION_REFERENCE,
    ModifierKind.FLOOR_REFERENCE,
}


def _item_from_span(span: ModifierSpan, counter: _Counter) -> LedgerItem | None:
    if span.kind in _CONDITION_SPANS:
        role = LedgerRole.CONDITION
    elif span.kind in _SCOPE_SPANS:
        role = LedgerRole.SCOPE
    else:
        # A UNIT qualifies a neighbouring numeric bound rather than standing
        # alone, so it is recorded but not separately required.
        role = LedgerRole.CONDITION

    return LedgerItem(
        item_id=counter.next("L"),
        text=span.text,
        role=role,
        source=LedgerSource.QUESTION_SPAN,
        # A scope reference is genuinely not a restriction — "in this building"
        # must never become a floor predicate — so it is tracked but optional.
        required=span.kind not in (ModifierKind.SCOPE_REFERENCE, ModifierKind.UNIT),
        negated=span.kind is ModifierKind.NEGATION,
        start=span.start,
        end=span.end,
        span_kind=span.kind.value,
    )


def _items_from_content(
    question: str, spans: list[ModifierSpan], counter: _Counter
) -> list[LedgerItem]:
    """Contiguous runs of meaningful words become subject/condition items.

    A multi-word run yields a SUBJECT item for the whole phrase plus a required
    CONDITION item for EVERY word in it. That looks redundant and is deliberate:
    it is the only language-independent way to guarantee no qualifier is lost.

    Guessing which word is the head would embed English word order. English puts
    the qualifier first ("load-bearing walls"), French puts it last ("murs
    porteurs") — so any fixed head position silently drops the constraint for
    half the languages this tool sees.

    Requiring every word instead is fail-safe. A word the chosen subject already
    accounts for is discharged as `bound_subject` ("curtain" and "walls" are both
    satisfied by binding IfcCurtainWall), which costs one disposition. A word the
    subject does NOT account for stays undisposed and fails validation — which is
    exactly what must happen for "external" in "external walls".
    """
    if not question:
        return []

    covered = _covered_offsets(spans)
    items: list[LedgerItem] = []

    for run_text, start, end in _content_runs(question, covered):
        words = _WORD_RE.findall(run_text)
        if not words:
            continue

        wants_output = any(w.casefold() in _OUTPUT_MARKERS for w in words)
        items.append(
            LedgerItem(
                item_id=counter.next("L"),
                text=run_text,
                role=LedgerRole.OUTPUT if wants_output else LedgerRole.SUBJECT,
                source=LedgerSource.QUESTION_SPAN,
                start=start,
                end=end,
            )
        )

        # Every word of a multi-word phrase is its own required item, so the
        # binding must say what it did with each one.
        if len(words) > 1:
            seen: set[str] = set()
            for word in words:
                key = singularize(word.casefold())
                if key in seen:
                    continue
                seen.add(key)
                items.append(
                    LedgerItem(
                        item_id=counter.next("L"),
                        text=word,
                        role=LedgerRole.CONDITION,
                        source=LedgerSource.QUESTION_SPAN,
                        start=start,
                        end=end,
                    )
                )

    return items


def _covered_offsets(spans: list[ModifierSpan]) -> set[int]:
    """Character offsets already accounted for by a typed span."""
    covered: set[int] = set()
    for span in spans:
        if span.start >= 0 and span.end > span.start:
            covered.update(range(span.start, span.end))
    return covered


def _content_runs(question: str, covered: set[int]) -> list[tuple[str, int, int]]:
    """Split the question into runs of adjacent content words."""
    runs: list[tuple[str, int, int]] = []
    current: list[str] = []
    start = -1
    end = -1

    for match in _WORD_RE.finditer(question):
        word = match.group(0)
        is_content = (
            word.casefold() not in _STRUCTURAL_WORDS
            and not covered.intersection(range(match.start(), match.end()))
            and len(word) > 1
        )
        if is_content:
            if not current:
                start = match.start()
            current.append(word)
            end = match.end()
            continue
        if current:
            runs.append((question[start:end], start, end))
            current = []
    if current:
        runs.append((question[start:end], start, end))

    # The RAW substring is kept as the item text. Normalizing here would fold
    # diacritics and silently rename a constraint the user actually typed
    # ("bärande" -> "barande"), which breaks both matching and the message the
    # user eventually reads. Normalization belongs at comparison time.
    return runs
