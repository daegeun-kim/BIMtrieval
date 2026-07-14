"""Lazy persistent BGE-M3 service lifecycle, batch-one encoding, dimension,
normalization, and no query-vector persistence (spec_v004 §4, §15)."""

from __future__ import annotations

import math

from query.rag.embedding_service import EMBEDDING_DIM, EmbeddingService, EmbeddingServiceState


def test_service_starts_not_loaded():
    svc = EmbeddingService()
    assert svc.state is EmbeddingServiceState.NOT_LOADED


def test_ensure_loaded_transitions_to_ready(embedding_service):
    assert embedding_service.state is EmbeddingServiceState.READY
    assert embedding_service.device_str is not None


def test_ensure_loaded_is_idempotent(embedding_service):
    embedding_service.ensure_loaded()
    embedding_service.ensure_loaded()
    assert embedding_service.state is EmbeddingServiceState.READY


def test_query_embedding_is_1024_dim_and_l2_normalized(embedding_service):
    vec = embedding_service.embed_query("a door on the ground floor")
    assert len(vec) == EMBEDDING_DIM
    norm = math.sqrt(sum(x * x for x in vec))
    assert abs(norm - 1.0) < 1e-4


def test_query_embedding_is_batch_one_never_returns_a_batch(embedding_service):
    vec = embedding_service.embed_query("a single query string")
    assert isinstance(vec, list)
    assert all(isinstance(x, float) for x in vec)


def test_query_vector_is_a_plain_list_not_persisted_anywhere(embedding_service):
    """No function in query.rag.embedding_service writes to the database —
    this is a structural guarantee, verified by inspecting the module's
    source has no INSERT/session.add/session.execute call sites."""
    import inspect

    import query.rag.embedding_service as mod

    source = inspect.getsource(mod)
    assert "INSERT" not in source.upper()
    assert "session" not in source.lower()


def test_two_different_queries_produce_different_vectors(embedding_service):
    v1 = embedding_service.embed_query("show me all doors")
    v2 = embedding_service.embed_query("show me all windows")
    assert v1 != v2
