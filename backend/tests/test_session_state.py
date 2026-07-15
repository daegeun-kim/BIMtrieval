"""reset() clears session state but never touches persistent data
(spec_v002 Section 15, tasks/task04.md required verification)."""

from __future__ import annotations

from app.query.session import ChatMessage, SessionState, reset
from app.shared.types import QueryScope


def test_reset_clears_chat_and_selection_but_keeps_session_id():
    state = SessionState(
        session_id="sess-1",
        mode=QueryScope.ACTIVE_MODEL,
        active_source_model_id=1,
        chat_history=[ChatMessage(role="user", content="How many doors?")],
        selected_entity_ids=[101, 102],
        last_primary_entity_ids=[1, 2, 3],
        pending_candidate_model_ids=[1],
    )

    fresh = reset(state)

    assert fresh.session_id == "sess-1"
    assert fresh.mode is QueryScope.MODEL_CATALOG
    assert fresh.active_source_model_id is None
    assert fresh.chat_history == []
    assert fresh.selected_entity_ids == []
    assert fresh.last_primary_entity_ids == []
    assert fresh.pending_candidate_model_ids == []


def test_selected_entity_ids_capped_at_five():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        SessionState(session_id="s1", selected_entity_ids=[1, 2, 3, 4, 5, 6])
