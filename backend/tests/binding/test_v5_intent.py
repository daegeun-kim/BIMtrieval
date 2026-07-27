"""task28 §Validation — the semantic planning boundary, offline.

Conversation serialization, resolved-intent parsing and provenance, the
resolver's user-meaning contract, ledger subordination, and pending
clarification across turns.

Fixtures are neutral and synthetic: no benchmark question, expected answer, IFC
filename, semantic ID, or model fact appears here.
"""

from __future__ import annotations

from app.llm.schemas_v5 import (
    ConstraintKind,
    IntentConstraint,
    IntentOperation,
    IntentPart,
    IntentProvenance,
    IntentTarget,
    ResolvedIntent,
    UnresolvedKind,
    UnresolvedSlot,
    VisualizationIntent,
)
from app.query.binding.clarification import decide_clarification
from app.query.binding.intent import (
    PendingClarification,
    build_intent_context,
    deterministic_intent,
    intent_payload,
    repair_intent,
    sanitize_intent,
    serialize_conversation,
)
from app.query.binding.ledger_v2 import ResolutionState
from app.query.binding.obligations import build_obligations, build_recall_ledger


def _turns(*contents: str) -> list[dict[str, str]]:
    return [
        {"role": "user" if index % 2 == 0 else "assistant", "content": text}
        for index, text in enumerate(contents)
    ]


def _intent(**overrides) -> ResolvedIntent:
    base = {
        "normalized_request": "count the fixtures of the chosen kind",
        "language": "en",
        "topic": "fixtures",
        "parts": [
            IntentPart(
                part_id="P1",
                request_text="count the fixtures of the chosen kind",
                operation=IntentOperation.COUNT,
                highlightable=True,
            )
        ],
        "targets": [IntentTarget(target_id="T1", part_id="P1", text="fixtures")],
        "visualization": VisualizationIntent.PRIMARY_ONLY,
    }
    base.update(overrides)
    return ResolvedIntent(**base)


# ---------------------------------------------------------------------------
# §2 — the complete conversation reaches the resolver
# ---------------------------------------------------------------------------


def test_every_turn_is_serialized_in_original_order():
    history = _turns(*[f"turn number {n}" for n in range(30)])
    conversation = serialize_conversation("the newest question", history)

    # 30 history turns plus the current message — no 20-turn window.
    assert len(conversation.turns) == 31
    assert [t.turn_index for t in conversation.turns] == list(range(31))
    assert conversation.turns[-1].content == "the newest question"
    assert conversation.turns[0].content == "turn number 0"
    assert conversation.omitted_turns == 0


def test_long_messages_are_not_truncated():
    long_message = "detail " * 400  # far past the retired 400-character cut
    conversation = serialize_conversation("and now?", _turns(long_message))

    assert conversation.turns[0].content == long_message.strip()
    assert len(conversation.turns[0].content) > 2000


def test_a_provider_hard_limit_is_recorded_and_never_silent():
    history = _turns(*[f"{'x' * 400} turn {n}" for n in range(20)])
    conversation = serialize_conversation("the newest question", history, char_limit=1200)

    assert conversation.omitted_turns > 0
    assert conversation.omission_reason and "provider limit" in conversation.omission_reason
    # The current message is never the turn that gets dropped.
    assert conversation.turns[-1].content == "the newest question"
    assert conversation.diagnostics()["omitted_turns"] == conversation.omitted_turns


def test_resolver_input_carries_no_backend_universe():
    conversation = serialize_conversation("a question", _turns("earlier"))
    context = build_intent_context(
        conversation, source_model_id=7, model_label="a model", selected_object_count=2
    )

    assert "projection_json" not in context
    payload = context["payload"]
    assert len(payload["conversation"]) == 2
    assert payload["session_state"]["active_model_loaded"] is True
    assert payload["session_state"]["objects_selected_in_viewer"] == 2


# ---------------------------------------------------------------------------
# §2 — structured intent, provenance, and the user-meaning contract
# ---------------------------------------------------------------------------


def test_intent_payload_preserves_parts_constraints_and_provenance():
    intent = _intent(
        constraints=[
            IntentConstraint(
                constraint_id="C1",
                part_id="P1",
                text="of the chosen kind",
                kind=ConstraintKind.ATTRIBUTE,
            )
        ],
        provenance=[
            IntentProvenance(element_id="P1", turn_index=2),
            IntentProvenance(element_id="C1", turn_index=0),
        ],
    )
    payload = intent_payload(intent)

    assert payload["request"] == intent.normalized_request
    assert payload["targets"][0]["text"] == "fixtures"
    assert payload["constraints"][0]["constraint_id"] == "C1"
    assert {p["element_id"]: p["turn"] for p in payload["provenance"]} == {"P1": 2, "C1": 0}
    # The carried-forward constraint is traceable to the earlier turn.
    assert intent.turn_for("C1") == 0


def test_invented_backend_identifiers_are_contract_violations():
    conversation = serialize_conversation("count the fixtures", [])
    intent = _intent(
        parts=[
            IntentPart(
                part_id="P1",
                request_text="count the fixtures",
                operation=IntentOperation.COUNT,
            )
        ],
        targets=[IntentTarget(target_id="T1", part_id="P1", text="cls:SomeClass")],
    )

    violations = sanitize_intent(intent, conversation)

    assert violations and "backend identifier" in violations[0]


def test_terms_the_user_actually_typed_are_not_violations():
    conversation = serialize_conversation("how many IfcThing objects are there?", [])
    intent = _intent(
        parts=[
            IntentPart(
                part_id="P1",
                request_text="how many IfcThing objects are there?",
                operation=IntentOperation.COUNT,
            )
        ],
        targets=[IntentTarget(target_id="T1", part_id="P1", text="IfcThing")],
    )

    assert sanitize_intent(intent, conversation) == []


def test_repair_reattaches_an_orphaned_constraint_instead_of_dropping_it():
    conversation = serialize_conversation("a question", [])
    intent = _intent(
        constraints=[
            IntentConstraint(
                constraint_id="C1",
                part_id="P9",
                text="a condition the user stated",
                kind=ConstraintKind.ATTRIBUTE,
            )
        ]
    )

    repair_intent(intent, conversation)

    # Repaired, never deleted: a dropped condition is the defect, not the fix.
    assert len(intent.constraints) == 1
    assert intent.constraints[0].part_id == "P1"


def test_deterministic_intent_preserves_the_message_verbatim():
    conversation = serialize_conversation("an unusual request", [])
    intent = deterministic_intent("an unusual request", conversation)

    assert intent.normalized_request == "an unusual request"
    assert intent.targets[0].text == "an unusual request"
    assert intent.constraints == []


# ---------------------------------------------------------------------------
# §6 — clarification is justified, structured, and not repeated
# ---------------------------------------------------------------------------


def _blocking_slot() -> UnresolvedSlot:
    return UnresolvedSlot(
        slot_id="S1",
        kind=UnresolvedKind.CONSTRAINT,
        part_id="P1",
        question="Which of the two recorded meanings did you have in mind?",
        about_text="the chosen kind",
    )


def test_a_blocking_slot_justifies_a_clarification():
    intent = _intent(unresolved=[_blocking_slot()])
    decision = decide_clarification(intent, _ledger(intent))

    assert decision.justified
    assert decision.slots[0]["slot_id"] == "S1"
    assert decision.question == _blocking_slot().question


def test_a_model_written_question_with_no_unresolved_slot_is_refused():
    intent = _intent()
    decision = decide_clarification(
        intent,
        _ledger(intent),
        plan_requested=True,
        plan_question="Could you be more specific?",
    )

    assert not decision.justified
    assert decision.rejected_reason


def test_a_backend_ambiguity_justifies_a_clarification():
    intent = _intent(
        constraints=[
            IntentConstraint(
                constraint_id="C1",
                part_id="P1",
                text="on the uppermost usable level",
                kind=ConstraintKind.SPATIAL,
            )
        ]
    )
    ledger = _ledger(intent)
    requirement = ledger.for_intent("C1")[0]
    requirement.resolution = ResolutionState.AMBIGUOUS
    requirement.resolution_note = "two recorded levels could be the uppermost usable one"

    decision = decide_clarification(intent, ledger)

    assert decision.justified
    assert decision.slots[0]["source"] == "backend_resolution"
    assert decision.slots[0]["from_intent"] == "C1"


def test_a_settled_clarification_is_not_asked_again():
    pending = PendingClarification(
        question=_blocking_slot().question,
        slots=[{"slot_id": "S1", "question": _blocking_slot().question}],
        normalized_request="count the fixtures of the chosen kind",
        source_model_id=1,
    )
    # The next turn answers it, and the resolver says so.
    intent = _intent(
        unresolved=[_blocking_slot()], resolves_pending_clarification=True
    )

    decision = decide_clarification(
        intent, _ledger(intent), pending=pending
    )

    assert not decision.justified


def test_a_justified_clarification_persists_the_blocked_request():
    intent = _intent(unresolved=[_blocking_slot()])
    decision = decide_clarification(intent, _ledger(intent))
    pending = decision.to_pending(intent, source_model_id=3)

    assert pending is not None
    assert pending.normalized_request == intent.normalized_request
    assert pending.matches_model(3)
    assert not pending.matches_model(4)


def _ledger(intent):
    """The recall ledger a resolved intent produces, for clarification tests."""
    return build_recall_ledger(build_obligations(intent), intent.normalized_request)
