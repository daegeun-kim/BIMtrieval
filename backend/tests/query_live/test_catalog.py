"""Model catalog list/filter/version/rank operations (spec_v003 §5, §6),
live against the read-only role."""

from __future__ import annotations

from app.query.sql import catalog
from app.query.sql.schemas import (
    FieldKind,
    FieldRef,
    FilterCondition,
    FilterGroup,
    FilterModelsPlan,
    GetModelMetadataPlan,
    ListModelsPlan,
    ListModelVersionsPlan,
    Operator,
    RankModelsByEntityCountPlan,
)
from app.shared.errors import ModelNotFoundError

from .conftest import SOURCE_MODEL_ID


def test_list_models_returns_seeded_catalog_entry(live_session):
    rows = catalog.list_models(live_session, ListModelsPlan(limit=50))
    ids = [r.source_model_id for r in rows]
    assert SOURCE_MODEL_ID in ids
    row = next(r for r in rows if r.source_model_id == SOURCE_MODEL_ID)
    assert row.status == "available"
    assert row.is_current is True
    # not invented — left null per user decision (tasks/task05.md item 14)
    assert row.project_type is None
    assert row.discipline is None
    assert row.description is None


def test_get_model_metadata(live_session):
    row = catalog.get_model_metadata(
        live_session, GetModelMetadataPlan(source_model_id=SOURCE_MODEL_ID)
    )
    assert row.ifc_schema == "IFC2X3"
    assert row.version_label == "v1"


def test_get_model_metadata_unknown_model_raises(live_session):
    import pytest

    with pytest.raises(ModelNotFoundError):
        catalog.get_model_metadata(live_session, GetModelMetadataPlan(source_model_id=999999))


def test_rank_models_by_entity_count_matches_exact_door_count(live_session):
    ranked = catalog.rank_models_by_entity_count(
        live_session, RankModelsByEntityCountPlan(entity_class="IfcDoor")
    )
    row = next(r for r in ranked if r.source_model_id == SOURCE_MODEL_ID)
    assert (
        row.entity_count == 205
    )  # manually verified: SELECT count(*) FROM ifc_entities WHERE ifc_class='IfcDoor'


def test_list_model_versions_for_the_seeded_family(live_session):
    versions = catalog.list_model_versions(
        live_session, ListModelVersionsPlan(family_key="ifc_schependomlaan_incl_planningsdata")
    )
    assert len(versions) == 1
    assert versions[0].version_order == 1


def test_filter_models_by_status(live_session):
    rows = catalog.filter_models(
        live_session,
        FilterModelsPlan(
            filters=FilterGroup(
                bool_op="and",
                conditions=[
                    FilterCondition(
                        field=FieldRef(field_kind=FieldKind.ATTRIBUTE, field_name="status"),
                        operator=Operator.EQ,
                        value="available",
                    )
                ],
            )
        ),
    )
    assert any(r.source_model_id == SOURCE_MODEL_ID for r in rows)


def test_filter_models_no_match(live_session):
    rows = catalog.filter_models(
        live_session,
        FilterModelsPlan(
            filters=FilterGroup(
                bool_op="and",
                conditions=[
                    FilterCondition(
                        field=FieldRef(field_kind=FieldKind.ATTRIBUTE, field_name="status"),
                        operator=Operator.EQ,
                        value="unavailable",
                    )
                ],
            )
        ),
    )
    assert rows == []
