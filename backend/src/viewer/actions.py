"""Viewer-action schema and builder (spec_v002 Section 17).

The backend supplies semantic roles and IFC GlobalIds only — never camera
coordinates or Three.js control. `build_viewer_actions()` always returns
every field (both role groups included, even when empty) so the frontend can
rely on one stable shape regardless of which route produced the result
(tasks/task04.md required verification: "Viewer action schemas always
produce a stable shape").
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class ModelAction(str, Enum):
    KEEP_CURRENT = "keep_current"
    # Catalog produced candidates; the frontend must wait for a user click
    # before loading a (potentially large) model (spec_v005 §13).
    AWAIT_USER_CONFIRMATION = "await_user_confirmation"
    LOAD_MODEL = "load_model"


class SelectionAction(str, Enum):
    SELECT_AND_FIT = "select_and_fit"
    SELECT_ONLY = "select_only"
    CLEAR = "clear"
    NONE = "none"


class ViewerRole(str, Enum):
    PRIMARY_MATCH = "primary_match"
    RELATIONSHIP_CONTEXT = "relationship_context"


class RoleGroup(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: ViewerRole
    global_ids: list[str] = Field(default_factory=list)


class ViewerActions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_action: ModelAction = ModelAction.KEEP_CURRENT
    selection_action: SelectionAction = SelectionAction.NONE
    primary_global_ids: list[str] = Field(default_factory=list)
    context_global_ids: list[str] = Field(default_factory=list)
    role_groups: list[RoleGroup] = Field(default_factory=list)
    # Populated only when model_action == load_model, after user confirmation
    # (spec_v005 §13): the viewer source the frontend should load.
    load_model_id: int | None = None
    viewer_source_location: str | None = None


def build_viewer_actions(
    *,
    model_action: ModelAction = ModelAction.KEEP_CURRENT,
    selection_action: SelectionAction = SelectionAction.NONE,
    primary_global_ids: list[str] | None = None,
    context_global_ids: list[str] | None = None,
    load_model_id: int | None = None,
    viewer_source_location: str | None = None,
) -> ViewerActions:
    """Build a stable ViewerActions payload.

    Always emits both role groups (primary_match, relationship_context),
    even when a list is empty, so the frontend never has to branch on
    whether a role group is present.
    """
    primary_global_ids = primary_global_ids or []
    context_global_ids = context_global_ids or []
    return ViewerActions(
        model_action=model_action,
        selection_action=selection_action,
        primary_global_ids=primary_global_ids,
        context_global_ids=context_global_ids,
        role_groups=[
            RoleGroup(role=ViewerRole.PRIMARY_MATCH, global_ids=primary_global_ids),
            RoleGroup(role=ViewerRole.RELATIONSHIP_CONTEXT, global_ids=context_global_ids),
        ],
        load_model_id=load_model_id,
        viewer_source_location=viewer_source_location,
    )


def build_await_confirmation_actions() -> ViewerActions:
    """Catalog results: do not auto-load; wait for a user click (spec_v005 §13)."""
    return build_viewer_actions(model_action=ModelAction.AWAIT_USER_CONFIRMATION)


def build_load_model_actions(
    load_model_id: int, viewer_source_location: str | None
) -> ViewerActions:
    """User confirmed a catalog candidate: instruct the frontend to load it."""
    return build_viewer_actions(
        model_action=ModelAction.LOAD_MODEL,
        selection_action=SelectionAction.CLEAR,
        load_model_id=load_model_id,
        viewer_source_location=viewer_source_location,
    )


def build_default_viewer_actions() -> ViewerActions:
    """No-op viewer action: no selection, keep current model (spec_v005 §14)."""
    return build_viewer_actions()
