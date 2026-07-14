"""Direct relationship listing/lookup (spec_v003 §12). Endpoint traversal
across depth lives in query.graph.traversal; this module covers direct
list/get/get_members only, always scoped by source_model_id."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.orm import Session

from bim_rag.schema.models import DbIfcRelationship, RelationshipMember
from query.sql.errors import UnknownEntityOrRelationshipError
from query.sql.schemas import GetRelationshipMembersPlan, GetRelationshipPlan, ListRelationshipsPlan

_RT = DbIfcRelationship.__table__
_MT = RelationshipMember.__table__


def _base_where(source_model_id: int, relationship_classes: list[str]) -> sa.ColumnElement:
    where = _RT.c.source_model_id == source_model_id
    if relationship_classes:
        where = sa.and_(where, _RT.c.ifc_class.in_(relationship_classes))
    return where


def list_relationships(session: Session, plan: ListRelationshipsPlan):
    stmt = (
        sa.select(_RT.c.id, _RT.c.global_id, _RT.c.ifc_class, _RT.c.name)
        .where(_base_where(plan.source_model_id, plan.relationship_classes))
        .order_by(_RT.c.id)
        .limit(plan.limit)
        .offset(plan.offset)
    )
    return session.execute(stmt).all()


def get_relationship(session: Session, plan: GetRelationshipPlan):
    where = _RT.c.source_model_id == plan.source_model_id
    if plan.relationship_id is not None:
        where = sa.and_(where, _RT.c.id == plan.relationship_id)
    else:
        where = sa.and_(where, _RT.c.global_id == plan.global_id)
    row = session.execute(
        sa.select(_RT.c.id, _RT.c.global_id, _RT.c.ifc_class, _RT.c.name).where(where)
    ).first()
    if row is None:
        raise UnknownEntityOrRelationshipError(
            f"relationship not found for source_model_id={plan.source_model_id}"
        )
    return row


def get_relationship_members(session: Session, plan: GetRelationshipMembersPlan):
    exists = session.execute(
        sa.select(sa.func.count())
        .select_from(_RT)
        .where(_RT.c.id == plan.relationship_id, _RT.c.source_model_id == plan.source_model_id)
    ).scalar_one()
    if not exists:
        raise UnknownEntityOrRelationshipError(
            f"relationship {plan.relationship_id} not found for "
            f"source_model_id={plan.source_model_id}"
        )
    stmt = (
        sa.select(
            _MT.c.id,
            _MT.c.role,
            _MT.c.member_order,
            _MT.c.entity_id,
            _MT.c.endpoint_global_id,
            _MT.c.endpoint_ifc_class,
            _MT.c.endpoint_name,
        )
        .where(
            _MT.c.relationship_id == plan.relationship_id,
            _MT.c.source_model_id == plan.source_model_id,
        )
        .order_by(_MT.c.role, _MT.c.member_order)
    )
    return session.execute(stmt).all()
