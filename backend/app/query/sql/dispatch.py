"""Execute a typed SQL/catalog/relationship/traversal plan and normalize the
result (spec_v005 §7).

This is the deterministic execution glue the orchestrator calls. It maps a
translated `SqlOperation` to the matching function in
`entities`/`relationships`/`catalog`/`graph`, and returns a uniform
`SqlExecResult` carrying: ordered canonical entity ids (for combination),
compact hydrated evidence (never full canonical JSON), non-entity facts
(counts/aggregates/groups/missing), and catalog model candidates. Viewer-action
construction is the orchestrator's job, not this module's.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from app.api.schemas.response import (
    ModelCandidate,
    PrimaryEntityResult,
    RelationshipResult,
)
from app.config import trace
from app.config.settings import get_settings
from app.query.graph.hydration import hydrate_traversal
from app.query.graph.traversal import traverse
from app.query.sql import catalog as catalog_ops
from app.query.sql import entities as entity_ops
from app.query.sql import relationships as rel_ops
from app.query.sql.hydration import hydrate_primary_entity, hydrate_relationship
from app.query.sql.schemas import SqlOperation
from app.shared.types import ModelStatus

# Entity operations whose matching set the viewer should be able to highlight
# (task13 §2). Counts and aggregates previously produced no identities at all,
# so "How many doors?" returned an exact number and highlighted nothing.
_VIEWER_IDENTITY_OPS = frozenset(
    {
        SqlOperation.COUNT_ENTITIES,
        SqlOperation.AGGREGATE_ENTITIES,
        SqlOperation.LIST_ENTITIES,
        SqlOperation.FILTER_ENTITIES,
    }
)


@dataclass
class SqlExecResult:
    operation: str
    entity_ids: list[int] = field(default_factory=list)
    primary_entities: list[PrimaryEntityResult] = field(default_factory=list)
    context_entities: list = field(default_factory=list)
    relationships: list[RelationshipResult] = field(default_factory=list)
    facts: dict[str, Any] | None = None
    exact_total: int | None = None
    model_candidates: list[ModelCandidate] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    # --- Viewer match identities (task13 §2) ---
    # Independent of `primary_entities` (bounded to the 50-item LLM evidence
    # limit) and of `exact_total` (never capped by the application).
    viewer_global_ids: list[str] = field(default_factory=list)
    viewer_matches_total: int | None = None
    viewer_matches_truncated: bool = False
    class_histogram: dict[str, int] = field(default_factory=dict)


def _to_candidate(row: Any) -> ModelCandidate:
    status = None
    raw_status = getattr(row, "status", None)
    if raw_status in {s.value for s in ModelStatus}:
        status = ModelStatus(raw_status)
    tags = getattr(row, "tags", None)
    return ModelCandidate(
        source_model_id=row.source_model_id,
        display_name=getattr(row, "display_name", None),
        version_label=getattr(row, "version_label", None),
        is_current=getattr(row, "is_current", None),
        status=status,
        tags=list(tags) if isinstance(tags, list) else [],
    )


def execute_catalog(session: Session, operation: SqlOperation, plan: Any) -> SqlExecResult:
    if operation is SqlOperation.LIST_MODELS:
        rows = catalog_ops.list_models(session, plan)
    elif operation is SqlOperation.FILTER_MODELS:
        rows = catalog_ops.filter_models(session, plan)
    elif operation is SqlOperation.LIST_MODEL_VERSIONS:
        rows = catalog_ops.list_model_versions(session, plan)
    elif operation is SqlOperation.RANK_MODELS_BY_ENTITY_COUNT:
        rows = catalog_ops.rank_models_by_entity_count(session, plan)
    elif operation is SqlOperation.GET_MODEL_METADATA:
        rows = [catalog_ops.get_model_metadata(session, plan)]
    else:  # pragma: no cover - guarded by translate
        raise ValueError(f"not a catalog operation: {operation}")
    candidates = [_to_candidate(r) for r in rows]
    return SqlExecResult(
        operation=operation.value,
        model_candidates=candidates,
        exact_total=len(candidates),
        facts={"model_count": len(candidates)},
    )


def _attach_viewer_identities(
    session: Session, plan: Any, res: SqlExecResult, viewer_match_limit: int | None
) -> None:
    """Identity-only retrieval over the same filtered set (task13 §2).

    Runs for counts/aggregates/lists alike so a count question highlights the
    objects it counted. The exact total is never reduced by viewer truncation,
    and the class summary is computed over the full matching set (not the
    truncated slice), so both stay exact above the cap.
    """
    limit = (
        viewer_match_limit
        if viewer_match_limit is not None
        else (get_settings().max_viewer_match_ids)
    )
    ident = entity_ops.select_viewer_identities(
        session, plan.source_model_id, plan.entity_classes, plan.filters, limit
    )
    res.viewer_global_ids = [r.global_id for r in ident.rows]
    res.viewer_matches_total = ident.exact_total
    res.viewer_matches_truncated = ident.truncated
    res.class_histogram = entity_ops.count_by_class(
        session, plan.source_model_id, plan.entity_classes, plan.filters
    )
    if ident.truncated:
        res.warnings.append(
            f"{ident.exact_total} objects match; the viewer received the first "
            f"{len(ident.rows)} (the exact total above is unaffected)"
        )


def execute_sql(
    session: Session,
    operation: SqlOperation,
    plan: Any,
    viewer_match_limit: int | None = None,
    with_viewer_identities: bool = True,
) -> SqlExecResult:
    """Run one active-model SQL/relationship/traversal operation.

    Wraps the operation in an opt-in trace record (task13 §1) and attaches
    viewer match identities for entity operations (task13 §2).

    `with_viewer_identities=False` is used by the hybrid orchestrator: there the
    highlighted set is the *combined* SQL/RAG outcome, so this path's raw match
    set would be both wasted work and a misleading truncation warning.
    """
    with trace.trace_sql_operation(operation.value) as rec:
        res = _execute_sql_operation(session, operation, plan)
        if with_viewer_identities and operation in _VIEWER_IDENTITY_OPS:
            _attach_viewer_identities(session, plan, res, viewer_match_limit)
        # Report the TRUE match total, not `exact_total` — for list/filter ops the
        # latter is only the plan-limited evidence row count, which would make the
        # trace understate the result (e.g. "50" for 880 matching walls).
        rec.exact_count = (
            res.viewer_matches_total if res.viewer_matches_total is not None else res.exact_total
        )
        rec.row_count = len(res.viewer_global_ids) or len(res.primary_entities) or None
        rec.result_histogram = res.class_histogram
        return res


def _execute_sql_operation(session: Session, operation: SqlOperation, plan: Any) -> SqlExecResult:
    op = operation
    if op is SqlOperation.COUNT_ENTITIES:
        n = entity_ops.count_entities(session, plan)
        return SqlExecResult(operation=op.value, facts={"count": n}, exact_total=n)

    if op in (SqlOperation.LIST_ENTITIES, SqlOperation.FILTER_ENTITIES):
        rows = (
            entity_ops.filter_entities(session, plan)
            if op is SqlOperation.FILTER_ENTITIES
            else entity_ops.list_entities(session, plan)
        )
        primary = [hydrate_primary_entity(r) for r in rows]
        res = SqlExecResult(
            operation=op.value,
            entity_ids=[r.id for r in rows],
            primary_entities=primary,
            exact_total=len(rows),
            facts={"returned": len(rows), "limit": plan.limit},
        )
        if len(rows) >= plan.limit:
            res.warnings.append(
                f"result hit the limit of {plan.limit}; more matching entities may exist"
            )
        return res

    if op is SqlOperation.GET_ENTITY:
        row = entity_ops.get_entity(session, plan)
        return SqlExecResult(
            operation=op.value,
            entity_ids=[row.id],
            primary_entities=[hydrate_primary_entity(row)],
            exact_total=1,
        )

    if op is SqlOperation.GET_SELECTED_ENTITIES:
        rows = entity_ops.get_selected_entities(session, plan)
        return SqlExecResult(
            operation=op.value,
            entity_ids=[r.id for r in rows],
            primary_entities=[hydrate_primary_entity(r) for r in rows],
            exact_total=len(rows),
        )

    if op is SqlOperation.AGGREGATE_ENTITIES:
        agg = entity_ops.aggregate_entities(session, plan)
        return SqlExecResult(
            operation=op.value,
            facts={
                "function": agg.function,
                "value": agg.value,
                "matched_count": agg.matched_count,
                "coverage_count": agg.coverage_count,
                "unit": plan.unit,
            },
            exact_total=agg.matched_count,
            warnings=list(agg.warnings),
        )

    if op is SqlOperation.GROUP_ENTITIES:
        buckets = entity_ops.group_entities(session, plan)
        return SqlExecResult(
            operation=op.value,
            facts={
                "function": plan.function,
                "groups": [{"key": b.key, "value": b.value, "count": b.count} for b in buckets],
            },
            exact_total=len(buckets),
        )

    if op is SqlOperation.FIND_MISSING_VALUES:
        report = entity_ops.find_missing_values(session, plan)
        return SqlExecResult(
            operation=op.value,
            facts={
                "field": report.field_name,
                "matched_count": report.matched_count,
                "state_counts": report.state_counts,
            },
            exact_total=report.matched_count,
        )

    if op is SqlOperation.LIST_RELATIONSHIPS:
        rows = rel_ops.list_relationships(session, plan)
        return SqlExecResult(
            operation=op.value,
            relationships=[hydrate_relationship(r) for r in rows],
            exact_total=len(rows),
        )

    if op is SqlOperation.GET_RELATIONSHIP:
        row = rel_ops.get_relationship(session, plan)
        return SqlExecResult(
            operation=op.value,
            relationships=[hydrate_relationship(row)],
            exact_total=1,
        )

    if op is SqlOperation.GET_RELATIONSHIP_MEMBERS:
        members = rel_ops.get_relationship_members(session, plan)
        return SqlExecResult(
            operation=op.value,
            facts={
                "member_count": len(members),
                "members": [
                    {
                        "role": m.role,
                        "entity_id": m.entity_id,
                        "endpoint_ifc_class": m.endpoint_ifc_class,
                        "endpoint_name": m.endpoint_name,
                    }
                    for m in members[:50]
                ],
            },
            exact_total=len(members),
        )

    if op is SqlOperation.TRAVERSE_RELATIONSHIPS:
        result = traverse(session, plan)
        primary, context, _viewer = hydrate_traversal(session, plan.source_model_id, result)
        return SqlExecResult(
            operation=op.value,
            entity_ids=[p.entity_id for p in primary],
            primary_entities=primary,
            context_entities=context,
            exact_total=len(result.primary_entity_ids) + len(result.context_entity_ids),
            facts={
                "hops": len(result.hops),
                "context_total": len(result.context_entity_ids),
            },
            warnings=list(result.warnings),
        )

    raise ValueError(f"unsupported sql operation {op}")  # pragma: no cover
