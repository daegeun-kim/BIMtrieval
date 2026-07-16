"""Translate a validated planner `QueryPlan` into the typed execution plans the
query paths actually run (spec_v005 §5, §6).

The planner emits a flat, LLM-friendly plan (`llm.schemas`); the SQL/RAG/graph
paths consume the strict typed plans (`query.sql.schemas`, `query.rag.schemas`).
This module is the single bridge:

- maps each semantic `operation` to its typed plan and checks it is legal for
  the plan's scope (no entity ops in catalog scope, no catalog ops in active),
- resolves every filter field against the model's real schema
  (`field_registry.resolve_field`), turning unknown/ambiguous fields into a
  repairable `PlanValidationError` (spec_v005 §6) rather than a runtime crash,
- coerces string filter values to the resolved field's real numeric/text type,
- builds one depth-1 `FilterGroup` from the planner's flat filter list.

No raw SQL is ever produced here (spec_v005 Prohibited actions).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.llm.schemas import CatalogPlan, PlanFieldRef, PlanFilter, QueryPlan, SqlPlan
from app.llm.validation import PlanValidationError
from app.query.sql.class_aliases import expand_entity_classes
from app.query.sql.errors import AmbiguousFieldError, FieldNotFoundError
from app.query.sql.field_registry import resolve_field
from app.query.sql.schemas import (
    AggregateEntitiesPlan,
    CountEntitiesPlan,
    FieldKind,
    FieldRef,
    FilterCondition,
    FilterEntitiesPlan,
    FilterGroup,
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
    Operator,
    RankModelsByEntityCountPlan,
    SqlOperation,
    TraverseRelationshipsPlan,
)

_CATALOG_OPS = {
    SqlOperation.LIST_MODELS,
    SqlOperation.FILTER_MODELS,
    SqlOperation.LIST_MODEL_VERSIONS,
    SqlOperation.RANK_MODELS_BY_ENTITY_COUNT,
    SqlOperation.GET_MODEL_METADATA,
}
_STRING_OPERATORS = {
    Operator.EXACT,
    Operator.CASE_INSENSITIVE_EXACT,
    Operator.CONTAINS,
    Operator.STARTS_WITH,
}
_LIST_OPERATORS = {Operator.IN, Operator.NOT_IN}


@dataclass
class TranslatedPlan:
    """Typed execution plans ready for the orchestrator. Only the fields the
    route uses are populated."""

    catalog_operation: SqlOperation | None = None
    catalog_plan: Any = None
    sql_operation: SqlOperation | None = None
    sql_plan: Any = None
    rag_plan: Any = None  # query.rag.schemas.RagSearchPlan
    graph_plan: TraverseRelationshipsPlan | None = None


def _field_ref(pf: PlanFieldRef) -> FieldRef:
    try:
        return FieldRef(
            field_kind=pf.field_kind,
            set_name=pf.set_name,
            field_name=pf.field_name,
        )
    except ValidationError as exc:
        # e.g. quantity/property without set_name — turn into a repairable message
        # rather than a 500 (spec_v005 §6). Hint the planner toward `dimension`,
        # which needs no set_name.
        raise PlanValidationError(
            f"invalid field reference for {pf.field_name!r} "
            f"(kind={pf.field_kind.value}, set_name={pf.set_name}): use field_kind='dimension' "
            f"for a bare quantity name, or supply set_name. ({_first_error(exc)})"
        ) from None


def _first_error(exc: ValidationError) -> str:
    errs = exc.errors()
    return errs[0]["msg"] if errs else str(exc)


def _validated_field_ref(session: Session, source_model_id: int, pf: PlanFieldRef) -> FieldRef:
    """Build a FieldRef AND confirm it resolves in this model's schema, so an
    unknown/ambiguous aggregate/group/missing field is a repairable planner
    error (spec_v005 §6), not a crash during execution."""
    ref = _field_ref(pf)
    try:
        resolve_field(session, source_model_id, ref)
    except AmbiguousFieldError as exc:
        raise PlanValidationError(
            f"field {pf.field_name!r} is ambiguous; pick field_kind=quantity with a set_name "
            f"from the schema ({exc})"
        ) from None
    except FieldNotFoundError as exc:
        raise PlanValidationError(
            f"field {pf.field_name!r} is not in this model's schema; use an exact "
            f"class/field/set name from the schema context ({exc})"
        ) from None
    return ref


def _coerce_scalar(text: str, numeric: bool) -> float | str:
    if not numeric:
        return text
    try:
        return float(text)
    except (TypeError, ValueError):
        raise PlanValidationError(
            f"filter value {text!r} is not numeric but the field is numeric"
        ) from None


def _build_entity_condition(
    session: Session, source_model_id: int, pf: PlanFilter
) -> FilterCondition:
    try:
        resolved = resolve_field(session, source_model_id, _field_ref(pf.field))
    except AmbiguousFieldError as exc:
        raise PlanValidationError(
            f"field {pf.field.field_name!r} is ambiguous; specify field_kind and set_name ({exc})"
        ) from None
    except FieldNotFoundError as exc:
        raise PlanValidationError(
            f"field {pf.field.field_name!r} not found in this model's schema ({exc})"
        ) from None

    numeric = resolved.field_kind in (FieldKind.QUANTITY, FieldKind.DIMENSION) or (
        resolved.declared_value_type == "float"
    )
    op = pf.operator

    if op is Operator.BETWEEN:
        if len(pf.value_list) != 2:
            raise PlanValidationError("between requires exactly two values in value_list")
        value: Any = [float(_coerce_scalar(v, True)) for v in pf.value_list]
    elif op in _LIST_OPERATORS:
        if not pf.value_list:
            raise PlanValidationError(f"{op.value} requires a non-empty value_list")
        value = [_coerce_scalar(v, numeric) for v in pf.value_list]
    else:
        if pf.value_text is None:
            raise PlanValidationError(f"{op.value} requires value_text")
        force_string = op in _STRING_OPERATORS
        value = _coerce_scalar(pf.value_text, numeric and not force_string)

    return FilterCondition(field=_field_ref(pf.field), operator=op, value=value, unit=pf.unit)


def _entity_filter_group(
    session: Session, source_model_id: int, filters: list[PlanFilter], bool_op: str
) -> FilterGroup | None:
    if not filters:
        return None
    conditions = [_build_entity_condition(session, source_model_id, pf) for pf in filters]
    return FilterGroup(bool_op=bool_op, conditions=conditions)


_TRUE_STRINGS = {"true", "1", "yes", "current", "y", "t"}


def _catalog_filter_group(filters: list[PlanFilter], bool_op: str) -> FilterGroup | None:
    """Catalog filters reference catalog columns (not entity schema fields).

    Field names are validated up front against the catalog allowlist so an
    unsupported field is a repairable planner error (spec_v005 §6) rather than a
    crash at execution. Boolean columns (is_current) are coerced to real bools."""
    from app.query.sql.catalog import _CATALOG_BOOLEAN_COLUMNS, CATALOG_FILTER_FIELDS

    if not filters:
        return None
    conditions: list[FilterCondition] = []
    for pf in filters:
        name = pf.field.field_name
        if name not in CATALOG_FILTER_FIELDS:
            raise PlanValidationError(
                f"catalog filter field {name!r} is not supported; use one of "
                f"{sorted(CATALOG_FILTER_FIELDS)}"
            )
        if pf.value_text is None and not pf.value_list:
            raise PlanValidationError("catalog filter requires value_text or value_list")
        op = pf.operator
        if name in _CATALOG_BOOLEAN_COLUMNS:
            value: Any = (pf.value_text or "").strip().lower() in _TRUE_STRINGS
            op = Operator.EQ  # boolean equality only, regardless of requested op
        elif op in _LIST_OPERATORS:
            value = pf.value_list
        else:
            value = pf.value_text or ""
        conditions.append(
            FilterCondition(
                field=FieldRef(field_kind=FieldKind.ATTRIBUTE, field_name=name),
                operator=op,
                value=value,
            )
        )
    return FilterGroup(bool_op=bool_op, conditions=conditions)


def _translate_catalog(plan: CatalogPlan) -> tuple[SqlOperation, Any]:
    op = plan.operation
    if op not in _CATALOG_OPS:
        raise PlanValidationError(
            f"operation {op.value!r} is not a catalog operation; use an active model instead"
        )
    limit = plan.limit
    if op is SqlOperation.LIST_MODELS:
        return op, ListModelsPlan(limit=limit or 50)
    if op is SqlOperation.FILTER_MODELS:
        return op, FilterModelsPlan(
            filters=_catalog_filter_group(plan.filters, plan.filter_bool_op), limit=limit or 50
        )
    if op is SqlOperation.LIST_MODEL_VERSIONS:
        if not plan.family_key:
            # "what versions exist?" without naming a specific family is a valid
            # question — degrade to listing all catalog models (each version is a
            # catalog row) rather than forcing a clarification (task08 finding).
            return SqlOperation.LIST_MODELS, ListModelsPlan(limit=limit or 50)
        return op, ListModelVersionsPlan(family_key=plan.family_key)
    if op is SqlOperation.RANK_MODELS_BY_ENTITY_COUNT:
        if not plan.entity_class:
            raise PlanValidationError("rank_models_by_entity_count requires entity_class")
        return op, RankModelsByEntityCountPlan(
            entity_class=plan.entity_class, direction=plan.direction, limit=limit or 10
        )
    if op is SqlOperation.GET_MODEL_METADATA:
        if plan.target_source_model_id is None:
            raise PlanValidationError("get_model_metadata requires target_source_model_id")
        return op, GetModelMetadataPlan(source_model_id=plan.target_source_model_id)
    raise PlanValidationError(f"unsupported catalog operation {op.value!r}")


def _translate_sql(
    session: Session, source_model_id: int, plan: SqlPlan
) -> tuple[SqlOperation, Any]:
    op = plan.operation
    if op in _CATALOG_OPS:
        raise PlanValidationError(
            f"operation {op.value!r} is a catalog operation; not valid in active-model scope"
        )
    sid = source_model_id
    # Expand generic classes to every stored class that satisfies them — notably
    # IfcWall -> {IfcWall, IfcWallStandardCase} (task13 §2). Explicit and central:
    # every entity operation below inherits it, and unknown classes pass through.
    classes = expand_entity_classes(plan.entity_classes)
    fg = _entity_filter_group(session, sid, plan.filters, plan.filter_bool_op)
    limit = plan.limit

    if op is SqlOperation.COUNT_ENTITIES:
        return op, CountEntitiesPlan(source_model_id=sid, entity_classes=classes, filters=fg)
    if op is SqlOperation.LIST_ENTITIES:
        return op, ListEntitiesPlan(
            source_model_id=sid, entity_classes=classes, filters=fg, limit=limit or 50
        )
    if op is SqlOperation.FILTER_ENTITIES:
        if fg is None:
            raise PlanValidationError("filter_entities requires at least one filter")
        return op, FilterEntitiesPlan(
            source_model_id=sid, entity_classes=classes, filters=fg, limit=limit or 50
        )
    if op is SqlOperation.AGGREGATE_ENTITIES:
        if plan.aggregate_function is None:
            raise PlanValidationError("aggregate_entities requires aggregate_function")
        if plan.aggregate_function != "count" and plan.aggregate_field is None:
            raise PlanValidationError(f"{plan.aggregate_function} requires aggregate_field")
        field = (
            _validated_field_ref(session, sid, plan.aggregate_field)
            if plan.aggregate_field
            else None
        )
        return op, AggregateEntitiesPlan(
            source_model_id=sid,
            entity_classes=classes,
            filters=fg,
            field=field,
            function=plan.aggregate_function,
            unit=plan.target_unit,
        )
    if op is SqlOperation.GROUP_ENTITIES:
        if plan.group_by_field is None:
            raise PlanValidationError("group_entities requires group_by_field")
        agg_field = (
            _validated_field_ref(session, sid, plan.aggregate_field)
            if plan.aggregate_field
            else None
        )
        return op, GroupEntitiesPlan(
            source_model_id=sid,
            entity_classes=classes,
            filters=fg,
            group_by_field=_validated_field_ref(session, sid, plan.group_by_field),
            aggregate_field=agg_field,
            function=plan.aggregate_function or "count",
            unit=plan.target_unit,
            limit=limit or 50,
        )
    if op is SqlOperation.GET_ENTITY:
        return op, GetEntityPlan(
            source_model_id=sid, entity_id=plan.entity_id, global_id=plan.global_id
        )
    if op is SqlOperation.GET_SELECTED_ENTITIES:
        if not plan.entity_ids:
            raise PlanValidationError("get_selected_entities requires entity_ids")
        return op, GetSelectedEntitiesPlan(source_model_id=sid, entity_ids=plan.entity_ids)
    if op is SqlOperation.FIND_MISSING_VALUES:
        if plan.aggregate_field is None:
            raise PlanValidationError("find_missing_values requires a field (use aggregate_field)")
        return op, FindMissingValuesPlan(
            source_model_id=sid,
            entity_classes=classes,
            field=_validated_field_ref(session, sid, plan.aggregate_field),
            limit=limit or 50,
        )
    if op is SqlOperation.LIST_RELATIONSHIPS:
        return op, ListRelationshipsPlan(
            source_model_id=sid, relationship_classes=plan.relationship_classes, limit=limit or 50
        )
    if op is SqlOperation.GET_RELATIONSHIP:
        return op, GetRelationshipPlan(
            source_model_id=sid, relationship_id=plan.relationship_id, global_id=plan.global_id
        )
    if op is SqlOperation.GET_RELATIONSHIP_MEMBERS:
        if plan.relationship_id is None:
            raise PlanValidationError("get_relationship_members requires relationship_id")
        return op, GetRelationshipMembersPlan(
            source_model_id=sid, relationship_id=plan.relationship_id
        )
    if op is SqlOperation.TRAVERSE_RELATIONSHIPS:
        if not plan.entity_ids:
            raise PlanValidationError("traverse_relationships requires entity_ids (start ids)")
        return op, TraverseRelationshipsPlan(
            source_model_id=sid,
            start_entity_ids=plan.entity_ids,
            relationship_classes=plan.relationship_classes,
        )
    raise PlanValidationError(f"unsupported sql operation {op.value!r}")


def _translate_rag(source_model_id: int, plan: QueryPlan) -> Any:
    from app.query.rag.schemas import RagSearchPlan

    rp = plan.rag_plan
    assert rp is not None
    return RagSearchPlan(
        source_model_id=source_model_id,
        semantic_query=rp.semantic_query,
        search_entity_documents=rp.search_entity_documents,
        search_relationship_documents=rp.search_relationship_documents,
        top_k_per_kind=rp.top_k_per_kind,
        visible_limit=rp.visible_limit,
        minimum_similarity_profile=rp.threshold_profile,
        expand_relationship_endpoints=rp.expand_relationship_endpoints,
        selected_entity_ids=[],
    )


def _translate_graph(source_model_id: int, plan: QueryPlan) -> TraverseRelationshipsPlan:
    gp = plan.graph_plan
    assert gp is not None
    if not gp.start_entity_ids:
        raise PlanValidationError("graph plan requires start_entity_ids")
    return TraverseRelationshipsPlan(
        source_model_id=source_model_id,
        start_entity_ids=gp.start_entity_ids,
        relationship_classes=gp.relationship_classes,
        max_depth=gp.max_depth,
        direction=gp.direction,
    )


def translate_plan(
    session: Session, plan: QueryPlan, selected_entity_ids: list[int]
) -> TranslatedPlan:
    """Build the typed execution plans for a structurally-valid QueryPlan.

    Raises PlanValidationError (repairable) for any DB-backed semantic problem.
    `selected_entity_ids` seed RAG selected-object context and graph starts when
    the planner did not name explicit ids.
    """
    try:
        return _translate_plan_inner(session, plan, selected_entity_ids)
    except ValidationError as exc:
        # Any typed-plan construction that violates its own bounds becomes a
        # repairable planner error, never an uncaught 500 (spec_v005 §6).
        raise PlanValidationError(f"plan failed typed validation: {_first_error(exc)}") from None


def _translate_plan_inner(
    session: Session, plan: QueryPlan, selected_entity_ids: list[int]
) -> TranslatedPlan:
    out = TranslatedPlan()
    sid = plan.source_model_id

    if plan.catalog_plan is not None:
        out.catalog_operation, out.catalog_plan = _translate_catalog(plan.catalog_plan)

    if plan.sql_plan is not None:
        if sid is None:
            raise PlanValidationError("sql_plan requires an active source_model_id")
        out.sql_operation, out.sql_plan = _translate_sql(session, sid, plan.sql_plan)

    if plan.rag_plan is not None:
        if sid is None:
            raise PlanValidationError("rag_plan requires an active source_model_id")
        rag = _translate_rag(sid, plan)
        if selected_entity_ids:
            rag.selected_entity_ids = selected_entity_ids[:5]
        out.rag_plan = rag

    if plan.graph_plan is not None:
        if sid is None:
            raise PlanValidationError("graph_plan requires an active source_model_id")
        gp = plan.graph_plan
        if not gp.start_entity_ids and selected_entity_ids:
            gp.start_entity_ids = selected_entity_ids[:50]
        out.graph_plan = _translate_graph(sid, plan)

    return out
