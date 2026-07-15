"""redact_secrets() masks key-shaped and value-shaped secrets (spec_v002 Section 21)."""

from __future__ import annotations

import json

from app.config.logging import redact_secrets, write_jsonl_event


def test_redacts_secret_shaped_keys():
    record = {
        "question": "How many doors?",
        "openai_api_key": "sk-realkey1234567890",
        "nested": {"database_url": "postgresql://u:p@host/db", "safe_field": "keep me"},
    }
    redacted = redact_secrets(record)
    assert redacted["openai_api_key"] == "***REDACTED***"
    assert redacted["nested"]["database_url"] == "***REDACTED***"
    assert redacted["nested"]["safe_field"] == "keep me"
    assert redacted["question"] == "How many doors?"


def test_token_usage_metrics_are_not_redacted():
    """Token-COUNT metrics must survive redaction (spec_v005 §16 logs token usage),
    while real auth tokens are still masked."""
    record = {
        "token_usage": [{"model": "gpt-5-nano", "total_tokens": 289, "prompt_tokens": 76}],
        "auth_token": "secret-bearer-abc",
        "authorization": "Bearer xyz",
    }
    redacted = redact_secrets(record)
    assert redacted["token_usage"][0]["total_tokens"] == 289
    assert redacted["token_usage"][0]["prompt_tokens"] == 76
    assert redacted["auth_token"] == "***REDACTED***"
    assert redacted["authorization"] == "***REDACTED***"


def test_redacts_openai_key_shaped_value_in_free_text():
    record = {"message": "using key sk-abcdefghijklmnopqrstuvwxyz1234"}
    redacted = redact_secrets(record)
    assert "sk-abcdefghijklmnopqrstuvwxyz1234" not in redacted["message"]


def test_redacts_credentials_embedded_in_db_url_string():
    record = {"error": "connection failed: postgresql://user:hunter2@localhost:5432/bimrag"}
    redacted = redact_secrets(record)
    assert "hunter2" not in redacted["error"]


def test_write_jsonl_event_writes_redacted_line(tmp_path):
    path = tmp_path / "query_log.jsonl"
    write_jsonl_event({"request_id": "abc", "openai_api_key": "sk-shouldnotpersist12345"}, path)

    line = path.read_text(encoding="utf-8").strip()
    record = json.loads(line)
    assert record["request_id"] == "abc"
    assert record["openai_api_key"] == "***REDACTED***"
    assert "logged_at" in record
