"""Selected-object context: up to five compact summaries, no full canonical
JSON (spec_v004 §13), live."""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from query.rag.hydration import hydrate_selected_entities
from query.rag.schemas import RagSearchPlan

from .conftest import SOURCE_MODEL_ID

DOOR_ENTITY_ID = 627
DOOR_GLOBAL_ID = "1Uo8RaB_bDWA9BY6VlAcwo"


def test_plan_rejects_more_than_five_selected_entities():
    with pytest.raises(ValidationError):
        RagSearchPlan(
            source_model_id=SOURCE_MODEL_ID,
            semantic_query="q",
            selected_entity_ids=[1, 2, 3, 4, 5, 6],
        )


def test_hydrate_selected_entities_returns_compact_summaries(live_session):
    summaries = hydrate_selected_entities(live_session, SOURCE_MODEL_ID, [DOOR_ENTITY_ID])
    assert len(summaries) == 1
    s = summaries[0]
    assert s.entity_id == DOOR_ENTITY_ID
    assert s.global_id == DOOR_GLOBAL_ID
    assert s.ifc_class == "IfcDoor"
    # compact, not full canonical JSON
    assert not hasattr(s, "canonical_json")
    assert not hasattr(s, "property_sets")


def test_hydrate_selected_entities_skips_nonexistent_ids_gracefully(live_session):
    summaries = hydrate_selected_entities(
        live_session, SOURCE_MODEL_ID, [DOOR_ENTITY_ID, 999999999]
    )
    assert len(summaries) == 1


def test_hydrate_selected_entities_empty_list_returns_empty(live_session):
    assert hydrate_selected_entities(live_session, SOURCE_MODEL_ID, []) == []
