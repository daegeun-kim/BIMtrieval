"""Settings load from env and never leak secrets via repr/str (spec_v002 Section 6)."""

from __future__ import annotations

from config.settings import Settings, get_settings


def test_defaults_use_gpt5_nano():
    settings = Settings(_env_file=None)
    assert settings.planner_model == "gpt-5-nano"
    assert settings.answer_model == "gpt-5-nano"


def test_secrets_never_appear_in_repr(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-testFAKEKEY1234567890")
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:sekret@localhost:5432/db")

    settings = get_settings()

    dump = repr(settings) + str(settings)
    assert "sk-testFAKEKEY1234567890" not in dump
    assert "sekret" not in dump
    # the secret is still retrievable when explicitly requested
    assert settings.openai_api_key.get_secret_value() == "sk-testFAKEKEY1234567890"
    assert settings.get_database_url() == "postgresql://user:sekret@localhost:5432/db"


def test_limits_have_spec_defaults():
    settings = Settings(_env_file=None)
    assert settings.default_list_limit == 50
    assert settings.max_list_limit == 500
    assert settings.default_graph_depth == 1
    assert settings.max_graph_depth == 3
    assert settings.max_selected_entity_ids == 5
