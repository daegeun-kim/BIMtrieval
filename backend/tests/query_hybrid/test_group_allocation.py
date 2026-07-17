"""Group-aware allocation + group decision (Task 17 §7, §8, §13). Pure unit."""

from __future__ import annotations

from app.api.schemas.response import PrimaryEntityResult
from app.llm.client import AnswerOutput
from app.query.hybrid.groups.allocation import allocate_examples
from app.query.hybrid.groups.decision import resolve_group_answer
from app.query.hybrid.groups.schemas import (
    AUTHORITY_EXACT,
    AUTHORITY_SEMANTIC,
    COVERAGE_BOUNDED,
    COVERAGE_COMPLETE,
    EvidenceGroup,
    GroupPredicate,
    PredicateKind,
)
from app.shared.types import AnswerBasis

_EID = [0]


def _entities(n, cls="IfcX"):
    out = []
    for _ in range(n):
        _EID[0] += 1
        out.append(
            PrimaryEntityResult(
                entity_id=_EID[0], global_id=f"g{_EID[0]}", ifc_class=cls, name=None, summary=None
            )
        )
    return out


def _class_group(gid, cls, count, role="direct", authority=AUTHORITY_EXACT, reps=None):
    reps = reps if reps is not None else _entities(min(count, 12), cls)
    return EvidenceGroup(
        group_id=gid,
        facet_id="f",
        label=f"{cls} objects",
        predicate=GroupPredicate(kind=PredicateKind.ENTITY_CLASS.value, ifc_classes=(cls,)),
        role_hint=role,
        authority=authority,
        coverage=COVERAGE_COMPLETE,
        predicate_queryable=True,
        exact_count=count,
        representative_entities=reps,
    )


def test_small_high_priority_group_included_whole():
    stairs = _class_group("stairs", "IfcStair", 9)
    railings = _class_group("railings", "IfcRailing", 90, reps=_entities(12, "IfcRailing"))
    allocate_examples([stairs, railings], budget=50, small_group_threshold=12)
    # all 9 stairs survive; not displaced by railings
    assert len(stairs.allocated_examples) == 9
    assert stairs.allocation_truncated is False


def test_budget_capped_at_50_and_shared():
    groups = [
        _class_group(f"g{i}", f"IfcC{i}", 100, reps=_entities(20, f"IfcC{i}")) for i in range(6)
    ]
    meta = allocate_examples(groups, budget=50, small_group_threshold=12)
    assert meta["total_allocated"] == 50
    # no single group consumed all 50 (round-robin) — every group got some
    assert all(len(g.allocated_examples) > 0 for g in groups)
    assert all(len(g.allocated_examples) < 50 for g in groups)


def test_dedup_across_groups():
    shared = _entities(5, "IfcDup")
    g1 = _class_group("g1", "IfcDup", 5, reps=list(shared))
    g2 = _class_group("g2", "IfcDup", 5, reps=list(shared))
    allocate_examples([g1, g2], budget=50, small_group_threshold=12)
    all_ids = [e.entity_id for e in g1.allocated_examples] + [
        e.entity_id for e in g2.allocated_examples
    ]
    assert len(all_ids) == len(set(all_ids))  # no entity allocated twice


# --- decision ---------------------------------------------------------------


def _out(**kw):
    return AnswerOutput(answer="a", **kw)


def test_primary_and_rejected_roles():
    g = _class_group("stairs", "IfcStair", 9)
    r = _class_group("windows", "IfcWindow", 259)
    dec = resolve_group_answer(
        [g, r],
        _out(
            primary_group_ids=["stairs"],
            rejected_group_ids=["windows"],
            viewer_primary_group_ids=["stairs"],
        ),
    )
    assert [x.group_id for x in dec.accepted_primary] == ["stairs"]
    assert dec.rejected_ids == ["windows"]
    assert dec.answer_basis == AnswerBasis.EXACT_SQL


def test_unknown_group_id_fails_safe():
    g = _class_group("stairs", "IfcStair", 9)
    dec = resolve_group_answer(
        [g], _out(primary_group_ids=["ghost"], viewer_primary_group_ids=["ghost"])
    )
    assert any("unknown" in w for w in dec.warnings)
    assert dec.viewer_primary == []
    assert dec.answer_basis == AnswerBasis.INSUFFICIENT_EVIDENCE


def test_contradictory_group_excluded():
    g = _class_group("stairs", "IfcStair", 9)
    dec = resolve_group_answer(
        [g], _out(primary_group_ids=["stairs"], rejected_group_ids=["stairs"])
    )
    assert any("both accepted and rejected" in w for w in dec.warnings)
    assert dec.accepted_primary == []


def test_rejected_group_not_in_viewer():
    g = _class_group("stairs", "IfcStair", 9)
    r = _class_group("windows", "IfcWindow", 259)
    dec = resolve_group_answer(
        [g, r],
        _out(
            primary_group_ids=["stairs"],
            rejected_group_ids=["windows"],
            viewer_primary_group_ids=["stairs", "windows"],
        ),
    )
    assert [x.group_id for x in dec.viewer_primary] == ["stairs"]  # windows excluded


def test_rag_only_acceptance_is_semantic_basis():
    rag = EvidenceGroup(
        group_id="rag",
        facet_id="f",
        label="candidates",
        predicate=GroupPredicate(kind=PredicateKind.ENTITY_ID_SET.value, entity_ids=(1, 2)),
        role_hint="direct",
        authority=AUTHORITY_SEMANTIC,
        coverage=COVERAGE_BOUNDED,
        predicate_queryable=True,
        rag_candidate_count=2,
        representative_entities=_entities(2),
    )
    dec = resolve_group_answer(
        [rag], _out(primary_group_ids=["rag"], viewer_primary_group_ids=["rag"])
    )
    assert dec.answer_basis == AnswerBasis.SEMANTIC_RETRIEVAL
