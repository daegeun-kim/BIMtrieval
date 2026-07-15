"""Typed, allowlisted SQL/catalog plan schemas (spec_v003 §6, §7, §11, §12).

These are the *real* per-operation validated plans — distinct from the
generic `llm.schemas.SqlPlan`/`CatalogPlan` shells built in Task 04, which
remain the LLM-facing envelope for a future planner (v005). Task 05 is
validated by constructing these typed plans directly.

Every model is `extra="forbid"`. `FilterCondition`/`FilterGroup` form a
bounded expression tree (max depth 3, max 20 conditions total) so a plan can
never encode unbounded Boolean logic.
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

MAX_FILTER_CONDITIONS = 20
MAX_FILTER_DEPTH = 3
DEFAULT_LIST_LIMIT = 50
MAX_LIST_LIMIT = 500
DEFAULT_TRAVERSAL_DEPTH = 1
MAX_TRAVERSAL_DEPTH = 3


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SqlOperation(str, Enum):
    """spec_v003 §6 operation vocabulary."""

    LIST_MODELS = "list_models"
    FILTER_MODELS = "filter_models"
    LIST_MODEL_VERSIONS = "list_model_versions"
    RANK_MODELS_BY_ENTITY_COUNT = "rank_models_by_entity_count"
    GET_MODEL_METADATA = "get_model_metadata"
    COUNT_ENTITIES = "count_entities"
    LIST_ENTITIES = "list_entities"
    GET_ENTITY = "get_entity"
    FILTER_ENTITIES = "filter_entities"
    AGGREGATE_ENTITIES = "aggregate_entities"
    GROUP_ENTITIES = "group_entities"
    FIND_MISSING_VALUES = "find_missing_values"
    LIST_RELATIONSHIPS = "list_relationships"
    GET_RELATIONSHIP = "get_relationship"
    GET_RELATIONSHIP_MEMBERS = "get_relationship_members"
    TRAVERSE_RELATIONSHIPS = "traverse_relationships"
    GET_SELECTED_ENTITIES = "get_selected_entities"


class FieldKind(str, Enum):
    """spec_v003 §8 — where a field concept may resolve to."""

    ATTRIBUTE = "attribute"
    DIMENSION = "dimension"
    QUANTITY = "quantity"
    PROPERTY = "property"
    TYPE_FACT = "type_fact"


class Operator(str, Enum):
    """spec_v003 §7 — numeric/date/bool operators plus the 5 string match modes.

    `in` doubles as both a numeric/date list-membership operator and one of
    the 5 required string modes; it is not duplicated.
    """

    EQ = "eq"
    NE = "ne"
    GT = "gt"
    GTE = "gte"
    LT = "lt"
    LTE = "lte"
    BETWEEN = "between"
    IN = "in"
    NOT_IN = "not_in"
    EXACT = "exact"
    CASE_INSENSITIVE_EXACT = "case_insensitive_exact"
    CONTAINS = "contains"
    STARTS_WITH = "starts_with"


_STRING_MODE_OPERATORS = {
    Operator.EXACT,
    Operator.CASE_INSENSITIVE_EXACT,
    Operator.CONTAINS,
    Operator.STARTS_WITH,
}
_LIST_OPERATORS = {Operator.IN, Operator.NOT_IN}


class FieldRef(_StrictModel):
    """A validated reference to a semantic field. Resolution/provenance happens
    in query.sql.field_registry — this model only fixes the allowlisted shape."""

    field_kind: FieldKind
    set_name: str | None = Field(default=None, max_length=200)
    field_name: str = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def _set_name_required_for_quantity_and_property(self) -> "FieldRef":
        if self.field_kind in (FieldKind.QUANTITY, FieldKind.PROPERTY) and not self.set_name:
            raise ValueError(f"{self.field_kind.value} fields require set_name")
        if (
            self.field_kind in (FieldKind.ATTRIBUTE, FieldKind.DIMENSION, FieldKind.TYPE_FACT)
            and self.set_name
        ):
            raise ValueError(f"{self.field_kind.value} fields must not set set_name")
        return self


class FilterCondition(_StrictModel):
    field: FieldRef
    operator: Operator
    value: float | int | str | bool | list[float | int | str | bool] = Field(...)
    unit: str | None = Field(default=None, max_length=16)

    @model_validator(mode="after")
    def _validate_value_shape(self) -> "FilterCondition":
        if self.operator is Operator.BETWEEN:
            if not isinstance(self.value, list) or len(self.value) != 2:
                raise ValueError("between requires a 2-element [low, high] value")
        elif self.operator in _LIST_OPERATORS:
            if not isinstance(self.value, list) or not (1 <= len(self.value) <= 50):
                raise ValueError(f"{self.operator.value} requires a 1-50 element list value")
        else:
            if isinstance(self.value, list):
                raise ValueError(f"{self.operator.value} requires a scalar value")
            if self.operator in _STRING_MODE_OPERATORS and not isinstance(self.value, str):
                raise ValueError(f"{self.operator.value} requires a string value")
        return self


class FilterGroup(_StrictModel):
    bool_op: Literal["and", "or"]
    conditions: list["FilterNode"] = Field(min_length=1, max_length=MAX_FILTER_CONDITIONS)

    @model_validator(mode="after")
    def _bounded_tree(self) -> "FilterGroup":
        if _count_conditions(self) > MAX_FILTER_CONDITIONS:
            raise ValueError(f"filter tree exceeds max {MAX_FILTER_CONDITIONS} conditions")
        if _max_depth(self) > MAX_FILTER_DEPTH:
            raise ValueError(f"filter tree exceeds max depth {MAX_FILTER_DEPTH}")
        return self


FilterNode = Annotated[Union[FilterCondition, FilterGroup], Field(union_mode="smart")]
FilterGroup.model_rebuild()


def _count_conditions(node: FilterCondition | FilterGroup) -> int:
    if isinstance(node, FilterCondition):
        return 1
    return sum(_count_conditions(c) for c in node.conditions)


def _max_depth(node: FilterCondition | FilterGroup) -> int:
    if isinstance(node, FilterCondition):
        return 0
    if not node.conditions:
        return 1
    return 1 + max(_max_depth(c) for c in node.conditions)


class SortSpec(_StrictModel):
    field: FieldRef
    direction: Literal["asc", "desc"] = "asc"


# ---------------------------------------------------------------------------
# Catalog-scope plans (spec_v002 §4.1)
# ---------------------------------------------------------------------------


class ListModelsPlan(_StrictModel):
    limit: int = Field(default=DEFAULT_LIST_LIMIT, ge=1, le=MAX_LIST_LIMIT)


class FilterModelsPlan(_StrictModel):
    filters: FilterGroup | None = None
    limit: int = Field(default=DEFAULT_LIST_LIMIT, ge=1, le=MAX_LIST_LIMIT)


class ListModelVersionsPlan(_StrictModel):
    family_key: str = Field(min_length=1, max_length=200)


class RankModelsByEntityCountPlan(_StrictModel):
    entity_class: str = Field(min_length=1, max_length=200)
    direction: Literal["asc", "desc"] = "desc"
    limit: int = Field(default=10, ge=1, le=MAX_LIST_LIMIT)


class GetModelMetadataPlan(_StrictModel):
    source_model_id: int


# ---------------------------------------------------------------------------
# Active-model entity plans (spec_v002 §4.2)
# ---------------------------------------------------------------------------


class CountEntitiesPlan(_StrictModel):
    source_model_id: int
    entity_classes: list[str] = Field(default_factory=list, max_length=50)
    filters: FilterGroup | None = None


class ListEntitiesPlan(_StrictModel):
    source_model_id: int
    entity_classes: list[str] = Field(default_factory=list, max_length=50)
    filters: FilterGroup | None = None
    sort: list[SortSpec] = Field(default_factory=list, max_length=5)
    limit: int = Field(default=DEFAULT_LIST_LIMIT, ge=1, le=MAX_LIST_LIMIT)
    offset: int = Field(default=0, ge=0)


class GetEntityPlan(_StrictModel):
    source_model_id: int
    entity_id: int | None = None
    global_id: str | None = Field(default=None, min_length=1, max_length=64)

    @model_validator(mode="after")
    def _one_of_id(self) -> "GetEntityPlan":
        if (self.entity_id is None) == (self.global_id is None):
            raise ValueError("exactly one of entity_id or global_id is required")
        return self


class FilterEntitiesPlan(_StrictModel):
    source_model_id: int
    entity_classes: list[str] = Field(default_factory=list, max_length=50)
    filters: FilterGroup
    sort: list[SortSpec] = Field(default_factory=list, max_length=5)
    limit: int = Field(default=DEFAULT_LIST_LIMIT, ge=1, le=MAX_LIST_LIMIT)
    offset: int = Field(default=0, ge=0)


class AggregateEntitiesPlan(_StrictModel):
    source_model_id: int
    entity_classes: list[str] = Field(default_factory=list, max_length=50)
    filters: FilterGroup | None = None
    field: FieldRef | None = None  # None only valid for function="count"
    function: Literal["count", "sum", "min", "max", "average"]
    unit: str | None = Field(default=None, max_length=16)  # target normalized unit, e.g. "mm"

    @model_validator(mode="after")
    def _field_required_unless_count(self) -> "AggregateEntitiesPlan":
        if self.function != "count" and self.field is None:
            raise ValueError(f"{self.function} requires field")
        return self


class GroupEntitiesPlan(_StrictModel):
    source_model_id: int
    entity_classes: list[str] = Field(default_factory=list, max_length=50)
    filters: FilterGroup | None = None
    group_by_field: FieldRef
    aggregate_field: FieldRef | None = None
    function: Literal["count", "sum", "min", "max", "average"] = "count"
    unit: str | None = Field(default=None, max_length=16)
    limit: int = Field(default=DEFAULT_LIST_LIMIT, ge=1, le=MAX_LIST_LIMIT)

    @model_validator(mode="after")
    def _aggregate_field_required_unless_count(self) -> "GroupEntitiesPlan":
        if self.function != "count" and self.aggregate_field is None:
            raise ValueError(f"{self.function} requires aggregate_field")
        return self


class FindMissingValuesPlan(_StrictModel):
    source_model_id: int
    entity_classes: list[str] = Field(default_factory=list, max_length=50)
    field: FieldRef
    limit: int = Field(default=DEFAULT_LIST_LIMIT, ge=1, le=MAX_LIST_LIMIT)


class GetSelectedEntitiesPlan(_StrictModel):
    source_model_id: int
    entity_ids: list[int] = Field(min_length=1, max_length=50)


# ---------------------------------------------------------------------------
# Relationship / graph plans (spec_v002 §4.2, spec_v003 §12)
# ---------------------------------------------------------------------------


class ListRelationshipsPlan(_StrictModel):
    source_model_id: int
    relationship_classes: list[str] = Field(default_factory=list, max_length=50)
    limit: int = Field(default=DEFAULT_LIST_LIMIT, ge=1, le=MAX_LIST_LIMIT)
    offset: int = Field(default=0, ge=0)


class GetRelationshipPlan(_StrictModel):
    source_model_id: int
    relationship_id: int | None = None
    global_id: str | None = Field(default=None, min_length=1, max_length=64)

    @model_validator(mode="after")
    def _one_of_id(self) -> "GetRelationshipPlan":
        if (self.relationship_id is None) == (self.global_id is None):
            raise ValueError("exactly one of relationship_id or global_id is required")
        return self


class GetRelationshipMembersPlan(_StrictModel):
    source_model_id: int
    relationship_id: int


class TraverseRelationshipsPlan(_StrictModel):
    source_model_id: int
    start_entity_ids: list[int] = Field(min_length=1, max_length=50)
    relationship_classes: list[str] = Field(default_factory=list, max_length=50)
    max_depth: int = Field(default=DEFAULT_TRAVERSAL_DEPTH, ge=0, le=MAX_TRAVERSAL_DEPTH)
    direction: Literal["outgoing", "incoming", "both"] = "both"
