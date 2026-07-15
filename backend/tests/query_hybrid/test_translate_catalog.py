"""Catalog filter translation validates fields up front and coerces booleans
(task08 regression: unsupported catalog field must repair, not crash)."""

from __future__ import annotations

import pytest

from app.llm.schemas import CatalogPlan, PlanFieldRef, PlanFilter
from app.llm.translate import _catalog_filter_group, _translate_catalog
from app.llm.validation import PlanValidationError
from app.query.sql.schemas import FieldKind, Operator, SqlOperation


def _filter(field_name, op=Operator.EQ, value_text="x"):
    return PlanFilter(
        field=PlanFieldRef(field_kind=FieldKind.ATTRIBUTE, field_name=field_name),
        operator=op,
        value_text=value_text,
    )


def test_unknown_catalog_field_is_repairable_not_crash():
    with pytest.raises(PlanValidationError):
        _catalog_filter_group([_filter("no_such_column")], "and")


def test_supported_catalog_field_builds_group():
    fg = _catalog_filter_group([_filter("status", value_text="available")], "and")
    assert fg is not None
    assert fg.conditions[0].field.field_name == "status"
    assert fg.conditions[0].value == "available"


def test_is_current_is_coerced_to_boolean_eq():
    fg = _catalog_filter_group(
        [_filter("is_current", op=Operator.EXACT, value_text="current")], "and"
    )
    cond = fg.conditions[0]
    assert cond.value is True
    assert cond.operator is Operator.EQ  # forced to boolean equality


def test_is_current_false_coercion():
    fg = _catalog_filter_group([_filter("is_current", value_text="false")], "and")
    assert fg.conditions[0].value is False


def test_list_model_versions_without_family_key_falls_back_to_list_models():
    op, _typed = _translate_catalog(CatalogPlan(operation=SqlOperation.LIST_MODEL_VERSIONS))
    assert op is SqlOperation.LIST_MODELS


def test_list_model_versions_with_family_key_kept():
    op, typed = _translate_catalog(
        CatalogPlan(operation=SqlOperation.LIST_MODEL_VERSIONS, family_key="fam-1")
    )
    assert op is SqlOperation.LIST_MODEL_VERSIONS
    assert typed.family_key == "fam-1"
