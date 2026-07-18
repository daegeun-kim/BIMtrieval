"""POST /api/query request-contract validation (offline).

The endpoint now runs the real planner/execute/answer pipeline (spec_v005), so
its happy-path behavior is validated with a live model + database in
tests/query_live/test_hybrid_live_openai.py. These offline tests only assert the
request schema is enforced before any handler/LLM/DB work happens.
"""

from __future__ import annotations

import logging


def test_missing_question_is_rejected(client):
    resp = client.post("/api/query", json={"session_id": "s1"})
    assert resp.status_code == 422


def test_more_than_five_selected_entities_is_rejected(client):
    resp = client.post(
        "/api/query",
        json={"question": "q", "session_id": "s1", "selected_entity_ids": [1, 2, 3, 4, 5, 6]},
    )
    assert resp.status_code == 422


def test_unknown_field_is_rejected(client):
    resp = client.post(
        "/api/query",
        json={"question": "q", "session_id": "s1", "raw_sql": "SELECT 1"},
    )
    assert resp.status_code == 422


def test_more_than_five_selected_global_ids_is_rejected(client):
    resp = client.post(
        "/api/query",
        json={
            "question": "q",
            "session_id": "s1",
            "active_source_model_id": 1,
            "selected_global_ids": ["G1", "G2", "G3", "G4", "G5", "G6"],
        },
    )
    assert resp.status_code == 422


def test_selected_global_ids_without_active_model_returns_bounded_error(client):
    # Reject happens before any LLM/DB work (spec_v006 §10.4), so this succeeds
    # offline with no OpenAI/database access.
    resp = client.post(
        "/api/query",
        json={"question": "q", "session_id": "s1", "selected_global_ids": ["G1"]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "error"
    assert "active model" in body["answer"].lower()


def test_render_timing_accepts_bounded_browser_telemetry(client, caplog):
    caplog.set_level(logging.INFO, logger="bim_rag_backend")
    resp = client.post(
        "/api/query/render-timing",
        json={
            "request_id": "r-timing",
            "response_received_ms": 1200.5,
            "viewer_render_ms": 42.2,
            "total_to_viewer_ms": 1242.7,
        },
    )
    assert resp.status_code == 204
    assert "[Query render timing]" in caplog.text
    assert "total_query_to_viewer_ms: 1242.7" in caplog.text
