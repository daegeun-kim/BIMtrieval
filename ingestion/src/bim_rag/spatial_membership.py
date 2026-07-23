"""Normalized effective spatial membership (task26 §4.2).

Populates `entity_spatial_memberships` deterministically from the committed
relationship rows of ONE source model. No IFC re-parsing, no LLM, no
model-specific rules: the projection is a bounded upward walk over the two
spatial parent-edge kinds IFC actually uses —

- `IfcRelContainedInSpatialStructure`: RelatedElements -> RelatingStructure
- `IfcRelAggregates`:                  RelatedObjects  -> RelatingObject

An entity's membership in a storey is every bounded path (max 3 hops) from the
entity up those edges to an `IfcBuildingStorey`. This resolves both the direct
scalar case (element contained in storey) and the representation models 2 and 3
use (space aggregated to storey; element contained in a space that aggregates
to a storey) with one rule.

Idempotent per model: rows for the model are replaced inside one transaction.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

__all__ = ["populate_spatial_memberships", "MAX_MEMBERSHIP_HOPS"]

#: Bounded nested-path depth. 1 = direct containment/aggregation,
#: 2 = element -> space -> storey. 3 covers one extra grouping level.
MAX_MEMBERSHIP_HOPS = 3

#: The two IFC spatial parent-edge kinds, by relationship class.
_PARENT_EDGE_SQL = """
    SELECT child.entity_id        AS child_entity_id,
           child.endpoint_global_id AS child_global_id,
           child.endpoint_ifc_class AS child_class,
           child.role             AS child_role,
           parent.entity_id       AS parent_entity_id,
           parent.endpoint_global_id AS parent_global_id,
           parent.endpoint_ifc_class AS parent_class,
           parent.role            AS parent_role,
           r.id                   AS relationship_id,
           CASE r.ifc_class
             WHEN 'IfcRelContainedInSpatialStructure' THEN 'contained'
             ELSE 'aggregated'
           END                    AS kind
    FROM ifc_relationships r
    JOIN relationship_members child
      ON child.relationship_id = r.id
     AND child.role IN ('RelatedElements', 'RelatedObjects')
    JOIN relationship_members parent
      ON parent.relationship_id = r.id
     AND parent.role IN ('RelatingStructure', 'RelatingObject')
    WHERE r.source_model_id = :sid
      AND r.ifc_class IN ('IfcRelContainedInSpatialStructure', 'IfcRelAggregates')
      AND child.endpoint_global_id IS NOT NULL
      AND parent.endpoint_global_id IS NOT NULL
"""

_POPULATE_SQL = f"""
WITH RECURSIVE parent_edge AS ({_PARENT_EDGE_SQL}),
climb AS (
    SELECT e.child_entity_id      AS entity_id,
           e.child_global_id      AS entity_global_id,
           e.parent_entity_id,
           e.parent_global_id,
           e.parent_class,
           e.relationship_id      AS source_relationship_id,
           e.kind                 AS path_kinds,
           (e.kind || ':' || e.child_role || '->' || e.parent_role) AS provenance,
           1                      AS hop_count
    FROM parent_edge e
    UNION ALL
    SELECT c.entity_id,
           c.entity_global_id,
           e.parent_entity_id,
           e.parent_global_id,
           e.parent_class,
           c.source_relationship_id,
           c.path_kinds || '>' || e.kind,
           c.provenance || ' > ' || (e.kind || ':' || e.child_role || '->' || e.parent_role),
           c.hop_count + 1
    FROM climb c
    JOIN parent_edge e
      ON e.child_global_id = c.parent_global_id
    WHERE c.hop_count < :max_hops
      AND c.parent_class <> 'IfcBuildingStorey'
),
memberships AS (
    -- Deduplicate corroborating identical paths deterministically: keep the
    -- lowest source relationship id per (entity, storey, path signature).
    SELECT DISTINCT ON (entity_global_id, parent_global_id, path_kinds)
           entity_id,
           entity_global_id,
           parent_entity_id   AS storey_entity_id,
           parent_global_id   AS storey_global_id,
           source_relationship_id,
           path_kinds         AS source_kind,
           hop_count,
           provenance
    FROM climb
    WHERE parent_class = 'IfcBuildingStorey'
      AND entity_global_id <> parent_global_id
    ORDER BY entity_global_id, parent_global_id, path_kinds,
             hop_count, source_relationship_id
),
annotated AS (
    SELECT m.*, s.distinct_storeys, s.min_hops
    FROM memberships m
    JOIN (
        SELECT entity_global_id,
               count(DISTINCT storey_global_id) AS distinct_storeys,
               min(hop_count) AS min_hops
        FROM memberships
        GROUP BY entity_global_id
    ) s USING (entity_global_id)
)
INSERT INTO entity_spatial_memberships (
    source_model_id, entity_id, entity_global_id, storey_entity_id,
    storey_global_id, source_relationship_id, source_kind, hop_count,
    resolution_status, is_primary, provenance
)
SELECT :sid,
       a.entity_id,
       a.entity_global_id,
       a.storey_entity_id,
       a.storey_global_id,
       a.source_relationship_id,
       a.source_kind,
       a.hop_count,
       CASE
         WHEN a.entity_id IS NULL OR a.storey_entity_id IS NULL THEN 'dangling'
         WHEN a.distinct_storeys > 1 THEN 'ambiguous'
         ELSE 'resolved'
       END,
       (a.distinct_storeys = 1 AND a.hop_count = a.min_hops),
       a.provenance
FROM annotated a
ON CONFLICT ON CONSTRAINT uq_esm_model_entity_storey_kind DO NOTHING
"""


def populate_spatial_memberships(session: Session, source_model_id: int) -> dict[str, Any]:
    """Replace and repopulate one model's spatial memberships. Returns stats."""
    session.execute(
        text("DELETE FROM entity_spatial_memberships WHERE source_model_id = :sid"),
        {"sid": source_model_id},
    )
    session.execute(
        text(_POPULATE_SQL),
        {"sid": source_model_id, "max_hops": MAX_MEMBERSHIP_HOPS},
    )
    stats = session.execute(
        text(
            "SELECT count(*) AS rows,"
            " count(DISTINCT entity_global_id) AS entities,"
            " count(DISTINCT storey_global_id) AS storeys,"
            " count(*) FILTER (WHERE resolution_status = 'resolved') AS resolved,"
            " count(*) FILTER (WHERE resolution_status = 'dangling') AS dangling,"
            " count(*) FILTER (WHERE resolution_status = 'ambiguous') AS ambiguous,"
            " count(*) FILTER (WHERE hop_count > 1) AS nested"
            " FROM entity_spatial_memberships WHERE source_model_id = :sid"
        ),
        {"sid": source_model_id},
    ).mappings().one()
    return dict(stats)
