"""Pure Pydantic validation for the typed SQL/catalog plan schemas
(spec_v003 §6, §7). No database access."""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from query.sql.operations import PLAN_BY_OPERATION, MissingValueState
from query.sql.schemas import (
    AggregateEntitiesPlan,
    CountEntitiesPlan,
    FieldKind,
    FieldRef,
    FilterCondition,
    FilterEntitiesPlan,
    FilterGroup,
    FindMissingValuesPlan,
    GetEntityPlan,
    GetRelationshipPlan,
    GroupEntitiesPlan,
    ListEntitiesPlan,
    Operator,
    SqlOperation,
    TraverseRelationshipsPlan,
)


def test_all_17_operations_registered():
    assert len(PLAN_BY_OPERATION) == 17
    assert set(PLAN_BY_OPERATION.keys()) == set(SqlOperation)


def test_missing_value_states_are_five():
    assert len(list(MissingValueState)) == 5


class TestFieldRef:
    def test_attribute_field_forbids_set_name(self):
        with pytest.raises(ValidationError):
            FieldRef(field_kind=FieldKind.ATTRIBUTE, set_name="x", field_name="name")

    def test_property_field_requires_set_name(self):
        with pytest.raises(ValidationError):
            FieldRef(field_kind=FieldKind.PROPERTY, field_name="Width")

    def test_quantity_field_requires_set_name(self):
        with pytest.raises(ValidationError):
            FieldRef(field_kind=FieldKind.QUANTITY, field_name="Width")

    def test_dimension_field_forbids_set_name(self):
        with pytest.raises(ValidationError):
            FieldRef(field_kind=FieldKind.DIMENSION, set_name="BaseQuantities", field_name="Width")


class TestFilterConditionValueShape:
    def test_between_requires_two_element_list(self):
        field = FieldRef(field_kind=FieldKind.ATTRIBUTE, field_name="name")
        with pytest.raises(ValidationError):
            FilterCondition(field=field, operator=Operator.BETWEEN, value=1)
        with pytest.raises(ValidationError):
            FilterCondition(field=field, operator=Operator.BETWEEN, value=[1, 2, 3])
        FilterCondition(field=field, operator=Operator.BETWEEN, value=[1, 2])  # ok

    def test_in_requires_nonempty_bounded_list(self):
        field = FieldRef(field_kind=FieldKind.ATTRIBUTE, field_name="ifc_class")
        with pytest.raises(ValidationError):
            FilterCondition(field=field, operator=Operator.IN, value=[])
        with pytest.raises(ValidationError):
            FilterCondition(field=field, operator=Operator.IN, value="IfcDoor")
        FilterCondition(field=field, operator=Operator.IN, value=["IfcDoor", "IfcWindow"])  # ok

    def test_scalar_operator_rejects_list_value(self):
        field = FieldRef(field_kind=FieldKind.ATTRIBUTE, field_name="ifc_class")
        with pytest.raises(ValidationError):
            FilterCondition(field=field, operator=Operator.EQ, value=[1, 2])

    def test_string_mode_requires_string_value(self):
        field = FieldRef(field_kind=FieldKind.ATTRIBUTE, field_name="name")
        with pytest.raises(ValidationError):
            FilterCondition(field=field, operator=Operator.CONTAINS, value=42)

    def test_all_five_string_modes_accepted(self):
        field = FieldRef(field_kind=FieldKind.ATTRIBUTE, field_name="name")
        for op in (
            Operator.EXACT,
            Operator.CASE_INSENSITIVE_EXACT,
            Operator.CONTAINS,
            Operator.STARTS_WITH,
        ):
            FilterCondition(field=field, operator=op, value="Door")
        FilterCondition(field=field, operator=Operator.IN, value=["Door", "Window"])


class TestFilterGroupBounds:
    def _condition(self, name: str = "name") -> FilterCondition:
        return FilterCondition(
            field=FieldRef(field_kind=FieldKind.ATTRIBUTE, field_name=name),
            operator=Operator.EXACT,
            value="x",
        )

    def test_rejects_too_many_conditions(self):
        with pytest.raises(ValidationError):
            FilterGroup(bool_op="and", conditions=[self._condition() for _ in range(21)])

    def test_rejects_excess_depth(self):
        # depth 4 nested groups (max is 3)
        inner = FilterGroup(bool_op="and", conditions=[self._condition()])
        depth2 = FilterGroup(bool_op="and", conditions=[inner])
        depth3 = FilterGroup(bool_op="and", conditions=[depth2])
        with pytest.raises(ValidationError):
            FilterGroup(bool_op="and", conditions=[depth3])

    def test_accepts_depth_within_bound(self):
        inner = FilterGroup(bool_op="or", conditions=[self._condition("a"), self._condition("b")])
        outer = FilterGroup(bool_op="and", conditions=[self._condition("c"), inner])
        assert outer.bool_op == "and"


class TestOperationPlanValidators:
    def test_get_entity_requires_exactly_one_id(self):
        with pytest.raises(ValidationError):
            GetEntityPlan(source_model_id=1)
        with pytest.raises(ValidationError):
            GetEntityPlan(source_model_id=1, entity_id=1, global_id="x")
        GetEntityPlan(source_model_id=1, entity_id=1)
        GetEntityPlan(source_model_id=1, global_id="x")

    def test_get_relationship_requires_exactly_one_id(self):
        with pytest.raises(ValidationError):
            GetRelationshipPlan(source_model_id=1)

    def test_aggregate_requires_field_unless_count(self):
        with pytest.raises(ValidationError):
            AggregateEntitiesPlan(source_model_id=1, function="sum")
        AggregateEntitiesPlan(source_model_id=1, function="count")

    def test_group_requires_aggregate_field_unless_count(self):
        group_field = FieldRef(field_kind=FieldKind.ATTRIBUTE, field_name="ifc_class")
        with pytest.raises(ValidationError):
            GroupEntitiesPlan(source_model_id=1, group_by_field=group_field, function="average")
        GroupEntitiesPlan(source_model_id=1, group_by_field=group_field, function="count")

    def test_filter_entities_requires_filters(self):
        with pytest.raises(ValidationError):
            FilterEntitiesPlan(source_model_id=1, filters=None)

    def test_list_entities_filters_optional(self):
        ListEntitiesPlan(source_model_id=1)

    def test_limits_bounded(self):
        with pytest.raises(ValidationError):
            ListEntitiesPlan(source_model_id=1, limit=501)
        with pytest.raises(ValidationError):
            ListEntitiesPlan(source_model_id=1, limit=0)
        ListEntitiesPlan(source_model_id=1, limit=500)

    def test_traversal_depth_bounded(self):
        with pytest.raises(ValidationError):
            TraverseRelationshipsPlan(source_model_id=1, start_entity_ids=[1], max_depth=4)
        TraverseRelationshipsPlan(source_model_id=1, start_entity_ids=[1], max_depth=3)

    def test_extra_fields_rejected_everywhere(self):
        with pytest.raises(ValidationError):
            CountEntitiesPlan(source_model_id=1, raw_sql="DROP TABLE ifc_entities")
        with pytest.raises(ValidationError):
            FindMissingValuesPlan(
                source_model_id=1,
                field=FieldRef(field_kind=FieldKind.ATTRIBUTE, field_name="name"),
                unexpected="x",
            )
