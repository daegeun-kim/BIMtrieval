"""RagSearchPlan validation (spec_v004 §5). No database access, no model load."""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from query.rag.schemas import (
    MAX_SELECTED_ENTITY_IDS,
    MAX_TOP_K_PER_KIND,
    MAX_VISIBLE_LIMIT,
    RagSearchPlan,
)


def test_valid_plan_accepted():
    plan = RagSearchPlan(source_model_id=1, semantic_query="components related to fire separation")
    assert plan.search_entity_documents is True
    assert plan.search_relationship_documents is True
    assert plan.minimum_similarity_profile == "default_v001"


def test_at_least_one_kind_required():
    with pytest.raises(ValidationError):
        RagSearchPlan(
            source_model_id=1,
            semantic_query="q",
            search_entity_documents=False,
            search_relationship_documents=False,
        )


def test_relationship_only_search_is_valid():
    plan = RagSearchPlan(source_model_id=1, semantic_query="q", search_entity_documents=False)
    assert plan.search_relationship_documents is True


def test_selected_entity_ids_capped():
    with pytest.raises(ValidationError):
        RagSearchPlan(
            source_model_id=1,
            semantic_query="q",
            selected_entity_ids=list(range(MAX_SELECTED_ENTITY_IDS + 1)),
        )
    RagSearchPlan(
        source_model_id=1,
        semantic_query="q",
        selected_entity_ids=list(range(MAX_SELECTED_ENTITY_IDS)),
    )


def test_top_k_and_visible_limit_bounded():
    with pytest.raises(ValidationError):
        RagSearchPlan(source_model_id=1, semantic_query="q", top_k_per_kind=MAX_TOP_K_PER_KIND + 1)
    with pytest.raises(ValidationError):
        RagSearchPlan(source_model_id=1, semantic_query="q", visible_limit=MAX_VISIBLE_LIMIT + 1)


def test_extra_fields_rejected():
    with pytest.raises(ValidationError):
        RagSearchPlan(source_model_id=1, semantic_query="q", raw_sql="SELECT 1")


def test_empty_query_rejected():
    with pytest.raises(ValidationError):
        RagSearchPlan(source_model_id=1, semantic_query="")
