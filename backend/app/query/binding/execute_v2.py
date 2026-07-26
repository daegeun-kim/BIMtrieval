"""One authoritative execution per compiled answer part (task26 §10-§12).

Each result kind executes its own operation-specific plan, and the requested,
contextual, scanned, covered, sample, and viewer sets stay distinct
throughout. Exactness follows the coverage proof: an exact zero is only
reported when the compiled predicate PROVES the operation was checkable for
the whole eligible set (§9.3); a bounded RAG miss or capped traversal never
becomes a zero.
"""

from __future__ import annotations

import time
from typing import Any, Callable

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.config.settings import Settings, get_settings
from app.db.models import IfcEntity, RagDocument
from app.llm.schemas_v2 import ResultKind, ViewerSetPolicy
from app.query.binding.compile_v2 import CompiledPart, array_element_expr
from app.query.binding.results_v2 import (
    DistributionBucketV2,
    DistributionResult,
    EntitySetResult,
    EvidenceExcerpt,
    GraphEndpointResult,
    PartResultV2,
    ProfileResult,
    QualitativeEvidenceResult,
    ResultExampleV2,
    ResultStatusV2,
    SampleResult,
    ScalarResult,
)
from app.query.semantic.manifest_v002.schema import ManifestV002
from app.query.sql.compiler import path_array_param

__all__ = ["ExecutionContextV2", "execute_part"]

_ET = IfcEntity.__table__
_RD = RagDocument.__table__

#: Diversity slice size below the primary similarity cutoff (§11.2).
_DIVERSITY_SLICE = 3


class ExecutionContextV2:
    def __init__(
        self,
        session: Session,
        manifest: ManifestV002,
        settings: Settings | None = None,
        embedding_service_getter: Callable[[], Any] | None = None,
    ) -> None:
        self.session = session
        self.manifest = manifest
        self.settings = settings or get_settings()
        self.embedding_service_getter = embedding_service_getter


def execute_part(
    compiled: CompiledPart,
    request_text: str,
    context: ExecutionContextV2,
) -> PartResultV2:
    started = time.perf_counter()
    result = PartResultV2(
        part_id=compiled.part_id,
        request_text=request_text,
        result_kind=compiled.result_kind.value,
        viewer_policy=compiled.viewer_set,
        interpretation_notes=list(compiled.interpretation_notes),
        coverage_complete=compiled.coverage.complete,
        coverage_reasons=list(compiled.coverage.reasons),
        is_contextual=compiled.viewer_set == ViewerSetPolicy.CONTEXT.value,
        context_reason=compiled.context_reason,
    )
    result.allowed_terms = _allowed_terms(compiled, context.manifest)

    kind = compiled.result_kind
    try:
        if kind in (ResultKind.ENTITY_SET, ResultKind.QUALITATIVE_EVIDENCE):
            _execute_entity_set(compiled, context, result)
            if kind is ResultKind.QUALITATIVE_EVIDENCE and result.is_answerable:
                _attach_evidence(compiled, context, result)
        elif kind is ResultKind.SCALAR:
            _execute_scalar(compiled, context, result)
        elif kind is ResultKind.DISTRIBUTION:
            _execute_distribution(compiled, context, result)
        elif kind is ResultKind.SAMPLE:
            _execute_sample(compiled, context, result)
        elif kind is ResultKind.PROFILE:
            _execute_profile(compiled, context, result)
        elif kind is ResultKind.GRAPH_ENDPOINTS:
            _execute_graph(compiled, context, result)
        if compiled.projections and result.is_answerable:
            _execute_projections(compiled, context, result)
    except sa.exc.SQLAlchemyError as exc:
        result.status = ResultStatusV2.UNAVAILABLE
        result.add_limitation(
            "RESULT_SET_MISMATCH",
            f"this part's query failed to execute ({type(exc).__name__}); its result is "
            "unavailable, not zero",
        )

    result.duration_ms = round((time.perf_counter() - started) * 1000.0, 1)
    return result


# ---------------------------------------------------------------------------
# Entity set (count / list / existence)
# ---------------------------------------------------------------------------


def _execute_entity_set(
    compiled: CompiledPart, context: ExecutionContextV2, result: PartResultV2
) -> None:
    session = context.session
    if compiled.derived_value is not None:
        result.result = EntitySetResult(
            scanned_cardinality=compiled.derived_value,
            matched_cardinality=compiled.derived_value,
        )
        result.status = ResultStatusV2.EXACT
        return
    scanned = session.execute(
        sa.select(sa.func.count()).select_from(_ET).where(compiled.scanned_where())
    ).scalar_one()
    matched = session.execute(
        sa.select(sa.func.count()).select_from(_ET).where(compiled.base_where())
    ).scalar_one()
    result.statement_count += 2

    entity_set = EntitySetResult(scanned_cardinality=scanned, matched_cardinality=matched)
    if len(compiled.target_classes) > 1 and matched:
        rows = session.execute(
            sa.select(_ET.c.ifc_class, sa.func.count())
            .where(compiled.base_where())
            .group_by(_ET.c.ifc_class)
        ).all()
        result.statement_count += 1
        entity_set.class_breakdown = {
            r[0]: int(r[1]) for r in sorted(rows, key=lambda r: (-r[1], r[0]))
        }
    result.result = entity_set

    result.status = _entity_set_status(compiled, matched, scanned, result)
    result.viewer_where = compiled.base_where() if matched else None
    if result.status in (ResultStatusV2.EXACT, ResultStatusV2.PARTIAL) and matched:
        limit = 1 if compiled.limit == 1 else min(3, matched)
        if compiled.result_kind is ResultKind.ENTITY_SET and compiled.limit:
            limit = min(compiled.limit, context.settings.max_list_limit)
        result.examples = _fetch_examples(session, compiled.base_where(), limit)
        result.statement_count += 1


def _entity_set_status(
    compiled: CompiledPart, matched: int, scanned: int, result: PartResultV2
) -> ResultStatusV2:
    if matched == 0:
        if compiled.coverage.complete:
            result.add_limitation(
                "SOURCE_UNRESOLVABLE",
                "this zero describes the model's recorded data, not necessarily the real "
                "building",
            )
            return ResultStatusV2.ZERO
        result.known_parts.append("0 objects with the requested fact recorded")
        result.unknown_parts.append(
            f"{scanned} objects whose value for the filtered fact is not recorded"
        )
        result.add_limitation(
            "COVERAGE_PROOF_GAP",
            "coverage is incomplete for the filtered fact, so an exact zero cannot be "
            "proved: " + "; ".join(compiled.coverage.reasons[:2]),
        )
        return ResultStatusV2.PARTIAL
    if compiled.coverage.complete:
        return ResultStatusV2.EXACT
    unrecorded = max(0, scanned - matched)
    result.known_parts.append(f"{matched} objects match among those with the fact recorded")
    if unrecorded:
        result.unknown_parts.append(f"{unrecorded} objects record no value for the filtered fact")
    result.add_limitation(
        "COVERAGE_PROOF_GAP",
        "; ".join(compiled.coverage.reasons[:2]) or "coverage is incomplete",
    )
    return ResultStatusV2.PARTIAL


# ---------------------------------------------------------------------------
# Scalar aggregate
# ---------------------------------------------------------------------------

_AGG_FUNCS = {
    "count": sa.func.count,
    "sum": sa.func.sum,
    "avg": sa.func.avg,
    "min": sa.func.min,
    "max": sa.func.max,
}


def _execute_scalar(
    compiled: CompiledPart, context: ExecutionContextV2, result: PartResultV2
) -> None:
    session = context.session
    if compiled.derived_value is not None:
        # An already-derived whole-model figure: exact, and no rows to scan.
        result.result = ScalarResult(
            function="count",
            value=compiled.derived_value,
            covered_cardinality=compiled.derived_value,
            eligible_cardinality=compiled.derived_value,
        )
        result.status = ResultStatusV2.EXACT
        return
    matched = session.execute(
        sa.select(sa.func.count()).select_from(_ET).where(compiled.base_where())
    ).scalar_one()
    result.statement_count += 1

    if compiled.aggregate_function == "count" or compiled.aggregate_expr is None:
        result.result = ScalarResult(
            function="count",
            value=matched,
            covered_cardinality=matched,
            eligible_cardinality=matched,
        )
        result.status = _entity_set_status(compiled, matched, matched, result)
        result.viewer_where = compiled.base_where() if matched else None
        return

    value_expr = _aggregate_value_expr(compiled)
    func = _AGG_FUNCS[compiled.aggregate_function]
    row = session.execute(
        sa.select(func(value_expr), sa.func.count(value_expr)).where(compiled.base_where())
    ).one()
    result.statement_count += 1
    value, covered = row[0], int(row[1] or 0)

    unit = None
    if compiled.aggregate_capability is not None:
        units = {
            a.unit for a in compiled.aggregate_capability.applicability if a.unit
        }
        unit = next(iter(units)) if len(units) == 1 else None

    if covered == 0:
        result.status = ResultStatusV2.UNAVAILABLE
        result.add_limitation(
            "COVERAGE_PROOF_GAP",
            f"none of the {matched} matching objects record a usable value for this "
            "measurement",
        )
        return
    result.result = ScalarResult(
        function=compiled.aggregate_function,
        value=float(value) if value is not None else None,
        unit=unit,
        covered_cardinality=covered,
        eligible_cardinality=matched,
    )
    result.viewer_where = compiled.base_where()
    if covered < matched:
        result.status = ResultStatusV2.PARTIAL
        result.known_parts.append(
            f"{compiled.aggregate_function} over the {covered} objects recording the value"
        )
        result.unknown_parts.append(f"{matched - covered} matching objects record no value")
        result.add_limitation(
            "COVERAGE_PROOF_GAP",
            f"only {covered} of {matched} matching objects carry this measurement",
        )
    else:
        result.status = ResultStatusV2.EXACT


def _aggregate_value_expr(compiled: CompiledPart) -> Any:
    capability = compiled.aggregate_capability
    if capability is not None and capability.physical:
        physical = capability.physical
        if physical.get("source") in ("property_sets", "quantity_sets"):
            unit_known = any(a.unit_state == "known" for a in capability.applicability)
            if unit_known:
                path = (
                    physical["source"],
                    physical["set"],
                    physical["field"],
                    "normalized_value",
                )
                return sa.cast(
                    _ET.c.canonical_json.op("#>>")(path_array_param(path)), sa.Numeric
                )
    return compiled.aggregate_expr


# ---------------------------------------------------------------------------
# Distribution / grouped argmax
# ---------------------------------------------------------------------------


def _execute_distribution(
    compiled: CompiledPart, context: ExecutionContextV2, result: PartResultV2
) -> None:
    session = context.session
    base = session.execute(
        sa.select(sa.func.count()).select_from(_ET).where(compiled.base_where())
    ).scalar_one()
    result.statement_count += 1

    if compiled.group is None:
        # A field distribution over the matched set via projections.
        if compiled.projections:
            _execute_projections(compiled, context, result)
            result.result = EntitySetResult(scanned_cardinality=base, matched_cardinality=base)
            result.status = _entity_set_status(compiled, base, base, result)
            result.viewer_where = compiled.base_where() if base else None
            return
        result.status = ResultStatusV2.UNAVAILABLE
        result.add_limitation(
            "UNSUPPORTED_LOGICAL_SHAPE", "a distribution needs a group axis or a field"
        )
        return

    if compiled.group.kind == "array_element":
        # A multi-valued array field: buckets come from the unnested elements,
        # and the objects carrying no element at all are the missing remainder.
        _element, value_expr = array_element_expr(
            compiled.group.array_key or "materials", compiled.group.array_field or "name"
        )
        label = value_expr.label("bucket")
        rows = session.execute(
            sa.select(label, sa.func.count(sa.distinct(_ET.c.id)).label("n"))
            .select_from(_ET)
            .where(compiled.base_where(), value_expr.isnot(None))
            .group_by(label)
            .order_by(sa.desc("n"))
        ).all()
        result.statement_count += 1
        with_any = session.execute(
            sa.select(sa.func.count())
            .select_from(_ET)
            .where(
                compiled.base_where(),
                _array_has_element(
                    compiled.group.array_key or "materials",
                    compiled.group.array_field or "name",
                ),
            )
        ).scalar_one()
        result.statement_count += 1
        rows = [*rows, (None, base - int(with_any))] if base > int(with_any) else list(rows)
    else:
        label = compiled.group.label_expr.label("bucket")
        rows = session.execute(
            sa.select(label, sa.func.count().label("n"))
            .where(compiled.base_where())
            .group_by(label)
            .order_by(sa.desc("n"))
        ).all()
        result.statement_count += 1

    band_labels = {
        band.semantic_id: _band_label(band) for band in compiled.group.bands
    }
    buckets = []
    missing = 0
    for key, count in rows:
        if key is None:
            missing = int(count)
            continue
        buckets.append(
            DistributionBucketV2(
                key=str(key), count=int(count), label=band_labels.get(str(key))
            )
        )
    covered = sum(b.count for b in buckets)
    if compiled.group.kind == "array_element":
        # One object may carry several values, so the bucket counts can exceed
        # the base set: the covered figure is the objects with any value, not
        # the bucket sum, or a distribution would look like a false total.
        covered = max(0, base - missing)

    distribution = DistributionResult(
        base_cardinality=base,
        covered_cardinality=covered,
        missing_count=missing,
        buckets=buckets,
    )
    if compiled.order_direction is not None and compiled.limit:
        ordered = sorted(
            buckets, key=lambda b: b.count, reverse=compiled.order_direction == "desc"
        )
        distribution.top_buckets = ordered[: compiled.limit]
        if len(ordered) > compiled.limit and distribution.top_buckets:
            boundary = distribution.top_buckets[-1].count
            distribution.tie = ordered[compiled.limit].count == boundary
    result.result = distribution
    result.viewer_where = compiled.base_where() if covered else None
    if compiled.group.kind == "array_element" and missing and covered:
        # Highlight the objects the buckets actually describe, not every object
        # of the class: the ones with no recorded value are not in the answer.
        result.viewer_where = sa.and_(
            compiled.base_where(),
            _array_has_element(
                compiled.group.array_key or "materials",
                compiled.group.array_field or "name",
            ),
        )

    if missing:
        result.status = ResultStatusV2.PARTIAL
        result.known_parts.append(f"{covered} objects grouped into {len(buckets)} buckets")
        result.unknown_parts.append(f"{missing} objects resolve to no group value")
        result.add_limitation(
            "COVERAGE_PROOF_GAP", f"{missing} of {base} objects carry no group value"
        )
    elif base == 0:
        result.status = (
            ResultStatusV2.ZERO if compiled.coverage.complete else ResultStatusV2.PARTIAL
        )
    else:
        result.status = (
            ResultStatusV2.EXACT if compiled.coverage.complete else ResultStatusV2.PARTIAL
        )
        if not compiled.coverage.complete:
            result.add_limitation(
                "COVERAGE_PROOF_GAP", "; ".join(compiled.coverage.reasons[:2])
            )


def _exact_evidence_retry(
    context: ExecutionContextV2, select: Any, result: PartResultV2
) -> list[Any]:
    """Re-run a nearest-neighbour search exactly when the index returned nothing.

    An approximate vector index that answers a similarity search with ZERO rows
    turns a bounded retrieval miss into "this model records nothing about that",
    which is the one thing evidence must never become (task26 §11.2). The retry
    disables index scans for this statement only, so the same bounded query runs
    exactly. It costs nothing once the index is healthy, because a healthy index
    never returns an empty answer for a non-empty scope.
    """
    try:
        with context.session.begin_nested():
            context.session.execute(sa.text("SET LOCAL enable_indexscan = off"))
            rows = context.session.execute(select).all()
    except sa.exc.SQLAlchemyError:
        return []
    result.statement_count += 2
    if rows:
        result.interpretation_notes.append(
            "the model's text-similarity index returned nothing and the search was "
            "repeated exactly"
        )
    return rows


def _array_has_element(array_key: str, element_field: str) -> Any:
    """EXISTS: this object carries at least one value in the given array field."""
    element, value_expr = array_element_expr(array_key, element_field)
    return sa.exists(
        sa.select(sa.literal(1)).select_from(element).where(value_expr.isnot(None))
    )


def _band_label(band: Any) -> str:
    names = [n for n in band.storey_names if n][:2]
    ordinal = f"floor {band.occupiable_ordinal}" if band.occupiable_ordinal else band.classification
    return f"{ordinal} ({', '.join(names)})" if names else ordinal


# ---------------------------------------------------------------------------
# Sample
# ---------------------------------------------------------------------------


def _execute_sample(
    compiled: CompiledPart, context: ExecutionContextV2, result: PartResultV2
) -> None:
    session = context.session
    eligible = session.execute(
        sa.select(sa.func.count()).select_from(_ET).where(compiled.base_where())
    ).scalar_one()
    result.statement_count += 1
    sample_result = SampleResult(eligible_cardinality=eligible)
    result.result = sample_result

    if eligible == 0:
        result.status = (
            ResultStatusV2.ZERO if compiled.coverage.complete else ResultStatusV2.PARTIAL
        )
        result.add_limitation(
            "SOURCE_UNRESOLVABLE", "no eligible object exists to sample from"
        )
        return

    examples = _fetch_examples(session, compiled.base_where(), 1)
    result.statement_count += 1
    if examples:
        sample_result.sample = examples[0]
        result.viewer_sample = examples[0]
        result.examples = examples
        detail = _sample_detail(session, compiled, examples[0])
        if detail:
            sample_result.detail = detail
            result.statement_count += 1
    result.status = ResultStatusV2.EXACT


def _sample_detail(
    session: Session, compiled: CompiledPart, example: ResultExampleV2
) -> dict[str, Any]:
    detail: dict[str, Any] = {}
    exprs = []
    labels = []
    for spec in compiled.projections[:4]:
        if spec.value_expr is not None:
            exprs.append(spec.value_expr)
            labels.append(spec.capability.label)
    if not exprs:
        return detail
    row = session.execute(
        sa.select(*exprs).where(
            _ET.c.id == example.entity_id, _ET.c.source_model_id == compiled.source_model_id
        )
    ).first()
    if row is not None:
        for label, value in zip(labels, row):
            if value is not None:
                detail[label] = value
    return detail


# ---------------------------------------------------------------------------
# Profiles (§5.6)
# ---------------------------------------------------------------------------


def _execute_profile(
    compiled: CompiledPart, context: ExecutionContextV2, result: PartResultV2
) -> None:
    manifest = context.manifest
    structured: dict[str, Any] = {
        "entity_total": manifest.entity_total,
        "class_inventory_top": dict(
            sorted(manifest.class_inventory.items(), key=lambda kv: -kv[1])[:10]
        ),
    }
    floors = manifest.floors
    if floors.bands:
        structured["floors"] = {
            "occupiable": len(floors.occupiable_bands()),
            "total_bands": len(floors.bands),
            "note": floors.interpretation_note,
        }
    material = manifest.capabilities.get("mat:material.name")
    if material is not None and material.values:
        structured["top_materials"] = {v: c for v, c in material.values[:8]}

    thematic = compiled.target_semantic_id == "derived:thematic_profile"
    profile = ProfileResult(structured=structured)
    result.result = profile
    result.status = ResultStatusV2.EXACT

    # A THEMATIC profile has to be about its theme. Retrieving only the generic
    # building profile left "describe the circulation" with an empty evidence
    # scope and nothing to say (task27 §5). The theme's relevant STRUCTURED
    # subjects are the classes of the objects the retrieval actually returned —
    # read off the same bounded text search, so no theme lookup table, ontology,
    # or second retrieval system is introduced.
    _attach_evidence(compiled, context, result, unscoped_allowed=True)
    if result.evidence is not None:
        profile.evidence_ids = [e.evidence_id for e in result.evidence.excerpts]
    if thematic:
        structured["theme"] = compiled.evidence_theme or result.request_text
        subjects = result.evidence.subject_classes if result.evidence else {}
        if subjects:
            structured["theme_subjects"] = {
                ifc_class: manifest.class_inventory.get(ifc_class, described)
                for ifc_class, described in subjects.items()
            }
            structured["theme_described_objects"] = sum(subjects.values())
        strong = any(
            excerpt.slice == "primary" for excerpt in (
                result.evidence.excerpts if result.evidence else []
            )
        )
        if not strong:
            # Bounded retrieval found nothing that clearly describes the theme.
            # That is a limitation, never a claim that the theme is absent from
            # the real building.
            result.status = ResultStatusV2.PARTIAL
            result.unknown_parts.append(structured["theme"])
            result.add_limitation(
                "EVIDENCE_SCOPE_ERROR",
                "this model records no concept named by that theme, so the objects and "
                "text below are the closest it holds, not a description of it",
            )


# ---------------------------------------------------------------------------
# Qualitative evidence (§11.2)
# ---------------------------------------------------------------------------


def _attach_evidence(
    compiled: CompiledPart,
    context: ExecutionContextV2,
    result: PartResultV2,
    *,
    unscoped_allowed: bool = False,
) -> None:
    if context.embedding_service_getter is None:
        return
    theme = compiled.evidence_theme or result.request_text
    try:
        service = context.embedding_service_getter()
        query_vector = service.embed_query(theme)
    except Exception as exc:  # noqa: BLE001 - RAG degrades, never converts to zero
        result.add_limitation(
            "PROVIDER_STAGE_FAILURE",
            f"qualitative evidence unavailable (embedding service: {type(exc).__name__})",
        )
        if result.status is ResultStatusV2.EXACT:
            result.status = ResultStatusV2.PARTIAL
            result.unknown_parts.append("qualitative evidence (retrieval unavailable)")
        return

    scoped = compiled.target_classes and not unscoped_allowed
    distance = _RD.c.embedding.cosine_distance(query_vector)
    predicates = [
        _RD.c.source_model_id == compiled.source_model_id,
        _RD.c.embedding.isnot(None),
    ]
    scope_kind = "structured"
    if scoped:
        predicates.append(_RD.c.entity_id.in_(compiled.id_select()))
    elif compiled.target_classes:
        scope_kind = "structured"
        predicates.append(_RD.c.entity_id.in_(compiled.id_select()))
    else:
        # A profile has no structured target set of its own, so its evidence can
        # only name the objects a theme is about through ENTITY documents;
        # relationship text records no subject class (§5).
        scope_kind = "unscoped_fallback"
        predicates.append(_RD.c.entity_id.isnot(None))

    select = (
        sa.select(
            _RD.c.id,
            _RD.c.source_kind,
            _RD.c.document_text,
            _RD.c.text_truncated,
            _ET.c.ifc_class,
            (sa.literal(1.0) - distance).label("similarity"),
        )
        .select_from(_RD.outerjoin(_ET, _ET.c.id == _RD.c.entity_id))
        .where(*predicates)
        .order_by(distance)
        .limit(context.settings.rag_facet_top_k + _DIVERSITY_SLICE)
    )
    rows = context.session.execute(select).all()
    result.statement_count += 1
    if not rows:
        rows = _exact_evidence_retry(context, select, result)

    threshold = 0.5
    excerpts: list[EvidenceExcerpt] = []
    subject_classes: dict[str, int] = {}
    primary_budget = context.settings.rag_facet_top_k
    diversity_budget = _DIVERSITY_SLICE
    truncated_any = False
    for row in rows:
        similarity = float(row.similarity)
        if similarity >= threshold and primary_budget > 0:
            slice_name = "primary"
            primary_budget -= 1
        elif diversity_budget > 0:
            slice_name = "diversity"
            diversity_budget -= 1
        else:
            continue
        truncated_any = truncated_any or bool(row.text_truncated)
        if row.ifc_class:
            subject_classes[row.ifc_class] = subject_classes.get(row.ifc_class, 0) + 1
        excerpts.append(
            EvidenceExcerpt(
                evidence_id=f"ev:{row.id}",
                source_kind=row.source_kind,
                similarity=similarity,
                excerpt=row.document_text[:400],
                text_truncated=bool(row.text_truncated),
                slice=slice_name,
            )
        )

    scope_count = 0
    if isinstance(result.result, EntitySetResult):
        scope_count = result.result.matched_cardinality
    else:
        scope_count = sum(subject_classes.values())
    result.evidence = QualitativeEvidenceResult(
        scope_cardinality=scope_count,
        excerpts=excerpts,
        scope_kind=scope_kind,
        truncated_evidence=truncated_any,
        subject_classes=subject_classes,
    )
    if truncated_any:
        result.add_limitation(
            "EVIDENCE_SCOPE_ERROR",
            "some evidence documents were truncated at ingestion; they can support facts "
            "but cannot prove an omitted fact absent",
        )


# ---------------------------------------------------------------------------
# Graph endpoints (§11.3)
# ---------------------------------------------------------------------------


def _execute_graph(
    compiled: CompiledPart, context: ExecutionContextV2, result: PartResultV2
) -> None:
    from app.db.models import DbIfcRelationship, RelationshipMember

    session = context.session
    _R = DbIfcRelationship.__table__
    _RM = RelationshipMember.__table__

    if not compiled.traversals:
        result.status = ResultStatusV2.UNAVAILABLE
        result.add_limitation("UNSUPPORTED_LOGICAL_SHAPE", "no traversal was bound")
        return
    spec = compiled.traversals[0]

    seed_count = session.execute(
        sa.select(sa.func.count()).select_from(_ET).where(compiled.base_where())
    ).scalar_one()
    result.statement_count += 1

    current_ids = compiled.id_select()
    relationship_total = 0
    path_labels: list[str] = []
    for hop in spec.hops:
        src = _RM.alias("src")
        tgt = _RM.alias("tgt")
        hop_select = (
            sa.select(tgt.c.entity_id)
            .select_from(
                _R.join(src, src.c.relationship_id == _R.c.id).join(
                    tgt, tgt.c.relationship_id == _R.c.id
                )
            )
            .where(
                _R.c.source_model_id == compiled.source_model_id,
                _R.c.ifc_class == hop.relationship,
                src.c.role == hop.from_role,
                tgt.c.role == hop.to_role,
                src.c.entity_id.in_(current_ids),
                tgt.c.entity_id.isnot(None),
            )
            .distinct()
        )
        count_relationships = session.execute(
            sa.select(sa.func.count(sa.distinct(_R.c.id)))
            .select_from(
                _R.join(src, src.c.relationship_id == _R.c.id)
            )
            .where(
                _R.c.source_model_id == compiled.source_model_id,
                _R.c.ifc_class == hop.relationship,
                src.c.role == hop.from_role,
                src.c.entity_id.in_(current_ids),
            )
        ).scalar_one()
        result.statement_count += 1
        relationship_total += int(count_relationships)
        path_labels.append(f"{hop.relationship}.{hop.from_role}->{hop.to_role}")
        current_ids = hop_select

    endpoint_where = [_ET.c.id.in_(current_ids), _ET.c.source_model_id == compiled.source_model_id]
    if spec.endpoint_classes:
        endpoint_where.append(_ET.c.ifc_class.in_(list(spec.endpoint_classes)))
    endpoint_count = session.execute(
        sa.select(sa.func.count()).select_from(_ET).where(*endpoint_where)
    ).scalar_one()
    result.statement_count += 1

    graph = GraphEndpointResult(
        seed_cardinality=int(seed_count),
        traversed_cardinality=int(seed_count),  # complete: no cap applied (§11.3)
        relationship_count=relationship_total,
        endpoint_entity_count=int(endpoint_count),
        endpoint_fact_count=relationship_total,
        complete=True,
        path_labels=path_labels,
    )
    result.result = graph

    if endpoint_count:
        graph.endpoints = _fetch_examples(session, sa.and_(*endpoint_where), 5)
        result.statement_count += 1
        result.examples = graph.endpoints
        result.viewer_where = sa.and_(*endpoint_where)
        result.status = ResultStatusV2.EXACT
    else:
        result.status = ResultStatusV2.ZERO
        result.add_limitation(
            "SOURCE_UNRESOLVABLE",
            "traversal ran completely and this model records no such connection; that "
            "describes the model's relationships, not necessarily the real building",
        )


# ---------------------------------------------------------------------------
# Projections
# ---------------------------------------------------------------------------


def _execute_projections(
    compiled: CompiledPart, context: ExecutionContextV2, result: PartResultV2
) -> None:
    session = context.session
    for spec in compiled.projections[:4]:
        if spec.capability.accessor == "json.material_name":
            element = sa.func.jsonb_array_elements(
                _ET.c.canonical_json["materials"]
            ).table_valued("value", joins_implicitly=True)
            value_expr = element.c.value.op("->>")("name")
            rows = session.execute(
                sa.select(value_expr.label("v"), sa.func.count().label("n"))
                .select_from(_ET)
                .where(compiled.base_where(), value_expr.isnot(None))
                .group_by("v")
                .order_by(sa.desc("n"))
                .limit(16)
            ).all()
        else:
            value_expr = spec.value_expr
            rows = session.execute(
                sa.select(value_expr.label("v"), sa.func.count().label("n"))
                .where(compiled.base_where(), value_expr.isnot(None))
                .group_by("v")
                .order_by(sa.desc("n"))
                .limit(16)
            ).all()
        result.statement_count += 1
        covered = session.execute(
            sa.select(sa.func.count())
            .select_from(_ET)
            .where(
                compiled.base_where(),
                (
                    sa.exists(
                        sa.select(sa.literal(1))
                        .select_from(
                            sa.func.jsonb_array_elements(
                                _ET.c.canonical_json["materials"]
                            ).table_valued("value", joins_implicitly=True)
                        )
                    )
                    if spec.capability.accessor == "json.material_name"
                    else spec.value_expr.isnot(None)
                ),
            )
        ).scalar_one()
        result.statement_count += 1
        result.extra_facts.append(
            {
                "fact_id": f"{compiled.part_id}:report:{spec.capability.semantic_id}",
                "kind": "value_distribution",
                "field": spec.capability.label,
                "covered": int(covered),
                "values": {str(v): int(n) for v, n in rows},
            }
        )
        matched = (
            result.result.matched_cardinality
            if isinstance(result.result, EntitySetResult)
            else None
        )
        if matched and covered < matched:
            result.known_parts.append(
                f"{spec.capability.label} recorded on {covered} of {matched} objects"
            )
            result.unknown_parts.append(
                f"{matched - covered} objects record no {spec.capability.label}"
            )
            if result.status is ResultStatusV2.EXACT:
                result.status = ResultStatusV2.PARTIAL
            result.add_limitation(
                "COVERAGE_PROOF_GAP",
                f"{spec.capability.label} is recorded on only {covered} of {matched} "
                "matching objects",
            )


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _fetch_examples(session: Session, where: Any, limit: int) -> list[ResultExampleV2]:
    name_expr = _ET.c.canonical_json.op("#>>")(path_array_param(("identity", "name")))
    storey_expr = _ET.c.canonical_json.op("#>>")(path_array_param(("storey", "name")))
    rows = session.execute(
        sa.select(_ET.c.id, _ET.c.global_id, _ET.c.ifc_class, name_expr, storey_expr)
        .where(where)
        .order_by(_ET.c.id)  # deterministic sample/order policy (§10.5)
        .limit(limit)
    ).all()
    return [
        ResultExampleV2(
            entity_id=r[0], global_id=r[1], ifc_class=r[2], name=r[3], storey_name=r[4]
        )
        for r in rows
    ]


def _allowed_terms(compiled: CompiledPart, manifest: ManifestV002) -> list[str]:
    terms: list[str] = list(compiled.target_classes)
    record = manifest.get(compiled.target_semantic_id)
    if record is not None:
        terms.append(getattr(record, "label", compiled.target_semantic_id))
        terms.extend(getattr(record, "aliases", ())[:4])
    for spec in compiled.projections:
        terms.append(spec.capability.label)
        terms.extend(spec.capability.aliases[:2])
    if compiled.group is not None and compiled.group.bands:
        for band in compiled.group.bands:
            terms.extend(n for n in band.storey_names if n)
    return terms[:40]
