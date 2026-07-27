"""Deterministic retrieval-requirement ledger (task26 §6, task30 §3).

The ledger is a graph of typed REQUEST REQUIREMENTS, not a bag of meaningful
words. Under Task 30 it has ONE job on the active path: carrying retrieval
hints into recall.

`app.query.binding.obligations.build_recall_ledger` is what fills it — one
requirement per typed obligation, so its `source_text` is a hint used to find
backend candidates and nothing more. Such a ledger is marked `typed`, and no
stage may then use its words to decide a role the resolver already established.
The Task 28/29 machinery that derived roles from phrase shape is gone: it was
the mechanism by which a resolved request lost its own structure.

`build_ledger_skeleton` remains as the lexical path for the no-resolver case
(the deterministic fallback and the dev endpoints). It detects structure from
question text alone and is a retrieval aid and audit artifact only.

Phase 2 (model resolution, `app.query.binding.recall.resolve_ledger`) is shared
by both paths: it attaches candidate semantic IDs, applicability, and a
resolution state from the manifest and the recall channels.

Vocabulary here is structural English (interrogatives, operations, grouping
words). No domain noun, model name, or expected answer appears.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from app.query.binding.multilingual import FUNCTION_WORDS
from app.query.binding.spans import ModifierKind, ModifierSpan, detect_spans

__all__ = [
    "RequirementRole",
    "ResolutionState",
    "LedgerRequirement",
    "LedgerV2",
    "build_ledger_skeleton",
]


class RequirementRole(str, Enum):
    OPERATION = "operation"
    TARGET = "target"
    FILTER = "filter"
    SCOPE = "scope"
    GROUP = "group"
    AGGREGATE = "aggregate"
    ORDER = "order"
    LIMIT = "limit"
    TRAVERSAL = "traversal"
    OUTPUT = "output"
    TOPIC_CONTEXT = "topic_context"
    EVIDENCE_THEME = "evidence_theme"


class ResolutionState(str, Enum):
    #: Phase-1 default, before model resolution runs.
    UNRESOLVED = "unresolved"
    RESOLVABLE = "resolvable"
    AMBIGUOUS = "ambiguous"
    CHECKED_ABSENT = "checked_absent"
    NOT_REPRESENTABLE = "not_representable"
    UNSUPPORTED_OPERATION = "unsupported_operation"


#: Requirement role -> the contract use its disposition must contribute (§6.4).
REQUIRED_USE_BY_ROLE = {
    RequirementRole.TARGET: "target",
    RequirementRole.FILTER: "filter",
    RequirementRole.SCOPE: "scope",
    RequirementRole.GROUP: "group",
    RequirementRole.AGGREGATE: "aggregate",
    RequirementRole.ORDER: "order",
    RequirementRole.TRAVERSAL: "traverse",
    RequirementRole.OUTPUT: "report",
    RequirementRole.TOPIC_CONTEXT: "topic_context",
}


@dataclass
class LedgerRequirement:
    requirement_id: str
    source_text: str
    start: int
    end: int
    role: RequirementRole
    required: bool = True
    #: Which peer answer part this requirement belongs to ("P1", "P2", ...).
    part_hint: str = "P1"
    #: Requirement this one qualifies (a filter's target, an order's group).
    target_hint: str | None = None
    bool_group: str | None = None
    negated: bool = False
    source: str = "question_span"
    span_kind: str | None = None
    #: Explicit limit value when the language fixed one ("one door" -> 1).
    limit_value: int | None = None
    #: The resolved-intent handle this requirement represents (task28 §4): a
    #: part id for a target/operation/output, a constraint id for everything
    #: else. Empty only on the lexical fallback path. This is what lets
    #: preservation checking say WHICH piece of user meaning went missing,
    #: rather than which token did.
    intent_ref: str | None = None

    # -- phase 2 (model resolution) -----------------------------------------
    resolution: ResolutionState = ResolutionState.UNRESOLVED
    candidate_ids: list[str] = field(default_factory=list)
    resolution_note: str | None = None
    partial_policy: str = "none"
    #: Set when an exhaustive stored-value scan found no value matching this
    #: qualifier, so an `unavailable` disposition is honest rather than a
    #: silently dropped condition (task27 §2).
    value_scan_absent: bool = False

    @property
    def required_use(self) -> str | None:
        return REQUIRED_USE_BY_ROLE.get(self.role)

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.requirement_id,
            "text": self.source_text,
            "role": self.role.value,
            "required": self.required,
            "part": self.part_hint,
            "resolution": self.resolution.value,
        }
        if self.required_use:
            payload["required_use"] = self.required_use
        if self.target_hint:
            payload["target_hint"] = self.target_hint
        if self.bool_group:
            payload["or_group"] = self.bool_group
        if self.negated:
            payload["negated"] = True
        if self.candidate_ids:
            payload["candidates"] = self.candidate_ids[:8]
        if self.resolution_note:
            payload["note"] = self.resolution_note
        if self.partial_policy != "none":
            payload["partial_policy"] = self.partial_policy
        if self.value_scan_absent:
            payload["no_stored_value_matches"] = True
        if self.limit_value is not None:
            payload["limit"] = self.limit_value
        if self.intent_ref:
            payload["from_intent"] = self.intent_ref
        if self.source != "question_span":
            payload["source"] = self.source
        return payload


@dataclass
class LedgerV2:
    question: str
    requirements: list[LedgerRequirement] = field(default_factory=list)
    spans: list[ModifierSpan] = field(default_factory=list)
    #: True when the requirements ARE typed obligations from the resolved intent
    #: (task30 §3). Their `source_text` is then a retrieval hint only, and no
    #: stage may use it to decide a role the resolver already established — in
    #: particular lexical coverage becomes a diagnostic signal rather than the
    #: authority on whether meaning survived.
    typed: bool = False

    def requirement(self, requirement_id: str) -> LedgerRequirement | None:
        return next(
            (r for r in self.requirements if r.requirement_id == requirement_id), None
        )

    def required(self) -> list[LedgerRequirement]:
        return [r for r in self.requirements if r.required]

    def with_role(self, *roles: RequirementRole) -> list[LedgerRequirement]:
        wanted = frozenset(roles)
        return [r for r in self.requirements if r.role in wanted]

    def part_hints(self) -> list[str]:
        seen: list[str] = []
        for requirement in self.requirements:
            if requirement.part_hint not in seen:
                seen.append(requirement.part_hint)
        return seen

    def for_intent(self, intent_ref: str) -> list[LedgerRequirement]:
        """Every requirement derived from one intent part or constraint (§4)."""
        return [r for r in self.requirements if r.intent_ref == intent_ref]

    def to_payload(self) -> dict[str, Any]:
        return {"requirements": [r.to_payload() for r in self.requirements]}

    def size_report(self) -> dict[str, int]:
        return {
            "requirements": len(self.requirements),
            "required": len(self.required()),
            "parts": len(self.part_hints()),
            "from_intent": len([r for r in self.requirements if r.intent_ref]),
        }


# ---------------------------------------------------------------------------
# Structural vocabulary (no domain nouns)
# ---------------------------------------------------------------------------

_OPERATION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("count", re.compile(r"\b(how many|count of|number of|total number|count)\b", re.I)),
    ("existence", re.compile(r"\b(is there|are there|does .{1,40} (?:have|contain)|do .{1,40} (?:have|contain))\b", re.I)),
    ("distribution", re.compile(r"\b(distribution|breakdown|per type|by type|what (?:kinds|types)|which (?:kinds|types)|grouped by)\b", re.I)),
    ("aggregate", re.compile(r"\b(total|sum of|average|mean|combined)\b", re.I)),
    ("sample", re.compile(r"\b(one example|an example|a sample|show me one|just one|any one)\b", re.I)),
    ("list", re.compile(r"\b(list|show|display|name all|enumerate|which are)\b", re.I)),
    ("description", re.compile(r"\b(describe|summarize|summarise|overview|tell me about|what is this|what can you tell)\b", re.I)),
    ("comparison", re.compile(r"\b(compare|difference between|versus|vs\.?)\b", re.I)),
)

_EXTREMUM_RE = re.compile(
    r"\b(which|what)\b.{0,60}?\b(the )?(most|fewest|least|highest|lowest|greatest|largest number|smallest number)\b",
    re.I | re.S,
)

#: "which <group> has/have/contains the most <target>"
_EXTREMUM_PARTS_RE = re.compile(
    r"\b(?:which|what)\s+(?P<group>[^\W\d_][\w\- ]{1,40}?)\s+"
    r"(?:has|have|contains?|holds?)\s+the\s+"
    r"(?:most|fewest|least|highest|lowest|greatest)\s+"
    r"(?P<target>[^\W\d_][\w\- ]{1,40}?)(?=[,.?;!]|$)",
    re.I,
)

#: Sample-language that must not be mistaken for a requested output field.
_SAMPLE_LANGUAGE_RE = re.compile(r"\b(example|sample|one|single|instance)s?\b", re.I)

_GROUP_BY_RE = re.compile(
    r"\b(?:per|by|for each|on each|grouped by|in each)\s+([^\W\d_][\w\- ]{1,40}?)(?=[,.?;]|\s+(?:and|or|with|that|which|in|on)\b|$)",
    re.I,
)

_TRAVERSAL_RE = re.compile(
    r"\b(connected to|connects to|connect to|adjacent to|next to|leads to|lead to|fills?|filled by|"
    r"voids?|voided by|hosted by|hosts|contained in|contains|belongs to|serves|served by|attached to)\b",
    re.I,
)

_OUTPUT_OF_RE = re.compile(
    r"\b(?:what (?:is|are)|list|show(?: me)?|give me|describe)\s+(?:the\s+|all\s+)?"
    r"(?P<output>[^\W\d_][\w\- ]{1,50}?)\s+(?:of|for)\s+",
    re.I,
)

_MADE_OF_RE = re.compile(r"\bmade (?:of|out of|from)\b", re.I)

_SAMPLE_ONE_RE = re.compile(r"\b(?:one|a single|an?)\s+(?:example|sample)\b|\bshow me one\b", re.I)

_PEER_SPLIT_RE = re.compile(
    r"(?:\band\b|,|;)\s+(?=(?:how many|how much|what|which|list|show|count|is there|are there|describe)\b)",
    re.I,
)

#: Language asking for ONE combined figure over coordinated peer subjects. With
#: it, "stairs and ramps" is a single union target; without it, a coordinated
#: list is a set of independent requests, each with its own part (task27 §2).
_UNION_TOTAL_RE = re.compile(
    r"\b(total|totals|combined|altogether|together|in total|overall|sum)\b", re.I
)

_WORD_RE = re.compile(r"[^\W\d_]+", re.UNICODE)

#: Interrogatives, determiners, operation verbs, and grouping words that shape
#: a request but are never themselves things to bind. NO domain noun.
_STRUCTURAL_WORDS = (
    frozenset(
        """a all am an and any are as at be been being both but by can could did do does
    each every for from get give had has have how i if in into is it its just many
    me much must my of on or our out please show some tell than that the their them
    then there these they this those to total us was we were what when where which
    who why will with would you your count number amount find display highlight
    select summarize summarise describe average sum min max most least fewest
    highest lowest compare list name enumerate per grouped group by made there
    contain contains have one single example examples sample samples instance
    instances either neither pick picks picked choose chose chosen fetch grab
    identify provide want need know kindly also please combined altogether
    together overall""".split()
    )
    | FUNCTION_WORDS
)

#: Words that name "whatever you have" rather than a concept to bind. A run made
#: only of these is a (non-required) requested-output marker, never an occurrence
#: target: the recorded defect was "details" becoming a target class (task27 §2).
_OUTPUT_MARKERS = frozenset(
    {
        "list",
        "show",
        "display",
        "name",
        "names",
        "detail",
        "details",
        "info",
        "information",
        "properties",
        "attributes",
        "data",
        "values",
        "overview",
    }
)


class _Counter:
    def __init__(self) -> None:
        self._n = 0

    def next(self) -> str:
        self._n += 1
        return f"L{self._n}"


# ---------------------------------------------------------------------------
# Phase 1b: lexical intent skeleton (deterministic fallback path)
# ---------------------------------------------------------------------------


def build_ledger_skeleton(
    question: str,
    *,
    previous_scope: Any | None = None,
    selected_entities: list[dict[str, Any]] | None = None,
) -> LedgerV2:
    ledger = LedgerV2(question=question or "")
    if not question:
        return ledger
    ledger.spans = detect_spans(question)
    counter = _Counter()

    segments = _split_segments(question)
    for index, (seg_start, seg_end) in enumerate(segments):
        part = f"P{index + 1}"
        _skeleton_for_segment(question, seg_start, seg_end, part, ledger, counter)

    # Typed inherited provenance (§6.3): explicitly present so a binding that
    # silently drops "of those" is detectable like any dropped requirement.
    if previous_scope is not None:
        ledger.requirements.append(
            LedgerRequirement(
                requirement_id=counter.next(),
                source_text="the previous result",
                start=-1,
                end=-1,
                role=RequirementRole.SCOPE,
                required=False,
                source="inherited_scope",
            )
        )
    if selected_entities:
        ledger.requirements.append(
            LedgerRequirement(
                requirement_id=counter.next(),
                source_text="the current viewer selection",
                start=-1,
                end=-1,
                role=RequirementRole.SCOPE,
                required=False,
                source="selection",
            )
        )
    _merge_targetless_parts(ledger)
    return ledger


def _merge_targetless_parts(ledger: LedgerV2) -> None:
    """Fold a part that names nothing to count into the part before it.

    "Pick a sample door and show me its details" splits on "and show", but the
    trailing segment has no subject of its own: its words qualify the FIRST
    part's subject. Leaving it as a separate part invented a second occurrence
    target out of "details" (task27 §2). A part with no target requirement
    therefore hands its requirements to the previous part.
    """
    hints = ledger.part_hints()
    with_target = {
        r.part_hint for r in ledger.requirements if r.role is RequirementRole.TARGET
    }
    previous: str | None = None
    for hint in hints:
        if hint in with_target:
            previous = hint
            continue
        if previous is None:
            continue
        for requirement in ledger.requirements:
            if requirement.part_hint == hint:
                requirement.part_hint = previous


def _split_segments(question: str) -> list[tuple[int, int]]:
    segments: list[tuple[int, int]] = []
    last = 0
    for match in _PEER_SPLIT_RE.finditer(question):
        segments.append((last, match.start()))
        last = match.end()
    segments.append((last, len(question)))
    return [(s, e) for s, e in segments if question[s:e].strip()]


def _skeleton_for_segment(
    question: str,
    seg_start: int,
    seg_end: int,
    part: str,
    ledger: LedgerV2,
    counter: _Counter,
) -> None:
    segment = question[seg_start:seg_end]

    # -- operation ----------------------------------------------------------
    # The operation is structural: it is expressed by the part's `result_kind`,
    # not by a node the binder cites, so it is tracked for context but never a
    # required disposition (requiring one invites a mis-kinded disposition that
    # blocks an otherwise-correct plan).
    operation, op_span = _detect_operation(segment)
    ledger.requirements.append(
        LedgerRequirement(
            requirement_id=counter.next(),
            source_text=op_span or operation,
            start=seg_start,
            end=seg_end,
            role=RequirementRole.OPERATION,
            required=False,
            part_hint=part,
            resolution=ResolutionState.RESOLVABLE,
            resolution_note=operation,
        )
    )

    # -- grouped extremum ("which floor has the most doors") ----------------
    extremum = _EXTREMUM_RE.search(segment)
    extremum_claimed: set[int] = set()
    if extremum:
        ledger.requirements.append(
            LedgerRequirement(
                requirement_id=counter.next(),
                source_text=extremum.group(0)[:80],
                start=seg_start + extremum.start(),
                end=seg_start + extremum.end(),
                role=RequirementRole.ORDER,
                required=True,
                part_hint=part,
                limit_value=1,
                resolution=ResolutionState.RESOLVABLE,
            )
        )
        # "which <group> has the most <target>": the grouping axis and the
        # counted subject are different requirements with different uses.
        parts_match = _EXTREMUM_PARTS_RE.search(segment)
        if parts_match:
            for group_name, role in (("group", RequirementRole.GROUP), ("target", RequirementRole.TARGET)):
                text = parts_match.group(group_name).strip()
                if not text or all(
                    w.casefold() in _STRUCTURAL_WORDS for w in _WORD_RE.findall(text)
                ):
                    continue
                start = seg_start + parts_match.start(group_name)
                end = seg_start + parts_match.end(group_name)
                ledger.requirements.append(
                    LedgerRequirement(
                        requirement_id=counter.next(),
                        source_text=text,
                        start=start,
                        end=end,
                        role=role,
                        required=True,
                        part_hint=part,
                    )
                )
                extremum_claimed.update(range(start, end))

    # -- explicit group-by --------------------------------------------------
    for match in _GROUP_BY_RE.finditer(segment):
        ledger.requirements.append(
            LedgerRequirement(
                requirement_id=counter.next(),
                source_text=match.group(1).strip(),
                start=seg_start + match.start(1),
                end=seg_start + match.end(1),
                role=RequirementRole.GROUP,
                required=True,
                part_hint=part,
            )
        )

    # -- traversal intent ---------------------------------------------------
    for match in _TRAVERSAL_RE.finditer(segment):
        ledger.requirements.append(
            LedgerRequirement(
                requirement_id=counter.next(),
                source_text=match.group(0),
                start=seg_start + match.start(),
                end=seg_start + match.end(),
                role=RequirementRole.TRAVERSAL,
                required=True,
                part_hint=part,
            )
        )

    # -- requested output ("materials of the doors", "made of") -------------
    # A phrase already detected as a typed span is that span's requirement, not
    # a second unresolvable output one: "What is on the top floor of this
    # building?" produced BOTH a scope requirement for the floor and a duplicate
    # `report` requirement for the same words, and the duplicate had no possible
    # binding (task27 §2, §4).
    span_claimed = {
        position
        for span in ledger.spans
        if span.material and seg_start <= span.start < seg_end
        for position in range(span.start, span.end)
    }
    output_match = _OUTPUT_OF_RE.search(segment)
    if (
        output_match
        and not _EXTREMUM_RE.search(output_match.group(0))
        and not _SAMPLE_LANGUAGE_RE.search(output_match.group("output"))
        and not span_claimed.intersection(
            range(seg_start + output_match.start("output"), seg_start + output_match.end("output"))
        )
    ):
        text = output_match.group("output").strip()
        if text and not all(w.casefold() in _STRUCTURAL_WORDS for w in _WORD_RE.findall(text)):
            ledger.requirements.append(
                LedgerRequirement(
                    requirement_id=counter.next(),
                    source_text=text,
                    start=seg_start + output_match.start("output"),
                    end=seg_start + output_match.end("output"),
                    role=RequirementRole.OUTPUT,
                    required=True,
                    part_hint=part,
                )
            )
    if _MADE_OF_RE.search(segment):
        match = _MADE_OF_RE.search(segment)
        ledger.requirements.append(
            LedgerRequirement(
                requirement_id=counter.next(),
                source_text=match.group(0),
                start=seg_start + match.start(),
                end=seg_start + match.end(),
                role=RequirementRole.OUTPUT,
                required=True,
                part_hint=part,
            )
        )

    if operation == "sample":
        # The limit is structural (part.limit), tracked but not a required
        # disposition.
        ledger.requirements.append(
            LedgerRequirement(
                requirement_id=counter.next(),
                source_text="one",
                start=seg_start,
                end=seg_end,
                role=RequirementRole.LIMIT,
                required=False,
                part_hint=part,
                limit_value=1,
                resolution=ResolutionState.RESOLVABLE,
            )
        )

    # -- typed spans inside this segment ------------------------------------
    claimed: set[int] = set(extremum_claimed)
    for requirement in ledger.requirements:
        if requirement.part_hint == part and requirement.start >= 0:
            if requirement.role in (
                RequirementRole.OUTPUT,
                RequirementRole.GROUP,
                RequirementRole.TARGET,
                RequirementRole.ORDER,
                RequirementRole.TRAVERSAL,
            ):
                claimed.update(range(requirement.start, requirement.end))

    for span in ledger.spans:
        if not (seg_start <= span.start < seg_end):
            continue
        role = _role_for_span(span)
        if role is None:
            continue
        required = span.material
        ledger.requirements.append(
            LedgerRequirement(
                requirement_id=counter.next(),
                source_text=span.text,
                start=span.start,
                end=span.end,
                role=role,
                required=required,
                part_hint=part,
                negated=span.kind is ModifierKind.NEGATION,
                span_kind=span.kind.value,
                resolution=(
                    ResolutionState.RESOLVABLE
                    if role is RequirementRole.TOPIC_CONTEXT
                    else ResolutionState.UNRESOLVED
                ),
            )
        )
        claimed.update(range(span.start, span.end))

    # -- content phrases ----------------------------------------------------
    runs = _content_runs(question, seg_start, seg_end, claimed)
    target_assigned = any(
        r.part_hint == part and r.role is RequirementRole.TARGET for r in ledger.requirements
    )
    # Coordinated peer subjects ("doors, windows and stairs"): one combined
    # figure was asked for, or several independent ones (task27 §2).
    one_total = bool(_UNION_TOTAL_RE.search(segment))
    peer_parts: list[str] = [part]
    previous_id: str | None = None
    or_group = 0
    for run_text, run_start, run_end, after_or, after_and in runs:
        if after_or and previous_id is not None:
            group = f"G{or_group}"
            previous = ledger.requirement(previous_id)
            if previous is not None and previous.bool_group is None:
                previous.bool_group = group
        else:
            or_group += 1
            group = None

        markers = [w.casefold() for w in _WORD_RE.findall(run_text)]
        only_output_markers = bool(markers) and all(w in _OUTPUT_MARKERS for w in markers)
        run_part = part
        if only_output_markers:
            # "details", "information": a request to report what is recorded.
            # Never a subject, and never a required binding of its own.
            role, required = RequirementRole.OUTPUT, False
        elif not target_assigned:
            role, required = RequirementRole.TARGET, True
        elif after_and and not after_or:
            # A peer subject of the same list. One total -> peer targets of the
            # same part (a union); otherwise an independent request of its own.
            role, required = RequirementRole.TARGET, True
            if not one_total:
                run_part = f"{part}_{len(peer_parts) + 1}"
                peer_parts.append(run_part)
        else:
            role, required = RequirementRole.FILTER, True
        requirement = LedgerRequirement(
            requirement_id=counter.next(),
            source_text=run_text,
            start=run_start,
            end=run_end,
            role=role,
            required=required,
            part_hint=run_part,
            bool_group=f"G{or_group}" if after_or else None,
        )
        ledger.requirements.append(requirement)
        previous_id = requirement.requirement_id
        if role is RequirementRole.TARGET:
            target_assigned = True

    # Link filters/orders/groups in each of this segment's parts to its target.
    for peer_part in peer_parts:
        target = next(
            (
                r
                for r in ledger.requirements
                if r.part_hint == peer_part and r.role is RequirementRole.TARGET
            ),
            None,
        )
        if target is None:
            continue
        for requirement in ledger.requirements:
            if (
                requirement.part_hint == peer_part
                and requirement.role
                in (
                    RequirementRole.FILTER,
                    RequirementRole.ORDER,
                    RequirementRole.GROUP,
                    RequirementRole.OUTPUT,
                    RequirementRole.TRAVERSAL,
                )
                and requirement.target_hint is None
            ):
                requirement.target_hint = target.requirement_id

    # A description-type segment carries a qualitative evidence theme (§6.1).
    if operation in ("description", "comparison"):
        theme = _theme_text(question, seg_start, seg_end)
        if theme:
            ledger.requirements.append(
                LedgerRequirement(
                    requirement_id=counter.next(),
                    source_text=theme,
                    start=seg_start,
                    end=seg_end,
                    role=RequirementRole.EVIDENCE_THEME,
                    required=False,
                    part_hint=part,
                    resolution=ResolutionState.RESOLVABLE,
                )
            )


def _detect_operation(segment: str) -> tuple[str, str | None]:
    for name, pattern in _OPERATION_PATTERNS:
        match = pattern.search(segment)
        if match:
            if name == "list" and _SAMPLE_ONE_RE.search(segment):
                return "sample", match.group(0)
            return name, match.group(0)
    if _EXTREMUM_RE.search(segment):
        return "extremum", None
    return "unspecified", None


def _role_for_span(span: ModifierSpan) -> RequirementRole | None:
    if span.kind in (
        ModifierKind.QUOTED_VALUE,
        ModifierKind.COMPARISON,
        ModifierKind.NUMERIC_BOUND,
        ModifierKind.NEGATION,
    ):
        return RequirementRole.FILTER
    if span.kind is ModifierKind.FLOOR_REFERENCE:
        return RequirementRole.SCOPE
    if span.kind in (
        ModifierKind.PREVIOUS_RESULT_REFERENCE,
        ModifierKind.SELECTION_REFERENCE,
    ):
        return RequirementRole.SCOPE
    if span.kind is ModifierKind.SCOPE_REFERENCE:
        return RequirementRole.TOPIC_CONTEXT
    return None


_OR_RE = re.compile(r"\bor\b", re.I)


#: A comma or semicolon inside a segment separates coordinated peers just as
#: "and" does; without this, "doors, windows" collapsed into ONE phrase whose
#: second noun could never be a peer target of its own (task27 §2).
_LIST_SEPARATOR_RE = re.compile(r"[,;/]|\band\b|\bor\b|&|\+", re.I)


def _content_runs(
    question: str, seg_start: int, seg_end: int, claimed: set[int]
) -> list[tuple[str, int, int, bool, bool]]:
    """Contiguous runs of meaningful words, each flagged with how it was joined.

    Returns `(text, start, end, after_or, after_and)`: whether this run followed
    a disjunction ("either external or load bearing") or a coordination of peer
    subjects ("doors, windows and stairs").
    """
    runs: list[tuple[str, int, int, bool, bool]] = []
    current_start = -1
    current_end = -1
    after_or = False
    after_and = False
    pending_or = False
    pending_and = False

    def _flush() -> None:
        nonlocal current_start
        if current_start >= 0:
            runs.append(
                (
                    question[current_start:current_end],
                    current_start,
                    current_end,
                    after_or,
                    after_and,
                )
            )
            current_start = -1

    for match in _WORD_RE.finditer(question, seg_start, seg_end):
        word = match.group(0)
        lowered = word.casefold()
        overlaps = bool(claimed.intersection(range(match.start(), match.end())))
        is_content = lowered not in _STRUCTURAL_WORDS and not overlaps and len(word) > 1
        if is_content:
            if current_start < 0:
                current_start = match.start()
                after_or = pending_or
                after_and = pending_and
            elif _LIST_SEPARATOR_RE.search(question, current_end, match.start()):
                # A separator between two content words ends the run.
                separator = question[current_end : match.start()]
                _flush()
                current_start = match.start()
                after_or = bool(re.search(r"\bor\b", separator, re.I))
                after_and = not after_or
            current_end = match.end()
            pending_or = False
            pending_and = False
            continue
        _flush()
        pending_or = lowered == "or"
        pending_and = lowered == "and"
    _flush()
    return runs


def _theme_text(question: str, seg_start: int, seg_end: int) -> str:
    words = [
        w
        for w in _WORD_RE.findall(question[seg_start:seg_end])
        if w.casefold() not in _STRUCTURAL_WORDS and len(w) > 1
    ]
    return " ".join(words[:8])
