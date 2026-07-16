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
    # Falls back to the backend-owned db_url loader (app.config.database.get_db_url,
    # reading the shared repo-root .env) when unset — see get_database_url().
    # Kept as a distinct optional override so the backend can point at the
    # dedicated read-only role/DSN (spec_v002 Section 20). The backend never
    # imports ingestion code for this (Task 09).
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
    # These bound only what the ANSWER LLM sees. They are deliberately separate
    # from the exact database count (uncapped) and from the viewer match set
    # (max_viewer_match_ids) — see tasks/task13.md §2.
    max_primary_entities: int = 50
    max_context_entities: int = 50
    max_relationships: int = 20
    rag_rrf_constant: int = 60

    # --- Viewer match identities (task13 §2) ---
    # Identity-only retrieval for highlighting: how many matching GlobalIds a
    # single response may carry. Independent of the 50-item LLM evidence bound
    # and of the exact count, which is never capped by the application.
    max_viewer_match_ids: int = 2000

    # --- Orchestration concurrency / timeouts (spec_v005 §8) ---
    path_timeout_s: float = 20.0

    # --- Logging / dev surface (spec_v005 §15, §16) ---
    # Runtime logs live under the gitignored backend/logs/ (experiment output,
    # kept out of git). Paths are relative to the backend/ working directory,
    # the supported run location (`poetry run uvicorn app.main:app`). The curated,
    # versioned reusable failure-case dataset is a committed deliverable under
    # backend/app/evaluation/ (spec_v005 §16).
    query_log_path: str = "logs/query_events.jsonl"
    failure_case_path: str = "logs/failure_cases.jsonl"
    enable_dev_endpoints: bool = False
    # Opt-in local terminal tracing (task13 §1), enabled only by BIM_RAG_TRACE=1.
    # Disabled by default, not required in .env, never enabled automatically in
    # tests or production. It is developer observability, not a client feature:
    # trace records are never returned through the public API.
    bim_rag_trace: bool = False

    # --- Frontend viewer contract (spec_v006 §9, §10; Task 10) ---
    # Backend-owned root for prepared viewer artifacts
    # (model_assets/{source_model_id}/{source_fingerprint}.frag). Default
    # resolves under the repository root but is overrideable for tests/local
    # deployment. The resolved path is NEVER exposed to clients (Task 10 §2).
    viewer_asset_root: str | None = None
    # Explicit CORS allowlist for the local Vite frontend (spec_v006 §10.5).
    # No wildcard-with-credentials; overrideable via env (JSON list) without
    # placing any secret in frontend configuration.
    cors_allow_origins: list[str] = ["http://localhost:5173"]

    def get_viewer_asset_root(self) -> Path:
        """Resolve the configured viewer-asset root (Task 10 §2).

        Defaults to `<repo-root>/model_assets`. Callers never send this path to
        clients — it exists only to derive/contain artifact files server-side.
        """
        if self.viewer_asset_root:
            return Path(self.viewer_asset_root)
        return _REPO_ROOT / "model_assets"

    def get_database_url(self) -> str:
        """Resolve the database URL without ever printing/logging it.

        Prefers an explicit `database_url` override; otherwise uses the
        backend-owned loader (`app.config.database.get_db_url`) reading the
        shared repo-root `.env` value. No ingestion code is imported (Task 09).
        """
        if self.database_url is not None:
            return self.database_url.get_secret_value()
        from app.config.database import get_db_url

        return get_db_url()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
