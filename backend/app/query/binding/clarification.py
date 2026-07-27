"""The clarification gate: backend-justified, structured, persistent (task28 §6).

A clarification is only ever justified by one of two things, and the gate checks
for them rather than trusting a model-written question:

1. a BLOCKING unresolved slot in the resolved intent — information the
   conversation genuinely does not supply;
2. a requirement the backend resolved to materially different plausible
   readings that cannot safely be chosen between.

Everything else is not a question for the user. In particular, this model not
recording the requested fact is a source limitation and must be reported as an
unavailable or partial result: converting it into a question asks the user to
supply data instead of telling them the truth about their model. Ordinary
language, breadth, and a request needing several capabilities are likewise never
grounds to ask.

What survives the gate is persisted as a `PendingClarification`, so the next
turn completes the same plan rather than reparsing an answer as a new request,
and so a decision the user already supplied is never asked for twice.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.llm.schemas_v5 import ResolvedIntent, UnresolvedSlot
from app.query.binding.intent import PendingClarification
from app.query.binding.ledger_v2 import LedgerRequirement, LedgerV2, ResolutionState
from app.query.binding.phrasing import humanize_text

__all__ = [
    "ClarificationDecision",
    "decide_clarification",
]


@dataclass
class ClarificationDecision:
    """Whether to ask, what to ask, and what makes it justified."""

    justified: bool = False
    question: str = ""
    #: The structured slots the question stands on — never free-form only.
    slots: list[dict[str, Any]] = field(default_factory=list)
    #: Why an asked-for clarification was refused, for the trace.
    rejected_reason: str | None = None

    def to_pending(
        self, intent: ResolvedIntent, source_model_id: int | None
    ) -> PendingClarification | None:
        if not self.justified:
            return None
        return PendingClarification(
            question=self.question,
            slots=list(self.slots),
            normalized_request=intent.normalized_request,
            source_model_id=source_model_id,
        )

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"justified": self.justified}
        if self.slots:
            payload["slots"] = self.slots
        if self.rejected_reason:
            payload["rejected"] = self.rejected_reason
        return payload


def decide_clarification(
    intent: ResolvedIntent,
    ledger: LedgerV2,
    *,
    plan_requested: bool = False,
    plan_question: str | None = None,
    pending: PendingClarification | None = None,
) -> ClarificationDecision:
    """Verify a clarification against structured evidence (§6)."""
    slots: list[dict[str, Any]] = []

    already_answered = _already_answered_questions(pending, intent)
    for slot in intent.blocking_slots():
        if _normalize(slot.question) in already_answered:
            # The user supplied this last turn. Asking again is the repeated
            # request §6 forbids.
            continue
        slots.append(_slot_payload(slot, intent))

    for requirement in _ambiguous_requirements(ledger):
        slots.append(_ambiguity_payload(requirement))

    if not slots:
        return ClarificationDecision(
            justified=False,
            rejected_reason=(
                "a clarification was requested with no unresolved decision and no "
                "materially different reading recorded"
            )
            if plan_requested
            else None,
        )

    return ClarificationDecision(
        justified=True,
        question=_compose_question(slots, plan_question),
        slots=slots,
    )


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------


def _ambiguous_requirements(ledger: LedgerV2) -> list[LedgerRequirement]:
    """Requirements the backend itself resolved to several readings.

    Only a REQUIRED requirement counts: an optional inherited scope with more
    than one reading never blocks an answer the user can already use.
    """
    return [
        r
        for r in ledger.required()
        if r.resolution is ResolutionState.AMBIGUOUS
    ]


def _slot_payload(slot: UnresolvedSlot, intent: ResolvedIntent) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "slot_id": slot.slot_id,
        "kind": slot.kind.value,
        "question": slot.question,
        "source": "resolved_intent",
    }
    if slot.about_text:
        payload["about"] = slot.about_text
    if slot.part_id:
        payload["part_id"] = slot.part_id
    turn = intent.turn_for(slot.slot_id)
    if turn is not None:
        payload["from_turn"] = turn
    return payload


def _ambiguity_payload(requirement: LedgerRequirement) -> dict[str, Any]:
    note = humanize_text(requirement.resolution_note or "") or (
        "this model records more than one reading of it"
    )
    return {
        "slot_id": requirement.requirement_id,
        "kind": requirement.role.value,
        "question": (
            f"{requirement.source_text!r} has more than one reasonable reading here: "
            f"{note}. Which do you mean?"
        ),
        "about": requirement.source_text,
        "source": "backend_resolution",
        **({"from_intent": requirement.intent_ref} if requirement.intent_ref else {}),
    }


def _already_answered_questions(
    pending: PendingClarification | None, intent: ResolvedIntent
) -> set[str]:
    """Questions the conversation has already settled (§6).

    Two independent signals: the resolver saying this message answers the
    pending clarification, and the exact question text having been asked before.
    """
    if pending is None:
        return set()
    if intent.resolves_pending_clarification:
        return {_normalize(s.get("question", "")) for s in pending.slots} | {
            _normalize(pending.question)
        }
    return set()


def _normalize(text: str) -> str:
    return " ".join(str(text).casefold().split())


def _compose_question(slots: list[dict[str, Any]], plan_question: str | None) -> str:
    """Ask only for the smallest missing decisions, one sentence each (§6)."""
    questions = [str(s["question"]).strip() for s in slots[:2] if s.get("question")]
    if questions:
        return " ".join(questions)
    return (plan_question or "").strip() or (
        "Could you say a little more precisely what you would like from this model?"
    )
