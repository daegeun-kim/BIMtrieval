"""Session store/reset and stable viewer-action contract (spec_v005 §12, §13, §14)."""

from __future__ import annotations

from query.session import SessionStore, reset
from shared.types import QueryScope
from viewer.actions import (
    ModelAction,
    SelectionAction,
    build_await_confirmation_actions,
    build_default_viewer_actions,
    build_load_model_actions,
    build_viewer_actions,
)


def test_store_get_or_create_is_stable():
    store = SessionStore()
    a = store.get_or_create("s1")
    b = store.get_or_create("s1")
    assert a is b
    assert a.session_id == "s1"


def test_reset_clears_all_session_state():
    store = SessionStore()
    state = store.get_or_create("s2")
    state.active_source_model_id = 1
    state.mode = QueryScope.ACTIVE_MODEL
    state.last_primary_entity_ids = [1, 2, 3]
    state.pending_candidate_model_ids = [1]
    store.save(state)

    fresh = store.reset("s2")
    assert fresh.active_source_model_id is None
    assert fresh.last_primary_entity_ids == []
    assert fresh.pending_candidate_model_ids == []
    assert fresh.mode is QueryScope.MODEL_CATALOG
    # same id, brand-new state object (nothing persistent referenced)
    assert fresh.session_id == "s2"


def test_reset_function_preserves_only_session_id():
    from query.session import SessionState

    s = SessionState(session_id="x", active_source_model_id=9, last_primary_entity_ids=[7])
    fresh = reset(s)
    assert fresh.session_id == "x"
    assert fresh.active_source_model_id is None
    assert fresh.last_primary_entity_ids == []


def test_default_viewer_action_is_stable_no_op():
    v = build_default_viewer_actions()
    assert v.model_action is ModelAction.KEEP_CURRENT
    assert v.selection_action is SelectionAction.NONE
    # both role groups always present (stable shape)
    assert [g.role.value for g in v.role_groups] == ["primary_match", "relationship_context"]


def test_await_confirmation_action():
    v = build_await_confirmation_actions()
    assert v.model_action is ModelAction.AWAIT_USER_CONFIRMATION


def test_load_model_action_carries_source():
    v = build_load_model_actions(1, "/path/to/model.ifc")
    assert v.model_action is ModelAction.LOAD_MODEL
    assert v.load_model_id == 1
    assert v.viewer_source_location == "/path/to/model.ifc"
    assert v.selection_action is SelectionAction.CLEAR


def test_select_and_fit_shape():
    v = build_viewer_actions(
        selection_action=SelectionAction.SELECT_AND_FIT,
        primary_global_ids=["a", "b"],
        context_global_ids=["c"],
    )
    assert v.primary_global_ids == ["a", "b"]
    assert v.role_groups[0].global_ids == ["a", "b"]
    assert v.role_groups[1].global_ids == ["c"]
