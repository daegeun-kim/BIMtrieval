"""Execute a typed group predicate against structured data (Task 17 §3, §8, §9).

All execution goes through the existing allowlisted typed SQL path — a predicate
is turned into a `List`/`Filter`/`GetSelected` plan, never raw SQL or a JSON
path. Two entry points: `execute_predicate` (exact count + bounded sample for
group construction) and `all_identities` (complete, uncapped identity hydration
for accepted viewer groups).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.api.schemas.response import PrimaryEntityResult
from app.query.hybrid.groups.schemas import (
    GroupPredicate,
    PredicateCondition,
    PredicateGroup,
    PredicateKind,
)
from app.query.sql.class_aliases import expand_entity_classes
from app.query.sql.dispatch import execute_sql
from app.query.sql.errors import AmbiguousFieldError, FieldNotFoundError
from app.query.sql.schemas import (
    FieldKind,
    FieldRef,
    FilterCondition,
    FilterEntitiesPlan,
    FilterGroup,
    GetSelectedEntitiesPlan,
    ListEntitiesPlan,
    Operator,
    SqlOperation,
)

_OPERATOR_MAP = {
    "exact": Operator.EXACT,
    "case_insensitive_exact": Operator.CASE_INSENSITIVE_EXACT,
    "contains": Operator.CONTAINS,
    "starts_with": Operator.STARTS_WITH,
    "eq": Operator.EQ,
    "ne": Operator.NE,
    "gt": Operator.GT,
    "gte": Operator.GTE,
    "lt": Operator.LT,
    "lte": Operator.LTE,
    "between": Operator.BETWEEN,
    "in": Operator.IN,
    "not_in": Operator.NOT_IN,
}
# Operators whose negation has a direct allowlisted inverse. Anything else is
# refused rather than approximated, so a negated condition is never silently
# turned into a weaker one (Task 23 §1).
_NEGATION_MAP = {
    Operator.EQ: Operator.NE,
    Operator.NE: Operator.EQ,
    Operator.EXACT: Operator.NE,
    Operator.CASE_INSENSITIVE_EXACT: Operator.NE,
    Operator.IN: Operator.NOT_IN,
    Operator.NOT_IN: Operator.IN,
    Operator.GT: Operator.LTE,
    Operator.GTE: Operator.LT,
    Operator.LT: Operator.GTE,
    Operator.LTE: Operator.GT,
}
_FIELD_KIND_MAP = {
    "attribute": FieldKind.ATTRIBUTE,
    "property": FieldKind.PROPERTY,
    "type_fact": FieldKind.TYPE_FACT,
    "quantity": FieldKind.QUANTITY,
    "dimension": FieldKind.DIMENSION,
}


@dataclass
class PredicateResult:
    ok: bool
    exact_count: int | None = None
    representative_entities: list[PrimaryEntityResult] = field(default_factory=list)
    viewer_global_ids: list[str] = field(default_factory=list)
    viewer_matches_total: int | None = None
    class_histogram: dict[str, int] = field(default_factory=dict)
    error: str | None = None


def _value_plan(predicate: GroupPredicate, source_model_id: int, limit: int) -> FilterEntitiesPlan:
    op = _OPERATOR_MAP[predicate.operator or "case_insensitive_exact"]
    fk = _FIELD_KIND_MAP[predicate.field_kind or "attribute"]
    condition = FilterCondition(
        field=FieldRef(field_kind=fk, set_name=predicate.set_name, field_name=predicate.field_name),
        operator=op,
        value=predicate.value,
    )
    return FilterEntitiesPlan(
        source_model_id=source_model_id,
        entity_classes=list(expand_entity_classes(list(predicate.ifc_classes))),
        filters=FilterGroup(bool_op="and", conditions=[condition]),
        limit=limit,
    )


def compile_condition(condition: PredicateCondition) -> FilterCondition:
    """One resolved leaf -> one allowlisted typed `FilterCondition`.

    Reuses the existing field/operator allowlists; raises rather than degrading so
    an uncompilable required condition fails its group instead of being dropped."""
    op = _OPERATOR_MAP.get(condition.operator)
    if op is None:
        raise ValueError(f"operator {condition.operator!r} is not allowlisted")
    if condition.negated:
        inverse = _NEGATION_MAP.get(op)
        if inverse is None:
            raise ValueError(f"operator {condition.operator!r} has no allowlisted negation")
        op = inverse
    fk = _FIELD_KIND_MAP.get(condition.field_kind)
    if fk is None:
        raise ValueError(f"field kind {condition.field_kind!r} is not allowlisted")
    value: object
    if isinstance(condition.value, tuple):
        value = list(condition.value)
    else:
        value = condition.value
    return FilterCondition(
        field=FieldRef(field_kind=fk, set_name=condition.set_name, field_name=condition.field_name),
        operator=op,
        value=value,
        unit=condition.unit,
    )


def compile_predicate_group(group: PredicateGroup) -> FilterGroup:
    """The resolved Boolean tree -> the existing recursive typed `FilterGroup`.

    This is the ONLY place a group predicate becomes SQL filters, and it goes
    through the same compiler/allowlists every other path uses (Task 23 §1)."""
    conditions: list = []
    for node in group.conditions:
        if isinstance(node, PredicateGroup):
            conditions.append(compile_predicate_group(node))
        else:
            conditions.append(compile_condition(node))
    if not conditions:
        raise ValueError("empty condition group")
    return FilterGroup(bool_op=group.bool_op, conditions=conditions)


def _compound_plan(
    predicate: GroupPredicate, source_model_id: int, limit: int
) -> FilterEntitiesPlan:
    """Result class AND every resolved condition, as ONE authoritative plan."""
    if predicate.filters is None:
        raise ValueError("compound predicate carries no filters")
    return FilterEntitiesPlan(
        source_model_id=source_model_id,
        entity_classes=list(expand_entity_classes(list(predicate.ifc_classes))),
        filters=compile_predicate_group(predicate.filters),
        limit=limit,
    )


def execute_predicate(
    session: Session,
    predicate: GroupPredicate,
    source_model_id: int,
    *,
    sample_limit: int = 10,
    viewer_limit: int | None = None,
) -> PredicateResult:
    """Exact count (uncapped) + a bounded representative sample for one predicate.

    Never raises — an unresolvable predicate returns ok=False so a single group
    failing cannot zero the others (Task 17 §4)."""
    try:
        if predicate.kind == PredicateKind.ENTITY_CLASS.value:
            plan = ListEntitiesPlan(
                source_model_id=source_model_id,
                entity_classes=list(expand_entity_classes(list(predicate.ifc_classes))),
                filters=None,
                limit=sample_limit,
            )
            res = execute_sql(
                session,
                SqlOperation.LIST_ENTITIES,
                plan,
                viewer_match_limit=viewer_limit,
                with_viewer_identities=True,
            )
        elif predicate.kind == PredicateKind.COMPOUND.value:
            plan = _compound_plan(predicate, source_model_id, sample_limit)
            res = execute_sql(
                session,
                SqlOperation.FILTER_ENTITIES,
                plan,
                viewer_match_limit=viewer_limit,
                with_viewer_identities=True,
            )
        elif predicate.kind in (
            PredicateKind.ATTRIBUTE_VALUE.value,
            PredicateKind.PROPERTY_VALUE.value,
            PredicateKind.TYPE_VALUE.value,
        ):
            plan = _value_plan(predicate, source_model_id, sample_limit)
            res = execute_sql(
                session,
                SqlOperation.FILTER_ENTITIES,
                plan,
                viewer_match_limit=viewer_limit,
                with_viewer_identities=True,
            )
        elif predicate.kind == PredicateKind.ENTITY_ID_SET.value:
            if not predicate.entity_ids:
                return PredicateResult(ok=True, exact_count=None)
            plan = GetSelectedEntitiesPlan(
                source_model_id=source_model_id, entity_ids=list(predicate.entity_ids)
            )
            res = execute_sql(
                session, SqlOperation.GET_SELECTED_ENTITIES, plan, with_viewer_identities=False
            )
            # RAG-only: bounded candidate set, NOT an exact semantic total.
            return PredicateResult(
                ok=True,
                exact_count=None,
                representative_entities=res.primary_entities[:sample_limit],
                viewer_global_ids=[e.global_id for e in res.primary_entities],
                viewer_matches_total=len(res.primary_entities),
                class_histogram=_hist(res.primary_entities),
            )
        else:
            return PredicateResult(ok=False, error=f"non-executable predicate {predicate.kind}")
    except (FieldNotFoundError, AmbiguousFieldError, ValueError) as exc:
        return PredicateResult(ok=False, error=str(exc)[:200])

    exact = res.viewer_matches_total if res.viewer_matches_total is not None else res.exact_total
    return PredicateResult(
        ok=True,
        exact_count=exact,
        representative_entities=res.primary_entities[:sample_limit],
        viewer_global_ids=res.viewer_global_ids,
        viewer_matches_total=res.viewer_matches_total,
        class_histogram=res.class_histogram,
    )


@dataclass
class IdentityResult:
    global_ids: list[str]
    exact_total: int
    missing_count: int  # matched entities that genuinely lack a usable GlobalId


def _where_args(predicate: GroupPredicate, source_model_id: int):
    """(entity_classes, filters) for `select_viewer_identities` from a predicate.

    Viewer identities are derived from the SAME predicate the answer's exact count
    came from, so highlighted objects can never be a broader set than the answer's
    scope (Task 23 §1)."""
    classes = list(expand_entity_classes(list(predicate.ifc_classes)))
    if predicate.kind == PredicateKind.ENTITY_CLASS.value:
        return classes, None
    if predicate.kind == PredicateKind.COMPOUND.value:
        return classes, _compound_plan(predicate, source_model_id, 1).filters
    plan = _value_plan(predicate, source_model_id, 1)
    return classes, plan.filters


def all_identities(
    session: Session, predicate: GroupPredicate, source_model_id: int
) -> IdentityResult:
    """Complete, UNCAPPED identity hydration for an accepted viewer group
    (Task 17 §9). `select_viewer_identities(limit=None)` returns every match — no
    2,000-ID truncation."""
    from app.query.sql.entities import select_viewer_identities

    if predicate.kind == PredicateKind.ENTITY_ID_SET.value:
        res = execute_predicate(session, predicate, source_model_id, sample_limit=10**9)
        gids = res.viewer_global_ids
        return IdentityResult(global_ids=gids, exact_total=len(gids), missing_count=0)

    classes, filters = _where_args(predicate, source_model_id)
    ident = select_viewer_identities(session, source_model_id, classes, filters, None)
    gids = [r.global_id for r in ident.rows]
    # A matched entity with no usable GlobalId is a distinct condition, not truncation.
    missing = max(0, ident.exact_total - len(gids))
    return IdentityResult(global_ids=gids, exact_total=ident.exact_total, missing_count=missing)


def _hist(entities) -> dict[str, int]:
    out: dict[str, int] = {}
    for e in entities:
        out[e.ifc_class] = out.get(e.ifc_class, 0) + 1
    return out
