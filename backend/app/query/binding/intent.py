"""Semantic intent resolution: conversation in, authoritative meaning out (task28 §2, §3).

Three deterministic jobs live here, all of them either side of the one cheap
resolver call:

- `serialize_conversation` renders the COMPLETE available conversation in
  original order with no per-message truncation and no 20-turn window. History
  is never silently dropped: when a provider hard limit genuinely cannot hold
  the transcript, the omission is explicit, recorded, and reported.
- `sanitize_intent` enforces that the resolver stayed inside its contract. It
  describes user meaning, so a semantic ID, SQL fragment, or backend field it
  was never shown is a contract violation, not a useful hint.
- `deterministic_intent` builds the same typed object without a model, so the
  pipeline still runs when the resolver is unavailable and offline tests never
  need a provider.

The resolved intent then travels intact; later stages read it instead of
re-reading the transcript (§3), which is what stops a topic, constraint, or
requested output from quietly changing between stages.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.llm.schemas_v5 import (
    ConstraintKind,
    IntentConstraint,
    IntentOperation,
    IntentPart,
    IntentProvenance,
    IntentTarget,
    ResolvedIntent,
    VisualizationIntent,
)

__all__ = [
    "CONVERSATION_CHAR_LIMIT",
    "ConversationTurn",
    "SerializedConversation",
    "PendingClarification",
    "IntentContractError",
    "serialize_conversation",
    "build_intent_context",
    "sanitize_intent",
    "deterministic_intent",
    "intent_payload",
]

#: The only reason a turn may be withheld from the resolver: a provider hard
#: limit. Generous by design — the normal path passes every turn intact (§2).
CONVERSATION_CHAR_LIMIT = 120_000


# ---------------------------------------------------------------------------
# Conversation serialization
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ConversationTurn:
    turn_index: int
    role: str
    content: str

    def to_payload(self) -> dict[str, Any]:
        return {"turn": self.turn_index, "role": self.role, "content": self.content}


@dataclass
class SerializedConversation:
    """Every available turn in original order, plus the current message last."""

    turns: list[ConversationTurn] = field(default_factory=list)
    #: Turns a provider hard limit forced out, oldest first. Normally empty.
    omitted_turns: int = 0
    omission_reason: str | None = None

    @property
    def current_turn_index(self) -> int:
        return self.turns[-1].turn_index if self.turns else 0

    def to_payload(self) -> list[dict[str, Any]]:
        return [t.to_payload() for t in self.turns]

    def diagnostics(self) -> dict[str, Any]:
        record: dict[str, Any] = {"turns": len(self.turns)}
        if self.omitted_turns:
            record["omitted_turns"] = self.omitted_turns
            record["omission_reason"] = self.omission_reason
        return record


def serialize_conversation(
    question: str,
    history: list[dict[str, str]] | None,
    *,
    char_limit: int = CONVERSATION_CHAR_LIMIT,
) -> SerializedConversation:
    """Complete ordered history followed by the current message (§2).

    No turn selection window and no per-message truncation: both existed in the
    v4 binder context and both silently removed the very words a follow-up
    depends on. Only a hard character budget can drop anything, and when it
    does, the drop is counted and explained rather than hidden.
    """
    ordered: list[ConversationTurn] = []
    for index, turn in enumerate(history or []):
        role = str(turn.get("role") or "").strip()
        content = str(turn.get("content") or "").strip()
        if not role or not content:
            continue
        ordered.append(ConversationTurn(turn_index=index, role=role, content=content))

    current = ConversationTurn(
        turn_index=len(ordered), role="user", content=question or ""
    )

    conversation = SerializedConversation(turns=[*ordered, current])
    total = sum(len(t.content) for t in conversation.turns)
    if total <= char_limit:
        return conversation

    # A hard limit: drop the OLDEST turns only, never the current message, and
    # say exactly how many went and why.
    kept: list[ConversationTurn] = [current]
    budget = char_limit - len(current.content)
    for turn in reversed(ordered):
        if len(turn.content) > budget:
            break
        budget -= len(turn.content)
        kept.append(turn)
    kept.reverse()
    dropped = len(conversation.turns) - len(kept)
    conversation.turns = kept
    conversation.omitted_turns = dropped
    conversation.omission_reason = (
        f"the conversation exceeds the {char_limit} character provider limit; "
        f"the {dropped} oldest turn(s) were not sent to interpretation"
    )
    return conversation


# ---------------------------------------------------------------------------
# Pending clarification state (§3, §6)
# ---------------------------------------------------------------------------


@dataclass
class PendingClarification:
    """What the previous turn asked for, carried into the next one (§6).

    Persisted through the existing session mechanism so a clarification answer
    COMPLETES the pending intent rather than being parsed as a new request, and
    so the same question is never asked twice.
    """

    question: str
    slots: list[dict[str, Any]] = field(default_factory=list)
    #: The request this clarification was blocking, so it can be resumed.
    normalized_request: str = ""
    source_model_id: int | None = None

    def matches_model(self, source_model_id: int | None) -> bool:
        return (
            source_model_id is not None and source_model_id == self.source_model_id
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "unresolved": self.slots[:4],
            "blocked_request": self.normalized_request,
        }


# ---------------------------------------------------------------------------
# Resolver input
# ---------------------------------------------------------------------------


def build_intent_context(
    conversation: SerializedConversation,
    *,
    source_model_id: int | None,
    model_label: str | None = None,
    selected_object_count: int = 0,
    has_previous_result: bool = False,
    previous_result_summary: dict[str, Any] | None = None,
    pending: PendingClarification | None = None,
) -> dict[str, Any]:
    """The resolver's complete input (§2).

    Deliberately small: the conversation, the ACTIVE MODEL IDENTITY only, the
    minimal session facts needed to resolve a reference, and any pending
    clarification. Never the manifest, the database, or backend identifiers —
    the resolver describes meaning and must not be able to name a capability it
    was never shown (non-goals).
    """
    session_state: dict[str, Any] = {"active_model_loaded": source_model_id is not None}
    if model_label:
        session_state["active_model_name"] = model_label
    if selected_object_count:
        session_state["objects_selected_in_viewer"] = selected_object_count
    if has_previous_result:
        session_state["previous_result_available"] = True
        if previous_result_summary:
            session_state["previous_result"] = previous_result_summary

    payload: dict[str, Any] = {
        "conversation": conversation.to_payload(),
        "current_turn_index": conversation.current_turn_index,
        "session_state": session_state,
    }
    if conversation.omitted_turns:
        payload["history_limit"] = {
            "omitted_turns": conversation.omitted_turns,
            "reason": conversation.omission_reason,
        }
    if pending is not None:
        payload["pending_clarification"] = pending.to_payload()
    return {"payload": payload}


# ---------------------------------------------------------------------------
# Contract enforcement
# ---------------------------------------------------------------------------


class IntentContractError(ValueError):
    """The resolver produced something outside its user-meaning contract."""


#: Manifest-style identifiers the resolver was never shown, and therefore could
#: only have invented.
_SEMANTIC_ID_RE = re.compile(
    r"\b(?:cls|prop|qty|attr|mat|cla|spatial|path|floor|storey|derived|count)"
    r":[A-Za-z0-9_.\-\[\]>]+"
)
#: An IFC entity/property-set name is a backend fact, not the user's words —
#: unless the user typed it, in which case it stays as their own phrasing.
_IFC_NAME_RE = re.compile(r"\b(?:Ifc[A-Z]\w+|Pset_\w+|Qto_\w+)\b")
_SQL_RE = re.compile(
    r"\b(?:select\s+.+\s+from|insert\s+into|update\s+\w+\s+set|delete\s+from|"
    r"join\s+\w+\s+on|group\s+by|order\s+by)\b",
    re.IGNORECASE,
)


def _intent_strings(intent: ResolvedIntent) -> list[tuple[str, str]]:
    strings: list[tuple[str, str]] = [
        ("normalized_request", intent.normalized_request),
        ("topic", intent.topic),
    ]
    for part in intent.parts:
        strings.append((f"{part.part_id}.request_text", part.request_text))
    strings.extend((t.target_id, t.text) for t in intent.targets)
    strings.extend((c.constraint_id, c.text) for c in intent.constraints)
    strings.extend((r.relationship_id, r.text) for r in intent.relationships)
    strings.extend((r.relationship_id, r.to_text) for r in intent.relationships)
    strings.extend((g.grouping_id, g.axis_text) for g in intent.groupings)
    strings.extend((o.output_id, o.text) for o in intent.outputs)
    for slot in intent.unresolved:
        strings.append((f"{slot.slot_id}.question", slot.question))
        strings.append((f"{slot.slot_id}.about", slot.about_text))
    return [(where, text) for where, text in strings if text]


def sanitize_intent(
    intent: ResolvedIntent, conversation: SerializedConversation
) -> list[str]:
    """Deterministically enforce the resolver's contract; returns violations.

    Anything the user actually typed is theirs to keep — a BIM-literate user may
    well name an IFC class. What is rejected is backend vocabulary the resolver
    invented, because it was never given any (§2).
    """
    spoken = " ".join(t.content for t in conversation.turns).casefold()
    violations: list[str] = []

    for where, text in _intent_strings(intent):
        for match in _SEMANTIC_ID_RE.finditer(text):
            if match.group(0).casefold() not in spoken:
                violations.append(
                    f"{where} names the backend identifier {match.group(0)!r}"
                )
        for match in _IFC_NAME_RE.finditer(text):
            if match.group(0).casefold() not in spoken:
                violations.append(f"{where} names the backend concept {match.group(0)!r}")
        if _SQL_RE.search(text):
            violations.append(f"{where} contains a query fragment")

    # Structural coherence: every constraint and slot must attach to a real part,
    # and every part must be unique.
    part_ids = [p.part_id for p in intent.parts]
    if len(part_ids) != len(set(part_ids)):
        violations.append("duplicate part ids in the resolved intent")
    known = set(part_ids)
    for group, label in (
        (intent.targets, "target"),
        (intent.constraints, "constraint"),
        (intent.relationships, "relationship"),
        (intent.groupings, "grouping"),
        (intent.orderings, "ordering"),
        (intent.outputs, "output"),
    ):
        for element in group:
            if element.part_id not in known:
                violations.append(
                    f"{label} names unknown part {element.part_id!r}"
                )
    for part in intent.parts:
        if not any(t.part_id == part.part_id for t in intent.targets):
            violations.append(f"part {part.part_id} has no target")
    for slot in intent.unresolved:
        if slot.part_id is not None and slot.part_id not in known:
            violations.append(f"slot {slot.slot_id} names unknown part {slot.part_id!r}")
    last_turn = conversation.current_turn_index
    for record in intent.provenance:
        if record.turn_index > last_turn:
            violations.append(
                f"provenance for {record.element_id} names turn {record.turn_index}, "
                f"past the end of the conversation"
            )
    return violations


def repair_intent(intent: ResolvedIntent, conversation: SerializedConversation) -> None:
    """Drop only structurally impossible bookkeeping, never meaning (§7).

    Meaning is never inferred here: an orphaned constraint attaches to the first
    part rather than being deleted, because deleting it would drop exactly the
    kind of condition this task exists to preserve.
    """
    if not intent.parts:
        return
    first = intent.parts[0].part_id
    known = {p.part_id for p in intent.parts}
    for group in (
        intent.targets,
        intent.constraints,
        intent.relationships,
        intent.groupings,
        intent.orderings,
        intent.outputs,
    ):
        for element in group:
            if element.part_id not in known:
                element.part_id = first
    # A part with no subject cannot be answered at all. One is synthesised from
    # the part's own words rather than the part being dropped, because dropping
    # it would silently discard a request the user made.
    for index, part in enumerate(intent.parts):
        if not any(t.part_id == part.part_id for t in intent.targets):
            intent.targets.append(
                IntentTarget(
                    target_id=f"T{len(intent.targets) + index + 1}"[:24],
                    part_id=part.part_id,
                    text=part.request_text[:300],
                )
            )
    for slot in intent.unresolved:
        if slot.part_id is not None and slot.part_id not in known:
            slot.part_id = first
    last_turn = conversation.current_turn_index
    intent.provenance = [
        record for record in intent.provenance if record.turn_index <= last_turn
    ]


# ---------------------------------------------------------------------------
# Provider-free intent (offline tests, resolver failure)
# ---------------------------------------------------------------------------


def deterministic_intent(
    question: str,
    conversation: SerializedConversation,
    *,
    has_previous_result: bool = False,
    selected_object_count: int = 0,
) -> ResolvedIntent:
    """A single-part intent over the current message, with no interpretation.

    Used when the resolver is unavailable. It preserves the request verbatim
    rather than guessing at structure, so the degraded path can lose nothing the
    resolver would have found — it simply finds less.
    """
    text = (question or "").strip() or "the active model"
    constraints: list[IntentConstraint] = []
    if has_previous_result:
        constraints.append(
            IntentConstraint(
                constraint_id="C1",
                part_id="P1",
                text="the previous result",
                kind=ConstraintKind.PREVIOUS_RESULT,
            )
        )
    if selected_object_count:
        constraints.append(
            IntentConstraint(
                constraint_id=f"C{len(constraints) + 1}",
                part_id="P1",
                text="the current viewer selection",
                kind=ConstraintKind.SELECTION,
            )
        )
    return ResolvedIntent(
        normalized_request=text[:1000],
        language="en",
        topic=text[:200],
        parts=[
            IntentPart(
                part_id="P1",
                request_text=text[:300],
                operation=IntentOperation.LIST,
                highlightable=True,
            )
        ],
        targets=[IntentTarget(target_id="T1", part_id="P1", text=text[:300])],
        constraints=constraints,
        visualization=VisualizationIntent.PRIMARY_ONLY,
        provenance=[
            IntentProvenance(
                element_id="P1", turn_index=conversation.current_turn_index
            )
        ],
    )


# ---------------------------------------------------------------------------
# Downstream payload
# ---------------------------------------------------------------------------


def intent_payload(intent: ResolvedIntent) -> dict[str, Any]:
    """The immutable intent as later stages and the trace see it (§3, §5)."""
    payload: dict[str, Any] = {
        "request": intent.normalized_request,
        "language": intent.language,
        "visualization": intent.visualization.value,
        "parts": [
            {
                "part_id": p.part_id,
                "request": p.request_text,
                "operation": p.operation.value,
                "evidence": p.evidence_kind.value,
                "highlightable": p.highlightable,
                **({"limit": p.limit} if p.limit else {}),
            }
            for p in intent.parts
        ],
        "targets": [
            {
                "target_id": t.target_id,
                "part_id": t.part_id,
                "text": t.text,
                "coordination": t.coordination.value,
            }
            for t in intent.targets
        ],
        "constraints": [
            {
                "constraint_id": c.constraint_id,
                "part_id": c.part_id,
                "text": c.text,
                "kind": c.kind.value,
                "operator": c.operator.value,
                **({"value": c.value_text} if c.value_text else {}),
                **({"values": list(c.value_list)} if c.value_list else {}),
                **({"unit": c.unit} if c.unit else {}),
                **({"negated": True} if c.negated else {}),
                **({"or_group": c.or_group} if c.or_group else {}),
            }
            for c in intent.constraints
        ],
    }
    if intent.relationships:
        payload["relationships"] = [
            {
                "relationship_id": r.relationship_id,
                "part_id": r.part_id,
                "text": r.text,
                "to": r.to_text,
                "direction": r.direction.value,
                "restricts": r.restricts,
            }
            for r in intent.relationships
        ]
    if intent.groupings:
        payload["groupings"] = [
            {"grouping_id": g.grouping_id, "part_id": g.part_id, "axis": g.axis_text}
            for g in intent.groupings
        ]
    if intent.orderings:
        payload["orderings"] = [
            {
                "ordering_id": o.ordering_id,
                "part_id": o.part_id,
                "direction": o.direction.value,
                "basis": o.basis.value,
            }
            for o in intent.orderings
        ]
    if intent.outputs:
        payload["outputs"] = [
            {"output_id": o.output_id, "part_id": o.part_id, "text": o.text}
            for o in intent.outputs
        ]
    if intent.topic:
        payload["topic"] = intent.topic
    if intent.superseded:
        payload["superseded"] = list(intent.superseded)
    if intent.unresolved:
        payload["unresolved"] = [
            {
                "slot_id": s.slot_id,
                "kind": s.kind.value,
                "part_id": s.part_id,
                "question": s.question,
                "about": s.about_text,
                "blocking": s.blocking,
            }
            for s in intent.unresolved
        ]
    if intent.provenance:
        payload["provenance"] = [
            {"element_id": r.element_id, "turn": r.turn_index} for r in intent.provenance
        ]
    if intent.resolves_pending_clarification:
        payload["resolves_pending_clarification"] = True
    return payload
