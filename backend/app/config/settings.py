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
    openai_timeout_s: float = 120.0

    # --- Task 25 §6 role/model/effort defaults ---
    # Three independently-configurable roles on the Responses API with strict
    # structured outputs. The binder is the hardest interpretation step; the
    # correction is rare and handles a proven recoverable gap; the answer writer
    # expresses already-adjudicated evidence and needs the least reasoning and a
    # smaller output limit. A configured model that is unavailable must fail
    # clearly — the client never silently substitutes another model (§6).
    # Cost-reduced roster (owner-selected 2026-07-21) in place of the §6 flagship
    # defaults: the ~1MB manifest makes each binder call's input dominate cost, so
    # a cheap nano binder plus a low-effort mini answer writer cuts spend roughly
    # 20x while keeping the manifest+ledger accuracy machinery unchanged.
    binder_model: str = "gpt-5.4-nano"
    binder_reasoning_effort: str = "medium"
    binder_max_output_tokens: int = 16000

    # The rare corrective retry stays in the binder family, one reasoning step up.
    correction_model: str = "gpt-5.4-nano"
    correction_reasoning_effort: str = "high"
    correction_max_output_tokens: int = 16000

    answer_model: str = "gpt-5.4-mini"
    answer_reasoning_effort: str = "low"
    answer_max_output_tokens: int = 4000

    #: Service tier reported to the pricing registry when the provider omits one.
    openai_service_tier: str = "standard"

    # At most ONE bounded application retry for a short transient connection,
    # rate-limit, or provider 5xx failure. A full request timeout is deliberately
    # NOT retried, and SDK-internal retries are disabled (`max_retries=0` in
    # llm.client) so the two cannot multiply.
    openai_max_retries: int = 1
    openai_retry_backoff_s: float = 1.5

    # Explicit per-role overrides, applied over the defaults above when set.
    binder_model_override: str | None = None
    correction_model_override: str | None = None
    answer_model_override: str | None = None

    def get_binder_model(self) -> str:
        return self.binder_model_override or self.binder_model

    def get_correction_model(self) -> str:
        return self.correction_model_override or self.correction_model

    def get_answer_model(self) -> str:
        return self.answer_model_override or self.answer_model

    # Back-compat alias: the binder was historically the "planner". Kept so any
    # remaining caller/diagnostic that asks for the planner model resolves to the
    # binder role rather than breaking.
    def get_planner_model(self) -> str:
        return self.get_binder_model()

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

    # --- Semantic vocabulary / ontology bounds (Task 16 §3, §4, §5, §8) ---
    # Bound the model-specific vocabulary so profile generation is deterministic
    # and the entire vocabulary/database is NEVER passed to the LLM.
    vocab_max_values_per_profile: int = 20  # observed values per class/field profile
    vocab_max_representative_examples: int = 5  # original examples kept per profile
    vocab_max_profiles_to_planner: int = 30  # active-model profiles to one planner call
    vocab_max_profile_excerpt_chars: int = 500  # per profile excerpt
    vocab_max_facts_total: int = 1500  # internal cache cap on observed-fact profiles
    vocab_min_fact_occurrences: int = 2  # drop per-instance singleton noise from value facts
    # Pre-planner semantic resolution top-k (threshold-free, Task 16 §4).
    semantic_resolution_top_k: int = 12  # ontology candidates surfaced to the planner
    semantic_resolution_model_top_k: int = 15  # model vocab candidates surfaced

    # --- Universal hybrid probe limits (Task 16 §5) ---
    max_probes_total: int = 10
    max_sql_probes: int = 4
    max_semantic_probes: int = 4  # ontology + model_vocabulary combined
    max_rag_probes: int = 4  # rag_entity + rag_relationship combined
    max_graph_probes: int = 2
    # Semantic candidates surfaced per probe into the evidence package (Task 16 §8).
    max_semantic_candidates_per_probe: int = 10
    max_semantic_candidates_per_probe_hard: int = 20
    max_probe_summaries_to_answerer: int = 10

    # --- Evidence groups + group-aware allocation (Task 17 §3, §6, §7) ---
    max_evidence_groups: int = 24  # bounded groups built per question
    group_construction_sample_limit: int = 8  # representative entities fetched per group
    max_answer_examples: int = 50  # total detailed examples across all groups (LLM budget)
    small_group_full_threshold: int = 12  # a direct group this small is included whole if it fits
    rag_facet_top_k: int = 12  # threshold-free RAG candidates per facet

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

    # --- Semantic manifests (task25 §2.1) ---
    # Backend-owned root for ingestion-generated semantic manifests
    # (model_semantics/{source_model_id}/{fingerprint}.semantic.json). ONE
    # configuration value shared with ingestion via the repo-root `.env`, TWO
    # independent resolvers — the backend never imports ingestion code (Task 09).
    # Deliberately separate from `viewer_asset_root`: §2.1 forbids mixing
    # semantic JSON with viewer fragments.
    model_semantics_root: str | None = None

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

    def get_model_semantics_root(self) -> Path:
        """Resolve the configured semantic-manifest root (task25 §2.1).

        Defaults to `<repo-root>/model_semantics`, matching the default the
        ingestion project resolves independently from the same `.env` key.
        """
        if self.model_semantics_root:
            return Path(self.model_semantics_root)
        return _REPO_ROOT / "model_semantics"

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
