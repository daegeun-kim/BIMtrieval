"""One authoritative execution per answer part (Task 24 §5).

Retrieval mode is DERIVED from the bound operation, never chosen by the model
(§5.1). There are no sql/rag/graph flags in the binding contract, and this
module is the only place the mapping exists:

    count / existence / list / group_distribution / aggregate / extremum
    / sample_detail                                    -> typed SQL
    description / comparison (with a structured subject) -> SQL scope, then
                                                            RAG *inside* it
    relationship                                       -> seeded graph traversal

§5.2 is the other half: execute ONLY the selected interpretation. Not every
subject candidate, not every field/value candidate, no competing evidence
groups, and no viewer identities fetched while candidates are still being
evaluated. An answer part normally costs one authoritative structured query.

Viewer identity hydration deliberately does NOT happen here. §9 requires
complete identities to be fetched only after execution has established the final
result, so this module returns the predicate and the caller hydrates once.
"""

from __future__ import annotations

import time
from typing import Any, Callable

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.config.settings import Settings, get_settings
from app.db.models import IfcEntity
from app.llm.schemas import AnswerPart, OutputOperation
from app.query.binding.compile import CompiledPredicate, compile_predicate
from app.query.binding.evidence import (
    AggregateValue,
    AnswerPartResult,
    DistributionBucket,
    ResultExample,
    ResultStatus,
    RetrievalMode,
    classify_structured_result,
)
from app.query.binding.graph_exec import execute_graph
from app.query.binding.schemas import CandidateSlate
from app.query.binding.validate import PartValidation
from app.query.sql.aggregates import compute_aggregate, compute_group_by
from app.query.sql.compiler import build_condition_expr, path_array_param
from app.query.sql.field_registry import resolve_field
from app.query.sql.schemas import FieldKind, FieldRef

__all__ = ["execute_answer_part", "ExecutionContext"]

_ET = IfcEntity.__table__

#: Operations answered entirely by typed SQL (§5.1).
_SQL_OPERATIONS = frozenset(
    {
        OutputOperation.COUNT,
        OutputOperation.EXISTENCE,
        OutputOperation.LIST,
        OutputOperation.SAMPLE_DETAIL,
        OutputOperation.GROUP_DISTRIBUTION,
        OutputOperation.AGGREGATE,
        OutputOperation.EXTREMUM,
    }
)
#: Operations that may additionally rank qualitatively, always inside the SQL scope.
_QUALITATIVE_OPERATIONS = frozenset({OutputOperation.DESCRIPTION, OutputOperation.COMPARISON})


class ExecutionContext:
    """Everything execution may read besides the model."""

    def __init__(
        self,
        session: Session,
        source_model_id: int,
        slate: CandidateSlate,
        settings: Settings | None = None,
        selection_entity_ids: list[int] | None = None,
        previous_scope_entity_ids: list[int] | None = None,
        embedding_service_getter: Callable[[], Any] | None = None,
    ) -> None:
        self.session = session
        self.source_model_id = source_model_id
        self.slate = slate
        self.settings = settings or get_settings()
        self.selection_entity_ids = selection_entity_ids or []
        self.previous_scope_entity_ids = previous_scope_entity_ids or []
        self.embedding_service_getter = embedding_service_getter


def execute_answer_part(validation: PartValidation, context: ExecutionContext) -> AnswerPartResult:
    """Execute exactly one answer part and return its adjudicated result."""
    part = validation.part
    started = time.perf_counter()
    result = AnswerPartResult(
        part_id=part.part_id,
        request_text=part.request_text,
        operation=part.operation.value,
        status=ResultStatus.UNAVAILABLE,
    )

    # A part that failed validation never executes. Answering it anyway would
    # run a query the user did not ask for (§3.3).
    if not validation.valid:
        result.limitation = (
            validation.issues[0].detail
            if validation.issues
            else (validation.closure.unresolved_reason or "this request could not be bound")
        )
        result.duration_ms = round((time.perf_counter() - started) * 1000.0, 1)
        return result

    predicate = compile_predicate(
        context.session,
        part,
        validation.closure,
        context.slate,
        context.source_model_id,
        selection_entity_ids=context.selection_entity_ids,
        previous_scope_entity_ids=context.previous_scope_entity_ids,
    )
    result.predicate = predicate
    result.interpretation = "; ".join(predicate.interpretation_notes[:4])

    if validation.closure.logical_kind:
        _execute_logical(part, validation.closure, context, result)
    elif part.operation is OutputOperation.RELATIONSHIP:
        _execute_relationship(part, predicate, context, result)
    elif part.operation in _QUALITATIVE_OPERATIONS:
        _execute_qualitative(part, predicate, context, result)
    else:
        _execute_structured(part, predicate, context, result)

    result.duration_ms = round((time.perf_counter() - started) * 1000.0, 1)
    return result


# ---------------------------------------------------------------------------
# Structured (typed SQL)
# ---------------------------------------------------------------------------


def _base_where(session: Session, predicate: CompiledPredicate) -> sa.ColumnElement:
    """The ONE where-clause every consumer of this part shares (§9).

    The count, the class breakdown, the examples, the RAG scope, the graph seeds
    and (later) the viewer identities are all built from this, so they cannot
    describe different sets.
    """
    where = _ET.c.source_model_id == predicate.source_model_id
    if predicate.ifc_classes:
        where = sa.and_(where, _ET.c.ifc_class.in_(list(predicate.ifc_classes)))
    if predicate.filters is not None:
        where = sa.and_(
            where,
            build_condition_expr(session, predicate.source_model_id, predicate.filters, _ET),
        )
    if predicate.scope_entity_ids is not None:
        where = sa.and_(where, _ET.c.id.in_(list(predicate.scope_entity_ids)))
    return where


def _execute_logical(
    part: AnswerPart,
    closure,
    context: ExecutionContext,
    result: AnswerPartResult,
) -> None:
    """Answer a LOGICAL subject from the derived spatial model (§11.4).

    The elevation-band abstraction is not an entity class, so it is never
    counted with `COUNT(*)` over `ifc_entities` — which is exactly what made a
    45-storey-entity model report "45 floors" when it has 9 levels. Both numbers
    are reported, distinctly, so neither can stand in for the other.
    """
    from app.query.semantic.spatial import build_storey_model

    storey_model = build_storey_model(context.session, context.source_model_id)
    result.statement_count += 1
    result.modes_executed = (RetrievalMode.SQL,)

    if not storey_model.bands:
        result.status = ResultStatus.UNAVAILABLE
        result.limitation = (
            "this model's storeys carry no elevations, so floor levels cannot be derived"
        )
        return

    result.status = ResultStatus.EXACT
    result.exact_total = len(storey_model.bands)
    result.distribution = [
        DistributionBucket(
            key=f"level {band.index + 1} (elevation {band.min_elevation:g})",
            count=len(band.storeys),
        )
        for band in storey_model.bands
    ]
    result.interpretation = (
        f"{len(storey_model.bands)} logical floor levels, derived by grouping the "
        f"{storey_model.total_storeys} IfcBuildingStorey entities that share an elevation"
    )


def _preflight_block(
    predicate: CompiledPredicate,
) -> tuple[ResultStatus, str | None] | None:
    """The states settled before any query runs, or None to proceed (§2.4, §6).

    Order matters: an unresolved condition outranks an absent subject, because
    "I could not apply your condition" is more accurate than "there are none"
    when the condition was never applied at all.
    """
    if predicate.unresolved:
        return ResultStatus.UNAVAILABLE, predicate.unresolved[0].reason
    if not predicate.ifc_classes:
        return (
            ResultStatus.ZERO,
            "this model contains no objects of the requested kind; this describes the "
            "model, not necessarily the real building",
        )
    if predicate.is_empty_scope:
        return (
            ResultStatus.ZERO,
            "the scope you referred to contains no objects, so nothing could match",
        )
    return None


def _execute_structured(
    part: AnswerPart,
    predicate: CompiledPredicate,
    context: ExecutionContext,
    result: AnswerPartResult,
) -> None:
    result.modes_executed = (RetrievalMode.SQL,)

    # Pre-flight: decide the cases that must NOT reach the database. An
    # unresolved condition or an absent subject is settled without querying,
    # because there is nothing safe to run and a broadened version would answer
    # a different question (§2.4).
    #
    # Deliberately NOT routed through `classify_structured_result` — that
    # function needs the real matched count, and feeding it a placeholder here
    # would classify every query as ZERO before it ever ran.
    blocked = _preflight_block(predicate)
    if blocked is not None:
        result.status, result.limitation = blocked
        if result.status is ResultStatus.ZERO:
            result.exact_total = 0
        return

    session = context.session
    where = _base_where(session, predicate)

    matched = session.execute(sa.select(sa.func.count()).select_from(_ET).where(where)).scalar_one()
    result.statement_count += 1
    result.exact_total = matched

    result.status, result.limitation = classify_structured_result(
        matched_count=matched,
        predicate_executable=True,
        unresolved_reasons=[],
        subject_absent=False,
    )

    if matched == 0:
        return

    if len(predicate.ifc_classes) > 1:
        result.class_breakdown = _class_breakdown(session, where)
        result.statement_count += 1

    if part.operation is OutputOperation.GROUP_DISTRIBUTION:
        _execute_distribution(part, predicate, context, result, where)
    elif part.operation is OutputOperation.AGGREGATE:
        _execute_aggregate(part, predicate, context, result, where)
    elif part.operation is OutputOperation.EXTREMUM:
        _execute_aggregate(part, predicate, context, result, where, extremum=True)

    # Bounded examples for grounding. Deliberately small: §10.2 defaults to at
    # most 3 per answer part, and a list request raises it only to the explicit
    # user limit, never to a whole-inventory dump.
    limit = _example_limit(part, context.settings)
    if limit:
        result.examples = _fetch_examples(session, where, limit)
        result.statement_count += 1


def _example_limit(part: AnswerPart, settings: Settings) -> int:
    if part.operation is OutputOperation.SAMPLE_DETAIL:
        return 1
    if part.operation is OutputOperation.LIST:
        return min(settings.max_list_limit, settings.max_primary_entities)
    if part.operation in (OutputOperation.COUNT, OutputOperation.EXISTENCE):
        return 3
    return 3


def _class_breakdown(session: Session, where: sa.ColumnElement) -> dict[str, int]:
    rows = session.execute(
        sa.select(_ET.c.ifc_class, sa.func.count().label("cnt"))
        .where(where)
        .group_by(_ET.c.ifc_class)
    ).all()
    return {r.ifc_class: r.cnt for r in sorted(rows, key=lambda r: (-r.cnt, r.ifc_class))}


def _fetch_examples(session: Session, where: sa.ColumnElement, limit: int) -> list[ResultExample]:
    name_expr = _ET.c.canonical_json.op("#>>")(path_array_param(("identity", "name")))
    storey_expr = _ET.c.canonical_json.op("#>>")(path_array_param(("storey", "name")))
    stmt = (
        sa.select(
            _ET.c.id,
            _ET.c.global_id,
            _ET.c.ifc_class,
            name_expr.label("name"),
            storey_expr.label("storey_name"),
        )
        .where(where)
        # Deterministic: the same question always yields the same sample (§11.3).
        .order_by(_ET.c.id)
        .limit(limit)
    )
    return [
        ResultExample(
            entity_id=r.id,
            global_id=r.global_id,
            ifc_class=r.ifc_class,
            name=r.name,
            storey_name=r.storey_name,
        )
        for r in session.execute(stmt)
    ]


def _output_field_ref(part: AnswerPart, context: ExecutionContext) -> FieldRef | None:
    for candidate_id in part.output_field_candidate_ids:
        candidate = context.slate.field_candidate(candidate_id)
        if candidate is not None:
            return FieldRef(
                field_kind=FieldKind(candidate.field_kind),
                set_name=candidate.set_name,
                field_name=candidate.field_name,
            )
    return None


def _execute_distribution(
    part: AnswerPart,
    predicate: CompiledPredicate,
    context: ExecutionContext,
    result: AnswerPartResult,
    where: sa.ColumnElement,
) -> None:
    """§4.3: prefer one scoped group/distribution result over inventing a value
    condition when a question asks what values a property has."""
    field_ref = _output_field_ref(part, context)
    if field_ref is None:
        # Distribution over the class itself is still a real answer.
        result.distribution = [
            DistributionBucket(key=cls, count=count)
            for cls, count in (
                result.class_breakdown or _class_breakdown(context.session, where)
            ).items()
        ]
        return
    resolved = resolve_field(context.session, predicate.source_model_id, field_ref)
    buckets = compute_group_by(
        context.session,
        _ET,
        where,
        resolved,
        "count",
        None,
        None,
        context.settings.default_list_limit,
    )
    result.statement_count += 1
    result.distribution = [
        DistributionBucket(key=b.key, count=b.count, value=b.value) for b in buckets
    ]


def _execute_aggregate(
    part: AnswerPart,
    predicate: CompiledPredicate,
    context: ExecutionContext,
    result: AnswerPartResult,
    where: sa.ColumnElement,
    extremum: bool = False,
) -> None:
    field_ref = _output_field_ref(part, context)
    if field_ref is None:
        result.status = ResultStatus.UNAVAILABLE
        result.limitation = (
            "this question needs a specific measured value to aggregate, and none was "
            "identified in this model"
        )
        return
    resolved = resolve_field(context.session, predicate.source_model_id, field_ref)
    function = "max" if extremum else "sum"
    aggregate = compute_aggregate(context.session, _ET, where, function, resolved, None)
    result.statement_count += 1

    if aggregate.coverage_count == 0:
        # §6: missing field coverage is not a zero value. Reporting 0 here would
        # assert a measurement the model never recorded.
        result.status = ResultStatus.UNAVAILABLE
        result.limitation = (
            f"none of the {aggregate.matched_count} matching objects record a usable value "
            "for that measurement in this model"
        )
        return

    result.aggregate = AggregateValue(
        function=aggregate.function,
        value=aggregate.value,
        unit=None,
        coverage_count=aggregate.coverage_count,
        matched_count=aggregate.matched_count,
    )
    if not result.aggregate.complete:
        result.status = ResultStatus.PARTIAL
        result.known_parts.append(
            f"{aggregate.function} over the {aggregate.coverage_count} objects that record it"
        )
        result.unknown_parts.append(
            f"{aggregate.matched_count - aggregate.coverage_count} matching objects record no value"
        )
        result.limitation = (
            f"only {aggregate.coverage_count} of {aggregate.matched_count} matching objects "
            "carry this measurement, so the result does not cover them all"
        )


# ---------------------------------------------------------------------------
# Qualitative — SQL scope first, RAG strictly inside it (§5.3)
# ---------------------------------------------------------------------------


def _execute_qualitative(
    part: AnswerPart,
    predicate: CompiledPredicate,
    context: ExecutionContext,
    result: AnswerPartResult,
) -> None:
    """A qualitative request with a structured subject executes SQL scope first
    and RAG only within the resulting ids (§5.1, §5.3)."""
    _execute_structured(part, predicate, context, result)
    if result.status not in (ResultStatus.EXACT, ResultStatus.PARTIAL):
        return
    if not part.semantic_ranking_text or context.embedding_service_getter is None:
        return

    scope_ids = _scope_entity_ids(context.session, predicate)
    result.statement_count += 1

    from app.query.rag.errors import EmbeddingServiceUnavailableError
    from app.query.rag.schemas import RagSearchPlan
    from app.query.rag.search import run_rag_search
    from app.shared.errors import DegradedCapabilityError

    try:
        service = context.embedding_service_getter()
        rag = run_rag_search(
            context.session,
            service,
            RagSearchPlan(
                source_model_id=predicate.source_model_id,
                semantic_query=part.semantic_ranking_text,
                search_entity_documents=True,
                search_relationship_documents=False,
                top_k_per_kind=context.settings.rag_facet_top_k,
                # The authoritative scope. An empty list stays empty — it never
                # widens back to the whole model (§5.3).
                scope_entity_ids=scope_ids,
            ),
        )
    except (EmbeddingServiceUnavailableError, DegradedCapabilityError) as exc:
        result.known_parts.append("the exact structured result above")
        result.unknown_parts.append("qualitative ranking (semantic retrieval unavailable)")
        result.status = ResultStatus.PARTIAL
        result.limitation = f"semantic ranking was unavailable: {exc}"
        return

    result.modes_executed = (*result.modes_executed, RetrievalMode.SCOPED_RAG)
    accepted = [c for c in rag.entity_candidates if c.passed_threshold]
    # Bounded semantic evidence, kept SEPARATE from the exact total, which is
    # still the SQL count above. §5.3: "RAG is bounded semantic evidence, never
    # an exact total."
    result.rag_candidate_count = len(accepted)
    if accepted:
        ranked_ids = [c.canonical_id for c in accepted[:3]]
        result.examples = _fetch_examples_by_id(context.session, predicate, ranked_ids)
        result.statement_count += 1


def _scope_entity_ids(session: Session, predicate: CompiledPredicate) -> list[int]:
    where = _base_where(session, predicate)
    return [r[0] for r in session.execute(sa.select(_ET.c.id).where(where))]


def _fetch_examples_by_id(
    session: Session, predicate: CompiledPredicate, entity_ids: list[int]
) -> list[ResultExample]:
    if not entity_ids:
        return []
    where = sa.and_(_ET.c.source_model_id == predicate.source_model_id, _ET.c.id.in_(entity_ids))
    return _fetch_examples(session, where, len(entity_ids))


# ---------------------------------------------------------------------------
# Relationship — seeded graph traversal (§5.4)
# ---------------------------------------------------------------------------


def _execute_relationship(
    part: AnswerPart,
    predicate: CompiledPredicate,
    context: ExecutionContext,
    result: AnswerPartResult,
) -> None:
    candidate = context.slate.relationship(part.relationship_candidate_id or "")
    if candidate is None:
        result.status = ResultStatus.UNAVAILABLE
        result.limitation = "no traversable relationship was identified for this question"
        return

    endpoint_classes: tuple[str, ...] = ()
    endpoint_subject = context.slate.subject(part.endpoint_subject_candidate_id or "")
    if endpoint_subject is not None:
        endpoint_classes = endpoint_subject.family_members or (endpoint_subject.ifc_class,)

    execution = execute_graph(
        context.session,
        predicate,
        relationship_class=candidate.ifc_class,
        relationship_available=candidate.available,
        endpoint_ifc_classes=endpoint_classes,
        max_depth=min(candidate.max_depth, context.settings.max_graph_depth),
        seed_entity_ids=list(predicate.scope_entity_ids or ()) or None,
    )
    result.modes_executed = (RetrievalMode.GRAPH,)
    result.statement_count += execution.statement_count

    if execution.unavailable_reason:
        result.status = ResultStatus.UNAVAILABLE
        result.limitation = execution.unavailable_reason
        return
    if execution.established_nothing:
        # Traversal genuinely ran and connected nothing. That is a ZERO about
        # the MODEL's recorded relationships — explicitly not proof that no such
        # connection exists in the real building (§6).
        result.status = ResultStatus.ZERO
        result.exact_total = 0
        result.limitation = (
            "traversal ran but this model records no such connection; that describes the "
            "model's relationships, not necessarily the real building"
        )
        return

    result.status = ResultStatus.EXACT
    result.graph_endpoints = execution.endpoints
    result.graph_path_count = execution.path_count
    result.exact_total = len(execution.endpoints)
    result.examples = execution.endpoints[:3]
