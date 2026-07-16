"""Independent exact / viewer / evidence limits + compact result summaries
(tasks/task13.md §2, §3).

The three limits must never interfere:

    exact database count   uncapped
    viewer match ids       max_viewer_match_ids (2,000)
    answer-LLM evidence    max_primary_entities (50)
"""

from __future__ import annotations

import pytest

from app.api.schemas.response import PrimaryEntityResult, SampleDetail
from app.config.settings import Settings
from app.query.hybrid.evidence import apply_bounds, build_answer_payload, build_result_summary
from app.query.hybrid.orchestrator import _ensure_viewer_matches, _select_actions
from app.query.hybrid.schemas import EvidencePackage
from app.query.sql import class_aliases
from app.query.sql.dispatch import _VIEWER_IDENTITY_OPS, SqlExecResult
from app.query.sql.schemas import SqlOperation
from app.viewer.actions import SelectionAction


def _entities(n: int, ifc_class: str = "IfcDoor") -> list[PrimaryEntityResult]:
    return [
        PrimaryEntityResult(entity_id=i, global_id=f"g{i}", ifc_class=ifc_class, name=f"e{i}")
        for i in range(n)
    ]


def _pkg(**kw) -> EvidencePackage:
    return EvidencePackage(question="q", route="sql", scope="active_model", source_model_id=1, **kw)


# ---------------------------------------------------------------------------
# Wall class expansion (task13 §2)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("requested", ["IfcWall", "ifcwall", "wall", "walls", "  Walls  "])
def test_wall_maps_to_both_stored_wall_classes(requested):
    assert class_aliases.expand_entity_classes([requested]) == ["IfcWall", "IfcWallStandardCase"]


def test_an_explicit_wall_subtype_request_is_not_widened():
    """Asking for IfcWallStandardCase must not silently add plain IfcWall."""
    assert class_aliases.expand_entity_classes(["IfcWallStandardCase"]) == ["IfcWallStandardCase"]


def test_unknown_classes_pass_through_untouched():
    assert class_aliases.expand_entity_classes(["IfcDoor", "IfcWindow"]) == ["IfcDoor", "IfcWindow"]


def test_expansion_preserves_order_and_deduplicates():
    assert class_aliases.expand_entity_classes(["IfcDoor", "IfcWall", "IfcWallStandardCase"]) == [
        "IfcDoor",
        "IfcWall",
        "IfcWallStandardCase",
    ]


def test_no_class_filter_stays_empty():
    assert class_aliases.expand_entity_classes([]) == []


def test_expansion_never_uses_fuzzy_substring_matching():
    # "IfcWallElementedCase" contains "IfcWall" but is a different stored class.
    assert class_aliases.expand_entity_classes(["IfcWallElementedCase"]) == ["IfcWallElementedCase"]
    assert class_aliases.expand_entity_classes(["IfcCurtainWall"]) == ["IfcCurtainWall"]


# ---------------------------------------------------------------------------
# Counts/aggregates produce viewer identities (task13 §2)
# ---------------------------------------------------------------------------


def test_count_and_aggregate_ops_are_included_in_viewer_identity_retrieval():
    """A count question must highlight the objects it counted."""
    assert SqlOperation.COUNT_ENTITIES in _VIEWER_IDENTITY_OPS
    assert SqlOperation.AGGREGATE_ENTITIES in _VIEWER_IDENTITY_OPS
    assert SqlOperation.LIST_ENTITIES in _VIEWER_IDENTITY_OPS
    assert SqlOperation.FILTER_ENTITIES in _VIEWER_IDENTITY_OPS


def test_count_result_produces_select_and_fit_viewer_actions():
    """ "How many doors are there?" -> exact count AND a select/fit action."""
    pkg = _pkg(
        viewer_global_ids=[f"g{i}" for i in range(205)],
        viewer_matches_total=205,
        class_histogram={"IfcDoor": 205},
        exact_totals={"sql_result": 205},
        sql_facts={"count": 205},
    )
    actions = _select_actions(pkg, Settings())

    assert actions.selection_action is SelectionAction.SELECT_AND_FIT
    assert len(actions.primary_global_ids) == 205
    assert actions.viewer_matches_total == 205
    assert actions.viewer_matches_truncated is False


def test_a_zero_result_produces_no_selection_rather_than_an_empty_fit():
    pkg = _pkg(viewer_global_ids=[], viewer_matches_total=0)
    actions = _select_actions(pkg, Settings())
    assert actions.selection_action is SelectionAction.NONE
    assert actions.primary_global_ids == []


# ---------------------------------------------------------------------------
# The three limits are independent (task13 §2)
# ---------------------------------------------------------------------------


def test_exact_count_is_unaffected_by_the_evidence_and_viewer_limits():
    settings = Settings(max_primary_entities=50, max_viewer_match_ids=2000)
    pkg = _pkg(
        primary_entities=_entities(205),
        viewer_global_ids=[f"g{i}" for i in range(205)],
        viewer_matches_total=205,
        class_histogram={"IfcDoor": 205},
    )
    apply_bounds(pkg, settings)

    # Evidence truncated to 50...
    assert len(pkg.primary_entities) == 50
    # ...viewer keeps all 205...
    assert len(pkg.viewer_global_ids) == 205
    # ...and the exact total is still 205.
    assert build_result_summary(pkg).exact_total == 205


def test_viewer_matches_are_captured_before_the_evidence_bound_is_applied():
    """RAG/graph/hybrid results must highlight their full match set, not the
    50 entities kept as LLM evidence (task13 §2)."""
    settings = Settings(max_primary_entities=50, max_viewer_match_ids=2000)
    pkg = _pkg(primary_entities=_entities(300))

    _ensure_viewer_matches(pkg, settings)  # orchestrator stage
    apply_bounds(pkg, settings)  # service stage

    assert len(pkg.viewer_global_ids) == 300
    assert pkg.viewer_matches_total == 300
    assert len(pkg.primary_entities) == 50


def test_viewer_identities_truncate_deterministically_above_the_cap():
    settings = Settings(max_viewer_match_ids=2000)
    pkg = _pkg(primary_entities=_entities(2500))

    _ensure_viewer_matches(pkg, settings)

    assert len(pkg.viewer_global_ids) == 2000
    assert pkg.viewer_matches_total == 2500  # exact total preserved
    assert pkg.viewer_matches_truncated is True
    # Deterministic: the first 2000 in stable order, not an arbitrary sample.
    assert pkg.viewer_global_ids[0] == "g0"
    assert pkg.viewer_global_ids[-1] == "g1999"
    assert any("2500 objects match" in w for w in pkg.warnings)


def test_truncation_does_not_change_the_exact_count():
    settings = Settings(max_viewer_match_ids=2000)
    pkg = _pkg(primary_entities=_entities(2500), exact_totals={"sql_result": 2500})
    _ensure_viewer_matches(pkg, settings)

    summary = build_result_summary(pkg)
    assert summary.exact_total == 2500
    assert summary.viewer_match_count == 2000
    assert summary.viewer_matches_total == 2500
    assert summary.truncated is True


def test_sql_supplied_viewer_identities_are_not_overwritten():
    """An identity-only SQL retrieval already ran; do not re-derive from evidence."""
    settings = Settings(max_viewer_match_ids=2000)
    pkg = _pkg(
        primary_entities=_entities(50),  # bounded evidence
        viewer_global_ids=[f"v{i}" for i in range(205)],
        viewer_matches_total=205,
        class_histogram={"IfcDoor": 205},
    )
    _ensure_viewer_matches(pkg, settings)

    assert pkg.viewer_matches_total == 205
    assert pkg.viewer_global_ids[0] == "v0"


# ---------------------------------------------------------------------------
# Compact result summary (task13 §3)
# ---------------------------------------------------------------------------


def test_result_summary_reports_compact_counts_grouped_by_ifc_class():
    pkg = _pkg(
        viewer_global_ids=["a", "b", "c", "d", "e", "f", "g", "h"],
        viewer_matches_total=8,
        class_histogram={"IfcDoor": 5, "IfcWindow": 3},
    )
    summary = build_result_summary(pkg)
    assert summary.class_counts == {"IfcDoor": 5, "IfcWindow": 3}
    assert summary.exact_total == 8
    assert summary.viewer_match_count == 8


def test_result_summary_falls_back_to_sql_exact_total_without_a_viewer_set():
    pkg = _pkg(exact_totals={"sql_result": 12})
    assert build_result_summary(pkg).exact_total == 12


def test_answer_payload_carries_the_compact_summary_and_bounded_evidence():
    settings = Settings(max_primary_entities=50, max_viewer_match_ids=2000)
    pkg = _pkg(
        primary_entities=_entities(205),
        viewer_global_ids=[f"g{i}" for i in range(205)],
        viewer_matches_total=205,
        class_histogram={"IfcDoor": 205},
    )
    apply_bounds(pkg, settings)
    payload = build_answer_payload(pkg)

    # The compact summary the answer should lead with.
    assert payload["result_summary"]["exact_total"] == 205
    assert payload["result_summary"]["class_counts"] == {"IfcDoor": 205}
    # Evidence stays at the 50 bound...
    assert len(payload["primary_entities"]) == 50
    # ...and the 205 viewer identities are NEVER sent to the LLM (task13 §3).
    assert "viewer_global_ids" not in payload
    assert "g150" not in str(payload)


def test_answer_payload_omits_sample_detail_for_ordinary_queries():
    pkg = _pkg(primary_entities=_entities(3), viewer_matches_total=3)
    payload = build_answer_payload(pkg)
    assert payload["result_summary"]["sample_detail"] is None


def test_answer_payload_includes_sample_detail_on_explicit_intent():
    pkg = _pkg(
        primary_entities=_entities(3),
        viewer_matches_total=3,
        sample_detail=SampleDetail(global_id="g0", ifc_class="IfcDoor", name="Door 1"),
    )
    payload = build_answer_payload(pkg)
    sample = payload["result_summary"]["sample_detail"]
    assert sample["global_id"] == "g0"
    assert sample["name"] == "Door 1"


# ---------------------------------------------------------------------------
# SqlExecResult contract (task13 §2)
# ---------------------------------------------------------------------------


def test_non_entity_operations_report_no_viewer_match_set():
    """viewer_matches_total=None means 'this op has no identity set', which is
    what makes `_ensure_viewer_matches` derive one from evidence instead."""
    res = SqlExecResult(operation="list_relationships")
    assert res.viewer_matches_total is None
    assert res.viewer_global_ids == []
    assert res.viewer_matches_truncated is False
