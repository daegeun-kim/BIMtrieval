"""Viewer actions always produce a stable shape (spec_v002 Section 17,
tasks/task04.md required verification)."""

from __future__ import annotations

from app.viewer.actions import (
    ModelAction,
    SelectionAction,
    ViewerRole,
    build_default_viewer_actions,
    build_viewer_actions,
)


def test_default_shape_has_both_role_groups_present_but_empty():
    actions = build_default_viewer_actions()
    dump = actions.model_dump()

    assert set(dump.keys()) == {
        "model_action",
        "selection_action",
        "primary_global_ids",
        "context_global_ids",
        "role_groups",
        "load_model_id",
        "viewer_source_location",
    }
    assert dump["model_action"] == ModelAction.KEEP_CURRENT.value
    assert dump["selection_action"] == SelectionAction.NONE.value
    assert dump["primary_global_ids"] == []
    assert dump["context_global_ids"] == []
    roles = {rg["role"] for rg in dump["role_groups"]}
    assert roles == {ViewerRole.PRIMARY_MATCH.value, ViewerRole.RELATIONSHIP_CONTEXT.value}


def test_populated_result_keeps_same_shape():
    actions = build_viewer_actions(
        model_action=ModelAction.KEEP_CURRENT,
        selection_action=SelectionAction.SELECT_AND_FIT,
        primary_global_ids=["GID-1", "GID-2"],
        context_global_ids=["GID-3"],
    )
    dump = actions.model_dump()

    assert set(dump.keys()) == set(build_default_viewer_actions().model_dump().keys())
    assert len(dump["role_groups"]) == 2
    primary_group = next(rg for rg in dump["role_groups"] if rg["role"] == "primary_match")
    context_group = next(rg for rg in dump["role_groups"] if rg["role"] == "relationship_context")
    assert primary_group["global_ids"] == ["GID-1", "GID-2"]
    assert context_group["global_ids"] == ["GID-3"]
