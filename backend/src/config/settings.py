"""Backend runtime configuration.

Loads OPENAI_API_KEY, model names, database connectivity, and the shared
limits/timeouts referenced throughout spec_v002_query_architecture.md.
Secrets (`openai_api_key`, `database_url`) are typed as `SecretStr` so they
never appear in `repr()`/`str()`/log output. Never print `.get_secret_value()`.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

_REPO_ROOT = Path(__file__).resolve().parents[3]
_ENV_FILE = _REPO_ROOT / ".env"


class Settings(BaseSettings):
    """spec_v002 Section 6 (LLM config) + Section 9/10/11/15 (limits)."""

    model_config = SettingsConfigDict(
        env_file=_ENV_FILE,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- LLM (Section 6) ---
    openai_api_key: SecretStr | None = None
    planner_model: str = "gpt-5-nano"
    answer_model: str = "gpt-5-nano"
    openai_timeout_s: float = 60.0
    # gpt-5-nano is a reasoning model: reasoning tokens count against the
    # completion budget, so a small cap makes it hit the length limit before
    # emitting the full structured JSON (observed on complex planner prompts in
    # task08). Keep this generous so structured output always completes.
    openai_max_output_tokens: int = 16000
    # Bounded retry on transient provider errors (timeout/rate-limit/5xx) — the
    # planner/answer loop itself is never retried unboundedly (spec_v005 §17).
    openai_max_retries: int = 2
    openai_retry_backoff_s: float = 1.5
    # Independently configurable so planner/answer models can be replaced later
    # (spec_v005 §4). Left as None here — planner_model/answer_model are the
    # canonical knobs; these exist only as explicit per-role overrides if ever set.
    planner_model_override: str | None = None
    answer_model_override: str | None = None

    def get_planner_model(self) -> str:
        return self.planner_model_override or self.planner_model

    def get_answer_model(self) -> str:
        return self.answer_model_override or self.answer_model

    # --- Database ---
    # Falls back to bim_rag.config.get_db_url() (the existing ingestion .env
    # loader) when unset — see get_database_url(). Kept as a distinct optional
    # override so the query backend can point at a read-only role/DSN later
    # (spec_v002 Section 20) without touching ingestion configuration.
    database_url: SecretStr | None = None
    db_statement_timeout_ms: int = 5000

    # --- Result / traversal limits (Section 9, 10, 11.2, 15) ---
    default_list_limit: int = 50
    max_list_limit: int = 500
    default_graph_depth: int = 1
    max_graph_depth: int = 3
    rag_display_candidates: int = 10
    rag_internal_candidates_per_kind: int = 30
    max_selected_entity_ids: int = 5
    max_history_turns: int = 20

    # --- Hybrid evidence bounds (spec_v005 §10) ---
    max_primary_entities: int = 50
    max_context_entities: int = 50
    max_relationships: int = 20
    rag_rrf_constant: int = 60

    # --- Orchestration concurrency / timeouts (spec_v005 §8) ---
    path_timeout_s: float = 20.0

    # --- Logging / dev surface (spec_v005 §15, §16) ---
    # Runtime logs live under the gitignored backend/logs/ (experiment output,
    # kept out of git). The curated, versioned reusable failure-case dataset is a
    # committed deliverable under backend/src/evaluation/ (spec_v005 §16).
    query_log_path: str = "backend/logs/query_events.jsonl"
    failure_case_path: str = "backend/logs/failure_cases.jsonl"
    enable_dev_endpoints: bool = False

    def get_database_url(self) -> str:
        """Resolve the database URL without ever printing/logging it.

        Prefers an explicit `database_url` override; otherwise reuses the
        existing ingestion loader (`bim_rag.config.get_db_url`) so both
        ingestion and query paths read the same `.env` value by default.
        """
        if self.database_url is not None:
            return self.database_url.get_secret_value()
        from bim_rag.config import get_db_url

        return get_db_url()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
