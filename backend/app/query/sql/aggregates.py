"""Coverage-aware exact aggregation (spec_v003 §10, spec_v002 §9.2).

Only aggregates numeric values whose semantic field and normalized unit are
known, over the full matching set (not a sample). Reports missing coverage
explicitly rather than implying completeness — "42% average X (based on 12
of 50 matching entities)" not a silently-partial average presented as whole.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.query.sql.compiler import resolved_numeric_expr, resolved_text_expr
from app.query.sql.field_registry import ResolvedField

_AGG_FUNCS = {"sum": sa.func.sum, "min": sa.func.min, "max": sa.func.max, "average": sa.func.avg}


@dataclass
class AggregateResult:
    function: str
    value: float | int | None
    matched_count: int
    coverage_count: int
    warnings: list[str] = field(default_factory=list)


@dataclass
class GroupBucket:
    key: str | None
    value: float | int | None
    count: int


def compute_aggregate(
    session: Session,
    entities_table: sa.Table,
    base_where: sa.ColumnElement,
    function: str,
    resolved_field: ResolvedField | None,
    unit: str | None,
) -> AggregateResult:
    matched_count = session.execute(
        sa.select(sa.func.count()).select_from(entities_table).where(base_where)
    ).scalar_one()

    if function == "count":
        return AggregateResult(
            function="count",
            value=matched_count,
            matched_count=matched_count,
            coverage_count=matched_count,
        )

    assert resolved_field is not None
    numeric_expr = resolved_numeric_expr(resolved_field, entities_table, unit)
    agg_func = _AGG_FUNCS[function]

    row = session.execute(
        sa.select(agg_func(numeric_expr), sa.func.count(numeric_expr))
        .select_from(entities_table)
        .where(base_where)
    ).one()
    value, coverage_count = row[0], row[1]
    warnings: list[str] = []
    if coverage_count < matched_count:
        warnings.append(
            f"only {coverage_count} of {matched_count} matching entities have a usable numeric "
            "value for this field; this aggregate does not imply completeness"
        )
    return AggregateResult(
        function=function,
        value=float(value) if value is not None else None,
        matched_count=matched_count,
        coverage_count=coverage_count,
        warnings=warnings,
    )


def compute_group_by(
    session: Session,
    entities_table: sa.Table,
    base_where: sa.ColumnElement,
    group_field: ResolvedField,
    function: str,
    agg_field: ResolvedField | None,
    unit: str | None,
    limit: int,
) -> list[GroupBucket]:
    key_expr = resolved_text_expr(group_field, entities_table)

    if function == "count":
        stmt = (
            sa.select(key_expr.label("key"), sa.func.count().label("cnt"))
            .select_from(entities_table)
            .where(base_where)
            .group_by(key_expr)
            .order_by(sa.func.count().desc())
            .limit(limit)
        )
        rows = session.execute(stmt).all()
        return [GroupBucket(key=r.key, value=r.cnt, count=r.cnt) for r in rows]

    assert agg_field is not None
    numeric_expr = resolved_numeric_expr(agg_field, entities_table, unit)
    agg_func = _AGG_FUNCS[function]
    stmt = (
        sa.select(
            key_expr.label("key"), agg_func(numeric_expr).label("val"), sa.func.count().label("cnt")
        )
        .select_from(entities_table)
        .where(base_where)
        .group_by(key_expr)
        .order_by(sa.func.count().desc())
        .limit(limit)
    )
    rows = session.execute(stmt).all()
    return [
        GroupBucket(key=r.key, value=(float(r.val) if r.val is not None else None), count=r.cnt)
        for r in rows
    ]
