"""POST /api/query request-contract validation (offline).

The endpoint now runs the real planner/execute/answer pipeline (spec_v005), so
its happy-path behavior is validated with a live model + database in
tests/query_live/test_hybrid_live_openai.py. These offline tests only assert the
request schema is enforced before any handler/LLM/DB work happens.
"""

from __future__ import annotations


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
