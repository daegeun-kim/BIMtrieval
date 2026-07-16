"""Settings load from env and never leak secrets via repr/str (spec_v002 Section 6)."""

from __future__ import annotations

from app.config.settings import Settings, get_settings


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


def test_trace_is_off_by_default_and_not_required_in_env(monkeypatch):
    """Tracing is opt-in developer observability (task13 §1): absent env var
    must not fail construction and must leave it disabled."""
    monkeypatch.delenv("BIM_RAG_TRACE", raising=False)
    assert Settings(_env_file=None).bim_rag_trace is False


def test_trace_is_enabled_by_the_documented_env_var(monkeypatch):
    monkeypatch.setenv("BIM_RAG_TRACE", "1")
    get_settings.cache_clear()
    assert get_settings().bim_rag_trace is True


def test_viewer_match_limit_is_independent_of_the_evidence_limit():
    """The three limits in task13 §2 are separate knobs."""
    settings = Settings(_env_file=None)
    assert settings.max_viewer_match_ids == 2000
    assert settings.max_primary_entities == 50
    assert settings.max_viewer_match_ids != settings.max_list_limit
