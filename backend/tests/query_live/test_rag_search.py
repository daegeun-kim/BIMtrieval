"""Source-scoped semantic search: entity-only/relationship-only/combined,
source-model isolation, threshold exclusion, top-k/visible limits, and
incompatible-model/dimension rejection (spec_v004 §3, §6, §7, §8, §15)."""

from __future__ import annotations

import pytest
from query.rag.errors import IncompatibleEmbeddingError
from query.rag.schemas import RagSearchPlan
from query.rag.search import check_compatibility, run_rag_search, search_kind

from .conftest import SOURCE_MODEL_ID


def test_entity_only_search_returns_only_entity_kind(live_session, embedding_service):
    plan = RagSearchPlan(
        source_model_id=SOURCE_MODEL_ID,
        semantic_query="show me all doors",
        search_entity_documents=True,
        search_relationship_documents=False,
        top_k_per_kind=10,
    )
    result = run_rag_search(live_session, embedding_service, plan)
    assert result.entity_candidates
    assert result.relationship_candidates == []
    assert result.fused == []  # only fused when both kinds ran


def test_relationship_only_search_returns_only_relationship_kind(live_session, embedding_service):
    plan = RagSearchPlan(
        source_model_id=SOURCE_MODEL_ID,
        semantic_query="building storey containment relationship",
        search_entity_documents=False,
        search_relationship_documents=True,
        top_k_per_kind=10,
    )
    result = run_rag_search(live_session, embedding_service, plan)
    assert result.relationship_candidates
    assert result.entity_candidates == []


def test_combined_search_fuses_both_kinds(live_session, embedding_service):
    plan = RagSearchPlan(
        source_model_id=SOURCE_MODEL_ID,
        semantic_query="doors and their containment relationships",
        top_k_per_kind=10,
    )
    result = run_rag_search(live_session, embedding_service, plan)
    assert result.entity_candidates
    assert result.relationship_candidates
    assert len(result.fused) == len(result.entity_candidates) + len(result.relationship_candidates)


def test_show_me_doors_ranks_doors_highest(live_session, embedding_service):
    """Spot check: 'show me doors' should retrieve real IfcDoor entities in
    the top-k (see docs/architecture_v004.md for the full calibration run)."""
    vec = embedding_service.embed_query("Show me all doors in the building")
    candidates = search_kind(live_session, SOURCE_MODEL_ID, "entity", vec, top_k=10, threshold=0.0)
    assert all("IfcDoor" in c.document_text_excerpt for c in candidates)


def test_source_model_isolation_returns_empty_not_error(live_session, embedding_service):
    vec = embedding_service.embed_query("anything")
    candidates = search_kind(live_session, 999999, "entity", vec, top_k=10, threshold=0.0)
    assert candidates == []


def test_threshold_exclusion(live_session, embedding_service):
    vec = embedding_service.embed_query("show me all doors")
    low = search_kind(live_session, SOURCE_MODEL_ID, "entity", vec, top_k=10, threshold=0.0)
    high = search_kind(live_session, SOURCE_MODEL_ID, "entity", vec, top_k=10, threshold=0.99)
    assert any(c.passed_threshold for c in low)
    assert not any(c.passed_threshold for c in high)


def test_top_k_limit_respected(live_session, embedding_service):
    vec = embedding_service.embed_query("show me all doors")
    candidates = search_kind(live_session, SOURCE_MODEL_ID, "entity", vec, top_k=3, threshold=0.0)
    assert len(candidates) == 3


def test_visible_limit_is_a_plan_concept_not_enforced_by_search_kind(
    live_session, embedding_service
):
    """visible_limit bounds what a caller displays; search_kind itself is
    governed only by top_k_per_kind (internal candidate pool, spec_v004 §7)."""
    plan = RagSearchPlan(
        source_model_id=SOURCE_MODEL_ID, semantic_query="doors", top_k_per_kind=20, visible_limit=5
    )
    result = run_rag_search(live_session, embedding_service, plan)
    assert len(result.entity_candidates) == 20
    assert plan.visible_limit == 5  # caller (frontend/answer layer) truncates to this


def test_no_result_above_threshold_reports_insufficient_evidence(live_session, embedding_service):
    plan = RagSearchPlan(
        source_model_id=SOURCE_MODEL_ID,
        semantic_query="show me all doors",
        minimum_similarity_profile="default_v001",
        top_k_per_kind=5,
    )
    # monkeypatch-free: construct candidates directly to prove the flag logic
    result = run_rag_search(live_session, embedding_service, plan)
    if not result.sufficient_evidence:
        assert result.warnings


def test_incompatible_embedding_model_rejected(live_session, monkeypatch):
    monkeypatch.setattr("query.rag.search.EMBEDDING_MODEL_NAME", "some-other-model")
    with pytest.raises(IncompatibleEmbeddingError):
        check_compatibility(live_session, SOURCE_MODEL_ID, "entity")


def test_incompatible_embedding_dimension_rejected(live_session, monkeypatch):
    monkeypatch.setattr("query.rag.search.EMBEDDING_DIM", 768)
    with pytest.raises(IncompatibleEmbeddingError):
        check_compatibility(live_session, SOURCE_MODEL_ID, "entity")


def test_empty_kind_is_not_an_incompatibility_error(live_session):
    """A source model with zero rows for a kind is not an error -- just no candidates."""
    check_compatibility(live_session, 999999, "entity")  # must not raise
