"""Runs the manually-verified benchmark cases (spec_v003 §16) against the
live query engine and checks exact counts / canonical IDs where the case
specifies them."""

from __future__ import annotations

from pathlib import Path

from evaluation.cases import load_cases
from query.graph.traversal import traverse
from query.sql import entities
from query.sql.schemas import CountEntitiesPlan, TraverseRelationshipsPlan
from sqlalchemy import text

from .conftest import SOURCE_MODEL_ID

_BENCHMARK_PATH = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "evaluation"
    / "benchmark_v002_sql_graph_cases.jsonl"
)


def test_benchmark_file_loads_and_has_cases():
    cases = load_cases(_BENCHMARK_PATH)
    assert len(cases) == 8


def test_exact_count_cases_match_live_data(live_session):
    cases = load_cases(_BENCHMARK_PATH)
    exact_count_cases = [
        c
        for c in cases
        if c.expected_answer_type == "exact_count"
        and c.expected_scope.value == "active_model"
        and not c.required_relationship_classes
    ]
    assert exact_count_cases, "expected at least one plain exact-count benchmark case"
    for case in exact_count_cases:
        entity_class = "IfcDoor" if "door" in case.question.lower() else "IfcWall"
        n = entities.count_entities(
            live_session,
            CountEntitiesPlan(source_model_id=SOURCE_MODEL_ID, entity_classes=[entity_class]),
        )
        assert n == case.expected_exact_count, case.question


def test_relationship_count_case_matches(live_session):
    cases = load_cases(_BENCHMARK_PATH)
    case = next(
        c
        for c in cases
        if c.required_relationship_classes == ["IfcRelAssignsTasks"] and c.expected_exact_count
    )
    n = live_session.execute(
        text(
            "SELECT count(*) FROM ifc_relationships "
            "WHERE source_model_id = :sid AND ifc_class = :cls"
        ),
        {"sid": SOURCE_MODEL_ID, "cls": "IfcRelAssignsTasks"},
    ).scalar_one()
    assert n == case.expected_exact_count


def test_containment_traversal_case_matches_canonical_ids(live_session):
    cases = load_cases(_BENCHMARK_PATH)
    case = next(
        c for c in cases if c.required_relationship_classes == ["IfcRelContainedInSpatialStructure"]
    )
    door_id, storey_id = case.relevant_canonical_ids
    result = traverse(
        live_session,
        TraverseRelationshipsPlan(
            source_model_id=SOURCE_MODEL_ID,
            start_entity_ids=[door_id],
            relationship_classes=["IfcRelContainedInSpatialStructure"],
            max_depth=1,
            direction="incoming",
        ),
    )
    assert result.context_entity_ids == {storey_id}


def test_property_definition_traversal_case_matches_canonical_ids(live_session):
    cases = load_cases(_BENCHMARK_PATH)
    case = next(
        c for c in cases if c.required_relationship_classes == ["IfcRelDefinesByProperties"]
    )
    door_id, pset_id = case.relevant_canonical_ids
    result = traverse(
        live_session,
        TraverseRelationshipsPlan(
            source_model_id=SOURCE_MODEL_ID,
            start_entity_ids=[door_id],
            relationship_classes=["IfcRelDefinesByProperties"],
            max_depth=1,
            direction="incoming",
        ),
    )
    assert result.context_entity_ids == {pset_id}


def test_average_door_width_case_reports_zero_coverage_honestly(live_session):
    """The benchmark records the honest answer for this dataset: DIMENSION
    'Width' doesn't resolve at all (zero populated quantity_sets), so
    resolve_field raises before any aggregate runs — a fabricated average is
    not returned."""
    import pytest
    from query.sql.errors import FieldNotFoundError
    from query.sql.schemas import AggregateEntitiesPlan, FieldKind, FieldRef

    with pytest.raises(FieldNotFoundError):
        entities.aggregate_entities(
            live_session,
            AggregateEntitiesPlan(
                source_model_id=SOURCE_MODEL_ID,
                entity_classes=["IfcDoor"],
                function="average",
                field=FieldRef(field_kind=FieldKind.DIMENSION, field_name="Width"),
                unit="mm",
            ),
        )
