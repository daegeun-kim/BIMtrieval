"""Deterministic evidence-group construction + execution (Task 17 §4, §5).

Turns per-facet resolved candidates into independently-selectable evidence
groups (one semantic claim each), deduplicates them by canonical predicate, and
executes ONLY the retrieval modes fixed by the frozen policy. SQL is authoritative
for exact counts; RAG enriches representative examples and forms bounded RAG-only
candidate groups; it never adds to an exact count (§4). One failing group never
zeroes the others.
"""

from __future__ import annotations

import re
from typing import Any, Callable

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.config.settings import Settings
from app.db.models import IfcEntity
from app.query.hybrid.groups.execute import execute_predicate
from app.query.hybrid.groups.schemas import (
    AUTHORITY_EXACT,
    AUTHORITY_SEMANTIC,
    AUTHORITY_STRUCTURED,
    COVERAGE_BOUNDED,
    COVERAGE_COMPLETE,
    COVERAGE_FAILED,
    COVERAGE_UNKNOWN,
    EvidenceGroup,
    GroupPredicate,
    PredicateKind,
)
from app.query.rag.errors import EmbeddingServiceUnavailableError
from app.query.rag.schemas import RagSearchPlan
from app.query.rag.search import run_rag_search
from app.query.sql.entities import entity_hydration_columns
from app.query.sql.hydration import hydrate_primary_entity
from app.shared.errors import DegradedCapabilityError

_ET = IfcEntity.__table__
_ROLE_RANK = {"direct": 0, "supporting": 1, "context": 2, "uncertain": 3}


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")[:48] or "x"


# ---------------------------------------------------------------------------
# Group spec collection (before execution)
# ---------------------------------------------------------------------------


def _class_predicate(ifc_class: str) -> GroupPredicate:
    return GroupPredicate(kind=PredicateKind.ENTITY_CLASS.value, ifc_classes=(ifc_class,))


def _fact_predicate(fact: Any) -> GroupPredicate | None:
    ref = fact.queryable_ref
    if ref is None:
        return None
    kind = {
        "attribute": PredicateKind.ATTRIBUTE_VALUE.value,
        "property": PredicateKind.PROPERTY_VALUE.value,
        "type_fact": PredicateKind.TYPE_VALUE.value,
    }.get(ref.field_kind)
    if kind is None:
        return None
    return GroupPredicate(
        kind=kind,
        ifc_classes=(fact.ifc_class,),
        field_kind=ref.field_kind,
        set_name=ref.set_name,
        field_name=ref.field_name,
        operator=ref.operator,
        value=ref.value,
    )


def _collect_specs(facet_resolutions: list[Any]) -> dict[tuple, EvidenceGroup]:
    """One group per unique predicate signature, deduped across facets (§4)."""
    groups: dict[tuple, EvidenceGroup] = {}

    def _add(predicate, facet, label, similarity, source_kind, ontology_def):
        sig = predicate.signature()
        g = groups.get(sig)
        if g is None:
            g = EvidenceGroup(
                group_id=f"{_slug(facet.facet_id)}--{_slug(label)}",
                facet_id=facet.facet_id,
                label=label,
                predicate=predicate,
                role_hint=facet.role_hint,
                authority=AUTHORITY_SEMANTIC,
                coverage=COVERAGE_UNKNOWN,
                source_kinds=[source_kind],
                predicate_queryable=predicate.queryable,
                ontology_definition=ontology_def,
                similarity=similarity,
                facet_ids=[facet.facet_id],
            )
            groups[sig] = g
        else:
            g.similarity = max(g.similarity, similarity)
            if source_kind not in g.source_kinds:
                g.source_kinds.append(source_kind)
            if facet.facet_id not in g.facet_ids:
                g.facet_ids.append(facet.facet_id)
            if _ROLE_RANK.get(facet.role_hint, 3) < _ROLE_RANK.get(g.role_hint, 3):
                g.role_hint = facet.role_hint
            if ontology_def and not g.ontology_definition:
                g.ontology_definition = ontology_def

    for fr in facet_resolutions:
        onto_def = {c.ifc_class: c.profile_excerpt for c in fr.ontology_candidates}
        # class groups (present-in-model ontology candidates + model class candidates)
        seen_classes: set[str] = set()
        for c in fr.ontology_candidates:
            if c.present_in_model and c.ifc_class not in seen_classes:
                seen_classes.add(c.ifc_class)
                _add(
                    _class_predicate(c.ifc_class),
                    fr,
                    f"{c.ifc_class} objects",
                    c.similarity,
                    "semantic_resolution",
                    c.profile_excerpt,
                )
        for c in fr.model_class_candidates:
            if c.ifc_class not in seen_classes:
                seen_classes.add(c.ifc_class)
                _add(
                    _class_predicate(c.ifc_class),
                    fr,
                    f"{c.ifc_class} objects",
                    c.similarity,
                    "semantic_resolution",
                    onto_def.get(c.ifc_class),
                )
        # value-predicate groups (one claim each)
        for fact in fr.model_fact_candidates:
            pred = _fact_predicate(fact)
            if pred is None:
                continue
            label = f"{fact.ifc_class} {fact.field_name or fact.fact_kind}={fact.observed_value}"
            _add(
                pred,
                fr,
                label[:80],
                fact.similarity,
                "semantic_resolution",
                onto_def.get(fact.ifc_class),
            )
    return groups


# ---------------------------------------------------------------------------
# Public entry
# ---------------------------------------------------------------------------


def build_groups(
    session: Session,
    facet_resolutions: list[Any],
    policy: Any,  # RetrievalPolicy (frozen)
    source_model_id: int,
    *,
    settings: Settings,
    embedding_service_getter: Callable[[], Any],
    selection_entity_ids: list[int] | None = None,
) -> list[EvidenceGroup]:
    groups_by_sig = _collect_specs(facet_resolutions)
    groups = list(groups_by_sig.values())
    # Bound the number of groups deterministically (role, then similarity).
    groups.sort(key=lambda g: (_ROLE_RANK.get(g.role_hint, 3), -g.similarity, g.group_id))
    groups = groups[: settings.max_evidence_groups]

    if policy.sql:
        _execute_sql_groups(session, groups, source_model_id, settings)
        groups = _dedupe_full_class_value_groups(groups)

    if policy.rag_entity:
        _execute_rag_entity(
            session,
            facet_resolutions,
            groups,
            source_model_id,
            settings,
            embedding_service_getter,
        )

    # Deterministic factual profiles (§3), reusing the model-vocabulary class profiles.
    from app.query.hybrid.groups.profile import build_factual_profile
    from app.query.semantic.vocabulary.cache import get_model_vocabulary

    try:
        vocab = get_model_vocabulary(session, source_model_id, settings)
    except Exception:  # noqa: BLE001 - profile enrichment is best-effort
        vocab = None
    for g in groups:
        g.factual_profile = build_factual_profile(g, vocab)

    # Deterministic final order for the answerer/allocator.
    groups.sort(key=lambda g: (_ROLE_RANK.get(g.role_hint, 3), -(g.exact_count or 0), g.group_id))
    return groups


def _execute_sql_groups(
    session: Session, groups: list[EvidenceGroup], source_model_id: int, settings: Settings
) -> None:
    for g in groups:
        if not g.predicate.queryable:
            continue
        # Sample up to the small-group threshold so a small high-priority group
        # (e.g. the 9 stairs) has ALL members available to the allocator (§7).
        sample = max(settings.group_construction_sample_limit, settings.small_group_full_threshold)
        res = execute_predicate(
            session, g.predicate, source_model_id, sample_limit=sample, viewer_limit=sample
        )
        if not res.ok:
            g.coverage = COVERAGE_FAILED
            g.warnings.append(f"predicate verification failed: {res.error}")
            continue
        g.exact_count = res.exact_count
        g.representative_entities = res.representative_entities
        g.factual_profile = {"class_histogram": res.class_histogram}
        g.all_viewer_identities_available = True
        g.coverage = COVERAGE_COMPLETE
        g.authority = (
            AUTHORITY_EXACT
            if g.predicate.kind == PredicateKind.ENTITY_CLASS.value
            else AUTHORITY_STRUCTURED
        )
        if "sql" not in g.source_kinds:
            g.source_kinds.append("sql")


def _dedupe_full_class_value_groups(groups: list[EvidenceGroup]) -> list[EvidenceGroup]:
    """Drop a single-class value-predicate group whose exact count equals the
    class total — it selects the whole class and is redundant with the class
    group (Task 17 §4). A genuine subset (e.g. name~liftdeur < all doors) is kept."""
    class_counts: dict[str, int] = {}
    for g in groups:
        if (
            g.predicate.kind == PredicateKind.ENTITY_CLASS.value
            and len(g.predicate.ifc_classes) == 1
        ):
            if g.exact_count is not None:
                class_counts[g.predicate.ifc_classes[0]] = g.exact_count
    kept: list[EvidenceGroup] = []
    for g in groups:
        if (
            g.predicate.kind != PredicateKind.ENTITY_CLASS.value
            and len(g.predicate.ifc_classes) == 1
            and g.exact_count is not None
            and class_counts.get(g.predicate.ifc_classes[0]) == g.exact_count
        ):
            # merge provenance into the class group, then drop
            for cg in kept:
                if (
                    cg.predicate.kind == PredicateKind.ENTITY_CLASS.value
                    and cg.predicate.ifc_classes == g.predicate.ifc_classes
                ):
                    for sk in g.source_kinds:
                        if sk not in cg.source_kinds:
                            cg.source_kinds.append(sk)
                    break
            continue
        kept.append(g)
    return kept


def _execute_rag_entity(
    session: Session,
    facet_resolutions: list[Any],
    groups: list[EvidenceGroup],
    source_model_id: int,
    settings: Settings,
    embedding_service_getter: Callable[[], Any],
) -> None:
    try:
        emb = embedding_service_getter()
    except (EmbeddingServiceUnavailableError, DegradedCapabilityError):
        for g in groups:
            g.warnings.append("entity RAG unavailable; using structured evidence only")
        return

    class_group_by_class: dict[str, EvidenceGroup] = {
        g.predicate.ifc_classes[0]: g
        for g in groups
        if g.predicate.kind == PredicateKind.ENTITY_CLASS.value and g.predicate.ifc_classes
    }
    for fr in facet_resolutions:
        plan = RagSearchPlan(
            source_model_id=source_model_id,
            semantic_query=fr.semantic_query,
            search_entity_documents=True,
            search_relationship_documents=False,
            top_k_per_kind=max(settings.rag_facet_top_k, 30),
            visible_limit=min(settings.rag_facet_top_k, 50),
        )
        try:
            rag_res = run_rag_search(session, emb, plan)
        except (EmbeddingServiceUnavailableError, DegradedCapabilityError):
            continue
        candidates = rag_res.entity_candidates[: settings.rag_facet_top_k]
        if not candidates:
            continue
        ids = [c.canonical_id for c in candidates]
        rows = session.execute(
            sa.select(*entity_hydration_columns()).where(
                _ET.c.source_model_id == source_model_id, _ET.c.id.in_(ids)
            )
        ).all()
        by_id = {r.id: r for r in rows}
        remainder: list[int] = []
        for c in candidates:
            row = by_id.get(c.canonical_id)
            if row is None:
                continue
            cls_group = class_group_by_class.get(row.ifc_class)
            if cls_group is not None:
                # RAG enriches an exact class group: ordering + provenance only (§4).
                cls_group.candidate_entity_ids.append(c.canonical_id)
                cls_group.rag_candidate_count = (cls_group.rag_candidate_count or 0) + 1
                if "rag_entity" not in cls_group.source_kinds:
                    cls_group.source_kinds.append("rag_entity")
            else:
                remainder.append(c.canonical_id)
        if remainder:
            _add_rag_only_group(session, fr, remainder, groups, source_model_id, settings)


def _add_rag_only_group(
    session: Session,
    fr: Any,
    entity_ids: list[int],
    groups: list[EvidenceGroup],
    source_model_id: int,
    settings: Settings,
) -> None:
    ids = tuple(entity_ids[: settings.rag_facet_top_k])
    predicate = GroupPredicate(kind=PredicateKind.ENTITY_ID_SET.value, entity_ids=ids)
    rows = session.execute(
        sa.select(*entity_hydration_columns()).where(
            _ET.c.source_model_id == source_model_id, _ET.c.id.in_(ids)
        )
    ).all()
    by_id = {r.id: r for r in rows}
    reps = [hydrate_primary_entity(by_id[i]) for i in ids if i in by_id]
    groups.append(
        EvidenceGroup(
            group_id=f"{_slug(fr.facet_id)}--rag-candidates",
            facet_id=fr.facet_id,
            label=f"semantic candidates for '{fr.semantic_query[:40]}'",
            predicate=predicate,
            role_hint=fr.role_hint,
            authority=AUTHORITY_SEMANTIC,
            coverage=COVERAGE_BOUNDED,  # bounded candidates, NEVER an exact total (§4)
            source_kinds=["rag_entity"],
            predicate_queryable=True,
            rag_candidate_count=len(reps),
            representative_entities=reps[: settings.group_construction_sample_limit],
            candidate_entity_ids=list(ids),
            facet_ids=[fr.facet_id],
            all_viewer_identities_available=True,
        )
    )
