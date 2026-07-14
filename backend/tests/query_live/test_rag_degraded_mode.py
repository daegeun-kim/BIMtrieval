"""SQL/graph paths remain usable when the embedding service is unavailable
(spec_v004 §4, §12, §14). This is the acceptance-critical guarantee: a RAG
failure must never disable deterministic query paths."""

from __future__ import annotations

import pytest
from query.rag.embedding_service import EmbeddingService, EmbeddingServiceState
from query.rag.errors import EmbeddingServiceUnavailableError
from query.rag.schemas import RagSearchPlan
from query.rag.search import run_rag_search
from query.sql import entities as sql_entities
from query.sql.schemas import CountEntitiesPlan

from .conftest import SOURCE_MODEL_ID


def test_bad_model_name_fails_permanently_without_auto_retry():
    bad = EmbeddingService(model_name="not-a-real-model-xyz")
    with pytest.raises(EmbeddingServiceUnavailableError):
        bad.ensure_loaded()
    assert bad.state is EmbeddingServiceState.FAILED
    # a second attempt must not silently substitute another model or retry
    with pytest.raises(EmbeddingServiceUnavailableError):
        bad.ensure_loaded()
    assert bad.state is EmbeddingServiceState.FAILED


def test_run_rag_search_raises_cleanly_when_embedding_service_is_down(live_session):
    bad = EmbeddingService(model_name="not-a-real-model-xyz")
    plan = RagSearchPlan(source_model_id=SOURCE_MODEL_ID, semantic_query="show me doors")
    with pytest.raises(EmbeddingServiceUnavailableError):
        run_rag_search(live_session, bad, plan)


def test_sql_path_still_works_after_simulated_rag_failure(live_session):
    bad = EmbeddingService(model_name="not-a-real-model-xyz")
    plan = RagSearchPlan(source_model_id=SOURCE_MODEL_ID, semantic_query="show me doors")
    with pytest.raises(EmbeddingServiceUnavailableError):
        run_rag_search(live_session, bad, plan)

    # the deterministic SQL path, same session/process, must be entirely unaffected
    n = sql_entities.count_entities(
        live_session, CountEntitiesPlan(source_model_id=SOURCE_MODEL_ID, entity_classes=["IfcDoor"])
    )
    assert n == 205


def test_rag_failure_does_not_touch_session_transaction_state(live_session):
    bad = EmbeddingService(model_name="not-a-real-model-xyz")
    plan = RagSearchPlan(source_model_id=SOURCE_MODEL_ID, semantic_query="show me doors")
    with pytest.raises(EmbeddingServiceUnavailableError):
        run_rag_search(live_session, bad, plan)
    # session remains usable for further queries in the same test
    n = sql_entities.count_entities(
        live_session, CountEntitiesPlan(source_model_id=SOURCE_MODEL_ID, entity_classes=["IfcWall"])
    )
    assert n == 648
