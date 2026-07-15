"""Model-catalog operations (spec_v002 §4.1, spec_v003 §5).

Catalog rows are ordinary typed columns (not canonical_json), so filtering
here uses a small dedicated column allowlist rather than the JSONB-aware
`compiler.py` machinery built for `ifc_entities`. Only a flat AND of
conditions is supported for `filter_models` — catalog metadata is small and
manually curated, so the bounded recursive expression tree used for entity
filters would be over-engineering here.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy import Table
from sqlalchemy.orm import Session

from app.db.models import IfcEntity, IfcSourceModel, ModelFamily, SourceModelCatalogEntry
from app.query.sql.errors import FieldNotFoundError, UnsupportedFilterOperatorError
from app.query.sql.schemas import (
    FieldKind,
    FilterGroup,
    FilterModelsPlan,
    GetModelMetadataPlan,
    ListModelsPlan,
    ListModelVersionsPlan,
    Operator,
    RankModelsByEntityCountPlan,
)
from app.shared.errors import ModelNotFoundError

_SM: Table = IfcSourceModel.__table__
_CE: Table = SourceModelCatalogEntry.__table__
_MF: Table = ModelFamily.__table__

_CATALOG_FILTER_COLUMNS: dict[str, sa.ColumnElement] = {
    "status": _CE.c.status,
    "project_type": _CE.c.project_type,
    "discipline": _CE.c.discipline,
    "family_key": _MF.c.family_key,
    "display_name": _CE.c.display_name,
    "version_label": _CE.c.version_label,
    "is_current": _CE.c.is_current,
}
# Boolean catalog columns: values are coerced to real booleans before comparison.
_CATALOG_BOOLEAN_COLUMNS = {"is_current"}

# Public allowlist so the planner-plan translator can reject unknown catalog
# filter fields up front (repairable), instead of crashing at execution.
CATALOG_FILTER_FIELDS = frozenset(_CATALOG_FILTER_COLUMNS)


def _base_catalog_select() -> sa.Select:
    return sa.select(
        _SM.c.id.label("source_model_id"),
        _SM.c.file_name,
        _SM.c.ifc_schema,
        _CE.c.display_name,
        _CE.c.version_label,
        _CE.c.version_order,
        _CE.c.is_current,
        _CE.c.status,
        _CE.c.project_type,
        _CE.c.discipline,
        _CE.c.tags,
        _CE.c.description,
        _CE.c.viewer_source_location,
        _MF.c.family_key,
    ).select_from(
        _SM.outerjoin(_CE, _CE.c.source_model_id == _SM.c.id).outerjoin(
            _MF, _MF.c.id == _CE.c.model_family_id
        )
    )


def list_models(session: Session, plan: ListModelsPlan) -> list:
    stmt = _base_catalog_select().order_by(_SM.c.id).limit(plan.limit)
    return session.execute(stmt).all()


def filter_models(session: Session, plan: FilterModelsPlan) -> list:
    stmt = _base_catalog_select()
    if plan.filters is not None:
        stmt = stmt.where(_build_catalog_filter_expr(plan.filters))
    stmt = stmt.order_by(_SM.c.id).limit(plan.limit)
    return session.execute(stmt).all()


def _build_catalog_filter_expr(group: FilterGroup) -> sa.ColumnElement:
    exprs = []
    for node in group.conditions:
        if not hasattr(node, "field"):
            raise UnsupportedFilterOperatorError(
                "nested filter groups are not supported for filter_models"
            )
        if (
            node.field.field_kind is not FieldKind.ATTRIBUTE
            or node.field.field_name not in _CATALOG_FILTER_COLUMNS
        ):
            raise FieldNotFoundError(f"unsupported catalog filter field {node.field.field_name!r}")
        column = _CATALOG_FILTER_COLUMNS[node.field.field_name]
        exprs.append(_catalog_condition(column, node.operator, node.value))
    return sa.and_(*exprs) if group.bool_op == "and" else sa.or_(*exprs)


def _catalog_condition(
    column: sa.ColumnElement, operator: Operator, value: object
) -> sa.ColumnElement:
    if operator in (Operator.EQ, Operator.EXACT):
        return column == value
    if operator is Operator.NE:
        return column != value
    if operator is Operator.CASE_INSENSITIVE_EXACT:
        return sa.func.lower(column) == sa.func.lower(sa.cast(value, sa.Text))
    if operator is Operator.CONTAINS:
        return (
            sa.func.strpos(sa.func.lower(column), sa.func.lower(sa.cast(str(value), sa.Text))) > 0
        )
    if operator is Operator.IN:
        return column.in_(value)
    if operator is Operator.NOT_IN:
        return sa.and_(column.is_not(None), column.not_in(value))
    raise UnsupportedFilterOperatorError(f"unsupported catalog filter operator {operator.value!r}")


def list_model_versions(session: Session, plan: ListModelVersionsPlan) -> list:
    stmt = (
        _base_catalog_select()
        .where(_MF.c.family_key == plan.family_key)
        .order_by(_CE.c.version_order)
    )
    return session.execute(stmt).all()


def rank_models_by_entity_count(session: Session, plan: RankModelsByEntityCountPlan) -> list:
    ie = IfcEntity.__table__
    counts = (
        sa.select(ie.c.source_model_id, sa.func.count().label("entity_count"))
        .where(ie.c.ifc_class == plan.entity_class)
        .group_by(ie.c.source_model_id)
        .subquery()
    )
    base = _base_catalog_select().subquery()
    order = (
        counts.c.entity_count.desc() if plan.direction == "desc" else counts.c.entity_count.asc()
    )
    stmt = (
        sa.select(base, counts.c.entity_count)
        .select_from(base.join(counts, counts.c.source_model_id == base.c.source_model_id))
        .order_by(order)
        .limit(plan.limit)
    )
    return session.execute(stmt).all()


def get_model_metadata(session: Session, plan: GetModelMetadataPlan):
    stmt = _base_catalog_select().where(_SM.c.id == plan.source_model_id)
    row = session.execute(stmt).first()
    if row is None:
        raise ModelNotFoundError(f"source_model_id {plan.source_model_id} does not exist")
    return row


# ---------------------------------------------------------------------------
# Narrow read-only selectors for the frontend viewer contract (Task 10).
# Bounded field allowlists only — no file paths, canonical JSON, or credentials.
# ---------------------------------------------------------------------------


def list_selector_models(session: Session) -> list:
    """Bounded model list for the display-name selector (spec_v006 §10.1).

    Returns only (source_model_id, source_fingerprint, display_name, status),
    ordered deterministically by id. No file path, canonical JSON, or ingestion
    internals are selected.
    """
    stmt = (
        sa.select(
            _SM.c.id.label("source_model_id"),
            _SM.c.file_fingerprint.label("source_fingerprint"),
            _CE.c.display_name,
            _CE.c.status,
        )
        .select_from(_SM.outerjoin(_CE, _CE.c.source_model_id == _SM.c.id))
        .order_by(_SM.c.id)
    )
    return session.execute(stmt).all()


def get_model_asset_identity(session: Session, source_model_id: int):
    """Fetch just the identity a viewer-asset/resolve request needs.

    Returns (source_model_id, source_fingerprint, status) or None if the model
    does not exist. Used to verify model existence and derive the expected
    artifact path from database identity only (Task 10 §3/§4).
    """
    stmt = (
        sa.select(
            _SM.c.id.label("source_model_id"),
            _SM.c.file_fingerprint.label("source_fingerprint"),
            _CE.c.status,
        )
        .select_from(_SM.outerjoin(_CE, _CE.c.source_model_id == _SM.c.id))
        .where(_SM.c.id == source_model_id)
    )
    return session.execute(stmt).first()
