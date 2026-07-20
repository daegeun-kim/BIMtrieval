"""Entity operations (spec_v003 §6, §9, §11). Every operation is active-model
scope and always filters by source_model_id."""

from __future__ import annotations

from dataclasses import dataclass, field

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.db.models import IfcEntity
from app.query.sql.aggregates import (
    AggregateResult,
    GroupBucket,
    compute_aggregate,
    compute_group_by,
)
from app.query.sql.compiler import (
    build_condition_expr,
    path_array_param,
    resolved_parent_has_key_expr,
    resolved_text_expr,
)
from app.query.sql.errors import UnknownEntityOrRelationshipError
from app.query.sql.field_registry import resolve_field
from app.query.sql.operations import MissingValueState
from app.query.sql.schemas import (
    AggregateEntitiesPlan,
    CountEntitiesPlan,
    FilterEntitiesPlan,
    FindMissingValuesPlan,
    GetEntityPlan,
    GetSelectedEntitiesPlan,
    GroupEntitiesPlan,
    ListEntitiesPlan,
)

_ET = IfcEntity.__table__
_NAME_PATH = ("identity", "name")
_STOREY_NAME_PATH = ("storey", "name")


def _base_where(source_model_id: int, entity_classes: list[str]) -> sa.ColumnElement:
    where = _ET.c.source_model_id == source_model_id
    if entity_classes:
        where = sa.and_(where, _ET.c.ifc_class.in_(entity_classes))
    return where


def entity_hydration_columns() -> list[sa.ColumnElement]:
    name_expr = _ET.c.canonical_json.op("#>>")(path_array_param(_NAME_PATH)).label("name")
    storey_expr = _ET.c.canonical_json.op("#>>")(path_array_param(_STOREY_NAME_PATH)).label(
        "storey_name"
    )
    return [_ET.c.id, _ET.c.global_id, _ET.c.ifc_class, name_expr, storey_expr]


def count_entities(session: Session, plan: CountEntitiesPlan) -> int:
    where = _base_where(plan.source_model_id, plan.entity_classes)
    if plan.filters is not None:
        where = sa.and_(
            where, build_condition_expr(session, plan.source_model_id, plan.filters, _ET)
        )
    return session.execute(sa.select(sa.func.count()).select_from(_ET).where(where)).scalar_one()


@dataclass
class ViewerIdentityResult:
    """Identity-only match set for viewer highlighting (task13 §2)."""

    rows: list  # (global_id, ifc_class) — nothing else is selected
    exact_total: int
    truncated: bool


def _identities_for_where(
    session: Session, where: sa.ColumnElement, limit: int | None
) -> ViewerIdentityResult:
    """Identity-only rows + the exact total for an arbitrary scoped predicate.

    Selects only `global_id` + `ifc_class`; the exact total is counted over the
    full predicate so it is never reduced by `limit`. Ordered by `id` so
    truncation is stable and deterministic across calls.

    `limit=None` returns EVERY matching identity with no cap (Task 17 §9 complete
    viewer hydration) — `truncated` is then always False.
    """
    exact_total = session.execute(
        sa.select(sa.func.count()).select_from(_ET).where(where)
    ).scalar_one()
    stmt = sa.select(_ET.c.global_id, _ET.c.ifc_class).where(where).order_by(_ET.c.id)
    if limit is not None:
        stmt = stmt.limit(limit)
    rows = session.execute(stmt).all()
    return ViewerIdentityResult(
        rows=list(rows),
        exact_total=exact_total,
        truncated=exact_total > len(rows),
    )


def _class_counts_for_where(session: Session, where: sa.ColumnElement) -> dict[str, int]:
    """Exact count grouped by IFC class over the full predicate."""
    rows = session.execute(
        sa.select(_ET.c.ifc_class, sa.func.count().label("cnt"))
        .where(where)
        .group_by(_ET.c.ifc_class)
    ).all()
    return {r.ifc_class: r.cnt for r in sorted(rows, key=lambda r: (-r.cnt, r.ifc_class))}


def _entity_where(source_model_id: int, entity_classes: list[str], filters, session: Session):
    where = _base_where(source_model_id, entity_classes)
    if filters is not None:
        where = sa.and_(where, build_condition_expr(session, source_model_id, filters, _ET))
    return where


def select_scope_entity_ids(
    session: Session, predicate, source_model_id: int, limit: int | None = None
) -> list[int]:
    """Canonical entity ids inside a group predicate's structured scope (Task 23 §1).

    Used to run RAG and graph traversal INSIDE a resolved compound scope instead
    of over the whole model. Reuses the same `_entity_where` compilation as the
    count and the viewer identities, so all three describe one identical set.
    """
    from app.query.hybrid.groups.execute import compile_predicate_group
    from app.query.sql.class_aliases import expand_entity_classes

    classes = list(expand_entity_classes(list(predicate.ifc_classes)))
    filters = compile_predicate_group(predicate.filters) if predicate.filters is not None else None
    where = _entity_where(source_model_id, classes, filters, session)
    stmt = sa.select(_ET.c.id).where(where)
    if limit is not None:
        stmt = stmt.limit(limit)
    return [r[0] for r in session.execute(stmt)]


def select_viewer_identities(
    session: Session,
    source_model_id: int,
    entity_classes: list[str],
    filters,
    limit: int | None,
) -> ViewerIdentityResult:
    """Deterministic identity-only retrieval over the *same* filtered set a
    count/list/aggregate matched (task13 §2).

    Deliberately separate from both the exact count (never capped) and the
    50-item LLM evidence bound: this returns only what the viewer needs to
    highlight geometry — active-model-scoped GlobalId + minimal class identity,
    never names, canonical JSON, or full object detail.

    Reuses `_base_where` (source_model_id first) and the same filter compilation
    as `count_entities`, so the highlighted set can never drift from the counted
    set.
    """
    where = _entity_where(source_model_id, entity_classes, filters, session)
    return _identities_for_where(session, where, limit)


def count_by_class(
    session: Session,
    source_model_id: int,
    entity_classes: list[str],
    filters,
) -> dict[str, int]:
    """Exact count grouped by IFC class over the FULL matching set (task13 §3).

    Computed with its own GROUP BY rather than tallying the returned rows, so
    the compact class summary stays exact even when the viewer match set is
    truncated at the 2,000 cap.
    """
    where = _entity_where(source_model_id, entity_classes, filters, session)
    return _class_counts_for_where(session, where)


# ---------------------------------------------------------------------------
# Component details + deterministic group matching (task13 §4, §5)
# ---------------------------------------------------------------------------

_TYPE_GLOBAL_ID_PATH = ("type", "global_id")
_TYPE_NAME_PATH = ("type", "name")


def _json_text(path: tuple[str, ...]) -> sa.ColumnElement:
    return _ET.c.canonical_json.op("#>>")(path_array_param(path))


def get_entity_canonical(session: Session, source_model_id: int, global_id: str):
    """Fetch one entity's stored canonical JSON, scoped to the model (task13 §4).

    Every predicate includes `source_model_id`, so a GlobalId belonging to a
    different model simply does not resolve — the caller returns 404 without
    revealing that the entity exists elsewhere.
    """
    row = session.execute(
        sa.select(_ET.c.id, _ET.c.global_id, _ET.c.ifc_class, _ET.c.canonical_json).where(
            _ET.c.source_model_id == source_model_id,
            _ET.c.global_id == global_id,
        )
    ).first()
    return row


def get_ifc_class_for_global_id(
    session: Session, source_model_id: int, global_id: str
) -> str | None:
    """IFC class of an in-model entity by GlobalId, or None.

    Used to report an explicit type object's own IFC class when that type was
    itself ingested as an entity. Returns None rather than guessing.
    """
    return session.execute(
        sa.select(_ET.c.ifc_class).where(
            _ET.c.source_model_id == source_model_id,
            _ET.c.global_id == global_id,
        )
    ).scalar_one_or_none()


def match_instance(
    session: Session, source_model_id: int, global_id: str, limit: int
) -> tuple[ViewerIdentityResult, dict[str, int]]:
    """`instance` scope: the selected entity only (task13 §5)."""
    where = sa.and_(
        _ET.c.source_model_id == source_model_id,
        _ET.c.global_id == global_id,
    )
    return _identities_for_where(session, where, limit), _class_counts_for_where(session, where)


def match_by_type_global_id(
    session: Session, source_model_id: int, type_global_id: str, limit: int
) -> tuple[ViewerIdentityResult, dict[str, int]]:
    """`type` scope, preferred form: exact explicit type GlobalId (task13 §5)."""
    where = sa.and_(
        _ET.c.source_model_id == source_model_id,
        _json_text(_TYPE_GLOBAL_ID_PATH) == type_global_id,
    )
    return _identities_for_where(session, where, limit), _class_counts_for_where(session, where)


def match_by_type_name(
    session: Session, source_model_id: int, type_name: str, limit: int
) -> tuple[ViewerIdentityResult, dict[str, int]]:
    """`type` scope, fallback: exact *normalized* stored type name, used only
    when the IFC gave a type name without a GlobalId (task13 §5).

    Normalization is case/whitespace folding on both sides — an exact match, not
    a fuzzy or partial one, and always within the same model.
    """
    normalized = sa.func.lower(sa.func.btrim(_json_text(_TYPE_NAME_PATH)))
    where = sa.and_(
        _ET.c.source_model_id == source_model_id,
        normalized == sa.func.lower(sa.func.btrim(sa.bindparam(None, type_name))),
    )
    return _identities_for_where(session, where, limit), _class_counts_for_where(session, where)


def match_by_family(
    session: Session,
    source_model_id: int,
    property_set: str,
    property_name: str,
    value: str,
    limit: int,
) -> tuple[ViewerIdentityResult, dict[str, int]]:
    """`family` scope: exact normalized value of the *same* allowlisted stored
    property the selected entity's family came from (task13 §5).

    Tied to explicit stored family data — the property set and property name are
    bound path parameters taken from the selected entity's own record, never a
    name-derived guess.
    """
    path = ("property_sets", property_set, property_name, "value")
    normalized = sa.func.lower(sa.func.btrim(_json_text(path)))
    where = sa.and_(
        _ET.c.source_model_id == source_model_id,
        normalized == sa.func.lower(sa.func.btrim(sa.bindparam(None, value))),
    )
    return _identities_for_where(session, where, limit), _class_counts_for_where(session, where)


def _select_entities(
    session: Session,
    source_model_id: int,
    entity_classes: list[str],
    filters,
    sort,
    limit: int,
    offset: int,
):
    where = _base_where(source_model_id, entity_classes)
    if filters is not None:
        where = sa.and_(where, build_condition_expr(session, source_model_id, filters, _ET))
    stmt = sa.select(*entity_hydration_columns()).where(where)
    for s in sort:
        resolved = resolve_field(session, source_model_id, s.field)
        expr = resolved_text_expr(resolved, _ET)
        stmt = stmt.order_by(expr.desc() if s.direction == "desc" else expr.asc())
    # deterministic tiebreaker (spec_v003 §11: "stable deterministic sorting")
    stmt = stmt.order_by(_ET.c.id).limit(limit).offset(offset)
    return session.execute(stmt).all()


def list_entities(session: Session, plan: ListEntitiesPlan):
    return _select_entities(
        session,
        plan.source_model_id,
        plan.entity_classes,
        plan.filters,
        plan.sort,
        plan.limit,
        plan.offset,
    )


def filter_entities(session: Session, plan: FilterEntitiesPlan):
    return _select_entities(
        session,
        plan.source_model_id,
        plan.entity_classes,
        plan.filters,
        plan.sort,
        plan.limit,
        plan.offset,
    )


def get_entity(session: Session, plan: GetEntityPlan):
    where = _ET.c.source_model_id == plan.source_model_id
    if plan.entity_id is not None:
        where = sa.and_(where, _ET.c.id == plan.entity_id)
    else:
        where = sa.and_(where, _ET.c.global_id == plan.global_id)
    row = session.execute(sa.select(*entity_hydration_columns()).where(where)).first()
    if row is None:
        raise UnknownEntityOrRelationshipError(
            f"entity not found for source_model_id={plan.source_model_id}"
        )
    return row


def get_selected_entities(session: Session, plan: GetSelectedEntitiesPlan):
    where = sa.and_(_ET.c.source_model_id == plan.source_model_id, _ET.c.id.in_(plan.entity_ids))
    return session.execute(sa.select(*entity_hydration_columns()).where(where)).all()


def resolve_entities_by_global_ids(session: Session, source_model_id: int, global_ids: list[str]):
    """Active-model-scoped GlobalId -> compact identity resolution (Task 10 §4).

    Every predicate includes `source_model_id`, so cross-model GlobalIds simply
    do not resolve (no cross-model leakage). Returns compact rows
    (id, global_id, ifc_class, name) — never canonical_json. Parameterized ORM
    only; no LLM call, no write.
    """
    if not global_ids:
        return []
    name_expr = _ET.c.canonical_json.op("#>>")(path_array_param(_NAME_PATH)).label("name")
    where = sa.and_(
        _ET.c.source_model_id == source_model_id,
        _ET.c.global_id.in_(global_ids),
    )
    stmt = sa.select(_ET.c.id, _ET.c.global_id, _ET.c.ifc_class, name_expr).where(where)
    return session.execute(stmt).all()


def aggregate_entities(session: Session, plan: AggregateEntitiesPlan) -> AggregateResult:
    where = _base_where(plan.source_model_id, plan.entity_classes)
    if plan.filters is not None:
        where = sa.and_(
            where, build_condition_expr(session, plan.source_model_id, plan.filters, _ET)
        )
    resolved = resolve_field(session, plan.source_model_id, plan.field) if plan.field else None
    return compute_aggregate(session, _ET, where, plan.function, resolved, plan.unit)


def group_entities(session: Session, plan: GroupEntitiesPlan) -> list[GroupBucket]:
    where = _base_where(plan.source_model_id, plan.entity_classes)
    if plan.filters is not None:
        where = sa.and_(
            where, build_condition_expr(session, plan.source_model_id, plan.filters, _ET)
        )
    group_resolved = resolve_field(session, plan.source_model_id, plan.group_by_field)
    agg_resolved = (
        resolve_field(session, plan.source_model_id, plan.aggregate_field)
        if plan.aggregate_field
        else None
    )
    return compute_group_by(
        session, _ET, where, group_resolved, plan.function, agg_resolved, plan.unit, plan.limit
    )


@dataclass
class MissingValueReport:
    field_kind: str
    set_name: str | None
    field_name: str
    matched_count: int
    state_counts: dict[str, int] = field(default_factory=dict)
    example_ids: dict[str, list[int]] = field(default_factory=dict)


def find_missing_values(session: Session, plan: FindMissingValuesPlan) -> MissingValueReport:
    """Exact (full-matching-set) missing-value state counts, plus bounded
    example entity IDs per state (spec_v003 §9, §11)."""
    where = _base_where(plan.source_model_id, plan.entity_classes)
    resolved = resolve_field(session, plan.source_model_id, plan.field)
    parent_has_key = resolved_parent_has_key_expr(resolved, _ET)
    leaf_text = resolved_text_expr(resolved, _ET)

    state_case = sa.case(
        (~parent_has_key, sa.literal(MissingValueState.ABSENT.value)),
        (leaf_text.is_(None), sa.literal(MissingValueState.PRESENT_NULL.value)),
        (leaf_text == "", sa.literal(MissingValueState.PRESENT_EMPTY.value)),
        else_=sa.null(),
    )

    matched_count = session.execute(
        sa.select(sa.func.count()).select_from(_ET).where(where)
    ).scalar_one()

    counts_stmt = (
        sa.select(state_case.label("state"), sa.func.count().label("cnt"))
        .select_from(_ET)
        .where(where)
        .group_by(state_case)
    )
    state_counts = {r.state: r.cnt for r in session.execute(counts_stmt) if r.state is not None}

    example_ids: dict[str, list[int]] = {}
    for state in state_counts:
        ex_stmt = (
            sa.select(_ET.c.id)
            .where(where, state_case == state)
            .order_by(_ET.c.id)
            .limit(plan.limit)
        )
        example_ids[state] = [r[0] for r in session.execute(ex_stmt)]

    return MissingValueReport(
        field_kind=resolved.field_kind.value,
        set_name=resolved.set_name,
        field_name=resolved.field_name,
        matched_count=matched_count,
        state_counts=state_counts,
        example_ids=example_ids,
    )
