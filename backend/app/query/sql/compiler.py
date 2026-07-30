"""The sole builder of parameterized SQL for the query path (spec_v003 §7, §13).

Every function here takes already-validated typed plans (`query.sql.schemas`)
and already-resolved fields (`query.sql.field_registry`) and returns
SQLAlchemy Core constructs built entirely from bound parameters. No route,
handler, or LLM-facing module is permitted to build SQL text directly —
`entities.py`/`relationships.py`/`catalog.py`/`aggregates.py` all go through
this module.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy import ColumnElement
from sqlalchemy.dialects.postgresql import ARRAY, TEXT
from sqlalchemy.orm import Session

from app.query.sql.errors import UnsupportedFilterOperatorError
from app.query.sql.field_registry import ResolvedField, resolve_field
from app.query.sql.schemas import FilterCondition, FilterGroup, Operator

_MAX_LIKE_VALUE_LEN = 500


def path_array_param(path: tuple[str, ...]) -> ColumnElement:
    """A bound text[] parameter for #> / #>> path operators. Never string-concatenated."""
    return sa.cast(sa.bindparam(None, list(path), type_=ARRAY(TEXT)), ARRAY(TEXT))


def resolved_text_expr(resolved: ResolvedField, entities_table: sa.Table) -> ColumnElement:
    """The field's value as text, regardless of storage location."""
    if resolved.access_kind == "column":
        col = entities_table.c[resolved.column_name]
        return sa.cast(col, TEXT)
    return entities_table.c.canonical_json.op("#>>")(path_array_param(resolved.json_path))


def resolved_parent_has_key_expr(
    resolved: ResolvedField, entities_table: sa.Table
) -> ColumnElement:
    """True if the immediate parent JSONB object actually contains the leaf key
    (used to distinguish ABSENT from PRESENT_NULL — spec_v003 §9). Always
    False (never NULL) for direct-column attribute fields, which are never absent."""
    if resolved.access_kind == "column":
        return sa.literal(True)
    parent_path = resolved.json_path[:-1]
    last_key = resolved.json_path[-1]
    if not parent_path:
        parent = entities_table.c.canonical_json
    else:
        parent = entities_table.c.canonical_json.op("#>")(path_array_param(parent_path))
    return sa.func.coalesce(parent.op("?")(sa.bindparam(None, last_key)), False)


def resolved_numeric_expr(resolved: ResolvedField, entities_table: sa.Table) -> ColumnElement:
    """The field's RAW stored value as a double precision number, or NULL.

    One expression for every field kind, and no conversion anywhere (task27
    §4.3): the corpus keeps the units the IFC used, so calculating means casting
    the number that is already there. A value that is not numeric text yields
    NULL, which keeps `count(numeric_expr)` an exact coverage count.

    Unit safety is decided BEFORE compilation, from the semantic manifest, by
    `app.query.semantic.units.decide_unit`. Two competing unit paths — one here
    rewriting values into millimetres, one there comparing symbols — is exactly
    what §4.3 forbids, so this function deliberately knows nothing about units.
    """
    text_expr = resolved_text_expr(resolved, entities_table)
    return sa.case((_is_numeric_text(text_expr), sa.cast(text_expr, sa.Double)), else_=None)


def _is_numeric_text(text_expr: ColumnElement) -> ColumnElement:
    return text_expr.op("~")(r"^-?\d+(\.\d+)?$")


def _has_usable_value_expr(resolved: ResolvedField, entities_table: sa.Table) -> ColumnElement:
    """True when the field actually carries a value on this row.

    Deliberately the exact complement of the three missing states
    `find_missing_values` reports (spec_v003 §9): the leaf key must be present on
    its parent object, and the value must be neither NULL nor the empty string.
    Using one definition for both keeps "how many walls have a fire rating" and
    "which walls are missing one" partitioning the same set — if they disagreed,
    the two counts could not be reconciled by anyone reading the answer.
    """
    parent_has_key = resolved_parent_has_key_expr(resolved, entities_table)
    leaf_text = resolved_text_expr(resolved, entities_table)
    return sa.and_(parent_has_key, leaf_text.is_not(None), leaf_text != "")


def _scalar_bind(value: Any) -> ColumnElement:
    return sa.bindparam(None, value)


def build_condition_expr(
    session: Session,
    source_model_id: int,
    node: FilterCondition | FilterGroup,
    entities_table: sa.Table,
) -> ColumnElement:
    """Recursively compile a bounded filter tree into a SQLAlchemy boolean expression.

    Every FieldRef is resolved through field_registry first (raising
    FieldNotFoundError/AmbiguousFieldError up front, before any SQL runs).
    Every value is a bound parameter — never string-concatenated.
    """
    if isinstance(node, FilterGroup):
        sub_exprs = [
            build_condition_expr(session, source_model_id, c, entities_table)
            for c in node.conditions
        ]
        return sa.and_(*sub_exprs) if node.bool_op == "and" else sa.or_(*sub_exprs)

    resolved = resolve_field(session, source_model_id, node.field)
    op = node.operator
    value = node.value

    if op in (Operator.IS_PRESENT, Operator.IS_MISSING):
        present = _has_usable_value_expr(resolved, entities_table)
        return present if op is Operator.IS_PRESENT else sa.not_(present)

    if op in (
        Operator.EXACT,
        Operator.CASE_INSENSITIVE_EXACT,
        Operator.CONTAINS,
        Operator.STARTS_WITH,
    ):
        text_expr = resolved_text_expr(resolved, entities_table)
        str_value = str(value)[:_MAX_LIKE_VALUE_LEN]
        if op is Operator.EXACT:
            return text_expr == _scalar_bind(str_value)
        if op is Operator.CASE_INSENSITIVE_EXACT:
            return sa.func.lower(text_expr) == sa.func.lower(_scalar_bind(str_value))
        if op is Operator.CONTAINS:
            return (
                sa.func.strpos(sa.func.lower(text_expr), sa.func.lower(_scalar_bind(str_value))) > 0
            )
        return sa.func.strpos(sa.func.lower(text_expr), sa.func.lower(_scalar_bind(str_value))) == 1

    if op is Operator.IN:
        if all(isinstance(v, str) for v in value):
            text_expr = resolved_text_expr(resolved, entities_table)
            return text_expr.in_([str(v) for v in value])
        numeric_expr = resolved_numeric_expr(resolved, entities_table)
        return numeric_expr.in_([float(v) for v in value])

    if op is Operator.NOT_IN:
        if all(isinstance(v, str) for v in value):
            text_expr = resolved_text_expr(resolved, entities_table)
            return sa.and_(text_expr.is_not(None), text_expr.not_in([str(v) for v in value]))
        numeric_expr = resolved_numeric_expr(resolved, entities_table)
        return sa.and_(numeric_expr.is_not(None), numeric_expr.not_in([float(v) for v in value]))

    if op is Operator.BETWEEN:
        numeric_expr = resolved_numeric_expr(resolved, entities_table)
        low, high = value
        return numeric_expr.between(float(low), float(high))

    if isinstance(value, str):
        text_expr = resolved_text_expr(resolved, entities_table)
        return _compare(text_expr, op, _scalar_bind(value))

    numeric_expr = resolved_numeric_expr(resolved, entities_table)
    return _compare(numeric_expr, op, _scalar_bind(float(value)))


def _compare(expr: ColumnElement, op: Operator, bound: ColumnElement) -> ColumnElement:
    if op is Operator.EQ:
        return expr == bound
    if op is Operator.NE:
        return expr != bound
    if op is Operator.GT:
        return expr > bound
    if op is Operator.GTE:
        return expr >= bound
    if op is Operator.LT:
        return expr < bound
    if op is Operator.LTE:
        return expr <= bound
    raise UnsupportedFilterOperatorError(f"unsupported operator {op.value!r} for scalar comparison")
