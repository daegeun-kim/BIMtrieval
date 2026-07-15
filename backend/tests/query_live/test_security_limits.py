"""Injection resistance, unsupported operations, statement timeouts, max
limits, and read-only role enforcement (spec_v003 §7, §11, §13, §16), live."""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from app.db.session import get_engine
from app.query.sql import entities
from app.query.sql.errors import FieldNotFoundError
from app.query.sql.schemas import (
    CountEntitiesPlan,
    FieldKind,
    FieldRef,
    FilterCondition,
    FilterEntitiesPlan,
    FilterGroup,
    ListEntitiesPlan,
    Operator,
)

from .conftest import SOURCE_MODEL_ID


def test_injection_attempt_in_filter_value_is_bound_not_executed(live_session):
    """A value that looks like SQL must be treated as a literal string,
    never concatenated (spec_v003 §7: 'All values must be bound parameters')."""
    plan = FilterEntitiesPlan(
        source_model_id=SOURCE_MODEL_ID,
        filters=FilterGroup(
            bool_op="and",
            conditions=[
                FilterCondition(
                    field=FieldRef(field_kind=FieldKind.ATTRIBUTE, field_name="name"),
                    operator=Operator.EXACT,
                    value="'; DROP TABLE ifc_entities; --",
                )
            ],
        ),
    )
    rows = entities.filter_entities(live_session, plan)
    assert rows == []  # no entity literally has that name — no error, no side effect

    still_there = entities.count_entities(
        live_session, CountEntitiesPlan(source_model_id=SOURCE_MODEL_ID, entity_classes=["IfcDoor"])
    )
    assert still_there == 205  # table intact


def test_injection_attempt_in_class_name_is_bound_not_executed(live_session):
    n = entities.count_entities(
        live_session,
        CountEntitiesPlan(
            source_model_id=SOURCE_MODEL_ID,
            entity_classes=["IfcDoor'; DROP TABLE ifc_entities; --"],
        ),
    )
    assert n == 0


def test_unsupported_field_rejected_before_any_query_runs(live_session):
    plan = FilterEntitiesPlan(
        source_model_id=SOURCE_MODEL_ID,
        filters=FilterGroup(
            bool_op="and",
            conditions=[
                FilterCondition(
                    field=FieldRef(
                        field_kind=FieldKind.ATTRIBUTE, field_name="not_a_real_attribute"
                    ),
                    operator=Operator.EXACT,
                    value="x",
                )
            ],
        ),
    )
    with pytest.raises(FieldNotFoundError):
        entities.filter_entities(live_session, plan)


def test_unsupported_operation_string_rejected_by_schema():
    """The plan schema itself rejects made-up field_kind/operator values —
    this never reaches SQL compilation at all."""
    with pytest.raises(ValidationError):
        FieldRef(field_kind="not_a_real_kind", field_name="x")
    with pytest.raises(ValidationError):
        FilterCondition(
            field=FieldRef(field_kind=FieldKind.ATTRIBUTE, field_name="name"),
            operator="raw_sql_passthrough",
            value="x",
        )


def test_max_list_limit_enforced_by_schema():
    with pytest.raises(ValidationError):
        ListEntitiesPlan(source_model_id=SOURCE_MODEL_ID, limit=501)


def test_statement_timeout_is_configured_on_the_query_engine():
    engine = get_engine()
    with engine.connect() as conn:
        timeout = conn.execute(text("SHOW statement_timeout")).scalar_one()
    assert timeout != "0"


def test_read_only_role_cannot_mutate(live_session):
    """The connection used by every query.sql/* function must be read-only in
    practice, not just by convention (spec_v003 §13)."""
    with pytest.raises(ProgrammingError, match="(?i)permission denied|read-only"):
        live_session.execute(
            text(
                "INSERT INTO ifc_source_models (file_path, file_name, file_fingerprint) "
                "VALUES ('x', 'x', 'security-test-should-be-rejected')"
            )
        )
    live_session.rollback()


def test_read_only_role_cannot_create_tables(live_session):
    with pytest.raises(ProgrammingError, match="(?i)permission denied"):
        live_session.execute(text("CREATE TABLE should_not_be_creatable (id serial primary key)"))
    live_session.rollback()
