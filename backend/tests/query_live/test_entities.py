"""Entity count/list/get/filter/group/aggregate + string modes + missing-value
states + exact-count-despite-limits (spec_v003 §6, §7, §9, §11), live."""

from __future__ import annotations

import pytest

from app.query.sql import entities
from app.query.sql.errors import UnknownEntityOrRelationshipError
from app.query.sql.operations import MissingValueState
from app.query.sql.schemas import (
    AggregateEntitiesPlan,
    CountEntitiesPlan,
    FieldKind,
    FieldRef,
    FilterCondition,
    FilterEntitiesPlan,
    FilterGroup,
    FindMissingValuesPlan,
    GetEntityPlan,
    GetSelectedEntitiesPlan,
    GroupEntitiesPlan,
    ListEntitiesPlan,
    Operator,
    SortSpec,
)

from .conftest import SOURCE_MODEL_ID

DOOR_ENTITY_ID = 627
DOOR_GLOBAL_ID = "1Uo8RaB_bDWA9BY6VlAcwo"
DOOR_NAME_FRAGMENT = "D2L"


def test_count_entities_exact_door_count(live_session):
    n = entities.count_entities(
        live_session, CountEntitiesPlan(source_model_id=SOURCE_MODEL_ID, entity_classes=["IfcDoor"])
    )
    assert n == 205


def test_list_entities_sorted_and_bounded(live_session):
    rows = entities.list_entities(
        live_session,
        ListEntitiesPlan(
            source_model_id=SOURCE_MODEL_ID,
            entity_classes=["IfcDoor"],
            sort=[SortSpec(field=FieldRef(field_kind=FieldKind.ATTRIBUTE, field_name="global_id"))],
            limit=3,
        ),
    )
    assert len(rows) == 3
    global_ids = [r.global_id for r in rows]
    assert global_ids == sorted(global_ids)


def test_get_entity_by_global_id(live_session):
    row = entities.get_entity(
        live_session, GetEntityPlan(source_model_id=SOURCE_MODEL_ID, global_id=DOOR_GLOBAL_ID)
    )
    assert row.id == DOOR_ENTITY_ID
    assert row.ifc_class == "IfcDoor"


def test_get_entity_by_id(live_session):
    row = entities.get_entity(
        live_session, GetEntityPlan(source_model_id=SOURCE_MODEL_ID, entity_id=DOOR_ENTITY_ID)
    )
    assert row.global_id == DOOR_GLOBAL_ID


def test_get_entity_not_found_raises(live_session):
    with pytest.raises(UnknownEntityOrRelationshipError):
        entities.get_entity(
            live_session, GetEntityPlan(source_model_id=SOURCE_MODEL_ID, entity_id=999999999)
        )


def test_get_selected_entities(live_session):
    rows = entities.get_selected_entities(
        live_session,
        GetSelectedEntitiesPlan(source_model_id=SOURCE_MODEL_ID, entity_ids=[DOOR_ENTITY_ID]),
    )
    assert len(rows) == 1
    assert rows[0].global_id == DOOR_GLOBAL_ID


class TestStringMatchModes:
    """spec_v003 §7 — all five required string modes, verified against a real name."""

    def _filter(self, operator: Operator, value):
        return FilterEntitiesPlan(
            source_model_id=SOURCE_MODEL_ID,
            entity_classes=["IfcDoor"],
            filters=FilterGroup(
                bool_op="and",
                conditions=[
                    FilterCondition(
                        field=FieldRef(field_kind=FieldKind.ATTRIBUTE, field_name="name"),
                        operator=operator,
                        value=value,
                    )
                ],
            ),
        )

    def test_exact(self, live_session):
        rows = entities.filter_entities(live_session, self._filter(Operator.EXACT, "D2L_(#219684)"))
        assert {r.id for r in rows} == {DOOR_ENTITY_ID}

    def test_exact_is_case_sensitive(self, live_session):
        rows = entities.filter_entities(live_session, self._filter(Operator.EXACT, "d2l_(#219684)"))
        assert rows == []

    def test_case_insensitive_exact(self, live_session):
        rows = entities.filter_entities(
            live_session, self._filter(Operator.CASE_INSENSITIVE_EXACT, "d2l_(#219684)")
        )
        assert {r.id for r in rows} == {DOOR_ENTITY_ID}

    def test_contains(self, live_session):
        rows = entities.filter_entities(
            live_session, self._filter(Operator.CONTAINS, DOOR_NAME_FRAGMENT)
        )
        assert DOOR_ENTITY_ID in {r.id for r in rows}

    def test_starts_with(self, live_session):
        rows = entities.filter_entities(live_session, self._filter(Operator.STARTS_WITH, "D2L"))
        assert DOOR_ENTITY_ID in {r.id for r in rows}
        rows_no_match = entities.filter_entities(
            live_session, self._filter(Operator.STARTS_WITH, "2L")
        )
        assert DOOR_ENTITY_ID not in {r.id for r in rows_no_match}

    def test_in(self, live_session):
        rows = entities.filter_entities(
            live_session, self._filter(Operator.IN, ["D2L_(#219684)", "nonexistent-name"])
        )
        assert {r.id for r in rows} == {DOOR_ENTITY_ID}


def test_aggregate_count(live_session):
    result = entities.aggregate_entities(
        live_session,
        AggregateEntitiesPlan(
            source_model_id=SOURCE_MODEL_ID, entity_classes=["IfcDoor"], function="count"
        ),
    )
    assert result.value == 205
    assert result.matched_count == 205
    assert result.coverage_count == 205
    assert result.warnings == []


def test_group_entities_by_ifc_class_matches_known_counts(live_session):
    buckets = entities.group_entities(
        live_session,
        GroupEntitiesPlan(
            source_model_id=SOURCE_MODEL_ID,
            group_by_field=FieldRef(field_kind=FieldKind.ATTRIBUTE, field_name="ifc_class"),
            function="count",
            limit=25,
        ),
    )
    by_key = {b.key: b.count for b in buckets}
    assert by_key["IfcDoor"] == 205
    assert by_key["IfcWall"] == 648
    assert sum(by_key.values()) == 6989  # matches ifc_entities total


class TestMissingValueStates:
    """spec_v003 §9 — never collapsed into one generic null."""

    def test_description_is_absent_for_all_doors(self, live_session):
        report = entities.find_missing_values(
            live_session,
            FindMissingValuesPlan(
                source_model_id=SOURCE_MODEL_ID,
                entity_classes=["IfcDoor"],
                field=FieldRef(field_kind=FieldKind.ATTRIBUTE, field_name="description"),
                limit=5,
            ),
        )
        assert report.matched_count == 205
        assert report.state_counts == {MissingValueState.ABSENT.value: 205}
        assert len(report.example_ids[MissingValueState.ABSENT.value]) == 5

    def test_name_is_present_for_all_doors(self, live_session):
        report = entities.find_missing_values(
            live_session,
            FindMissingValuesPlan(
                source_model_id=SOURCE_MODEL_ID,
                entity_classes=["IfcDoor"],
                field=FieldRef(field_kind=FieldKind.ATTRIBUTE, field_name="name"),
                limit=5,
            ),
        )
        assert report.matched_count == 205
        # not one of the 5 missing states -> excluded from state_counts entirely
        assert sum(report.state_counts.values()) == 0


def test_exact_count_holds_despite_returned_row_limit(live_session):
    """spec_v003 §11: exact counts/aggregates cover the full matching set even
    when returned example rows are bounded."""
    exact = entities.count_entities(
        live_session, CountEntitiesPlan(source_model_id=SOURCE_MODEL_ID, entity_classes=["IfcDoor"])
    )
    limited_rows = entities.list_entities(
        live_session,
        ListEntitiesPlan(source_model_id=SOURCE_MODEL_ID, entity_classes=["IfcDoor"], limit=5),
    )
    assert exact == 205
    assert len(limited_rows) == 5
    assert exact > len(limited_rows)
