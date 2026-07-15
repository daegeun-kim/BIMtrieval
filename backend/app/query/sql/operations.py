"""Operation registry: SqlOperation -> typed plan model (spec_v003 §6).

Also defines the missing-value state vocabulary (spec_v003 §9), used by
`find_missing_values` and field resolution across this package.
"""

from __future__ import annotations

from enum import Enum

from app.query.sql.schemas import (
    AggregateEntitiesPlan,
    CountEntitiesPlan,
    FilterEntitiesPlan,
    FilterModelsPlan,
    FindMissingValuesPlan,
    GetEntityPlan,
    GetModelMetadataPlan,
    GetRelationshipMembersPlan,
    GetRelationshipPlan,
    GetSelectedEntitiesPlan,
    GroupEntitiesPlan,
    ListEntitiesPlan,
    ListModelsPlan,
    ListModelVersionsPlan,
    ListRelationshipsPlan,
    RankModelsByEntityCountPlan,
    SqlOperation,
    TraverseRelationshipsPlan,
)


class MissingValueState(str, Enum):
    """spec_v003 §9 — never collapsed into one generic null."""

    ABSENT = "absent"
    PRESENT_NULL = "present_null"
    PRESENT_EMPTY = "present_empty"
    EXTRACTION_FAILED = "extraction_failed"
    UNSUPPORTED_VALUE = "unsupported_value"


PLAN_BY_OPERATION: dict[SqlOperation, type] = {
    SqlOperation.LIST_MODELS: ListModelsPlan,
    SqlOperation.FILTER_MODELS: FilterModelsPlan,
    SqlOperation.LIST_MODEL_VERSIONS: ListModelVersionsPlan,
    SqlOperation.RANK_MODELS_BY_ENTITY_COUNT: RankModelsByEntityCountPlan,
    SqlOperation.GET_MODEL_METADATA: GetModelMetadataPlan,
    SqlOperation.COUNT_ENTITIES: CountEntitiesPlan,
    SqlOperation.LIST_ENTITIES: ListEntitiesPlan,
    SqlOperation.GET_ENTITY: GetEntityPlan,
    SqlOperation.FILTER_ENTITIES: FilterEntitiesPlan,
    SqlOperation.AGGREGATE_ENTITIES: AggregateEntitiesPlan,
    SqlOperation.GROUP_ENTITIES: GroupEntitiesPlan,
    SqlOperation.FIND_MISSING_VALUES: FindMissingValuesPlan,
    SqlOperation.LIST_RELATIONSHIPS: ListRelationshipsPlan,
    SqlOperation.GET_RELATIONSHIP: GetRelationshipPlan,
    SqlOperation.GET_RELATIONSHIP_MEMBERS: GetRelationshipMembersPlan,
    SqlOperation.TRAVERSE_RELATIONSHIPS: TraverseRelationshipsPlan,
    SqlOperation.GET_SELECTED_ENTITIES: GetSelectedEntitiesPlan,
}


def get_plan_model(operation: SqlOperation) -> type:
    return PLAN_BY_OPERATION[operation]
