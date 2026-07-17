"""OpenAI planner + answer client using schema-enforced structured outputs
(spec_v005 §2, §4, §11).

Two roles, independently configurable models (`planner_model` / `answer_model`,
spec_v005 §4):

- `plan_query()` → one `QueryPlan` (structured output). This is OpenAI call 1.
- `generate_answer()` → one `AnswerOutput` (structured output). This is call 2.

Secret handling (task07 §Secret handling): the API key is read from settings
(runtime env / .env) only. It is never logged, printed, hard-coded, or returned.
If the key is absent, `plan_query`/`generate_answer` raise `LLMUnavailableError`
with a sanitized message and no network call is made. The `openai.OpenAI`
object is built lazily so importing/instantiating this module never touches the
network.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field

from app.config.settings import Settings, get_settings
from app.llm.prompts import (
    ANSWERER_PROMPT_VERSION,
    GROUP_ANSWERER_PROMPT_VERSION,
    PLANNER_PROMPT_VERSION,
    POLICY_PLANNER_PROMPT_VERSION,
    answerer_prompt,
    group_answerer_prompt,
    planner_prompt,
    policy_planner_prompt,
)
from app.llm.schemas import QueryPlan, RetrievalPolicyPlan
from app.llm.serialization import dumps_context

if TYPE_CHECKING:
    from openai import OpenAI


class LLMError(RuntimeError):
    """Base class for sanitized LLM-layer failures (never carries secrets)."""


class LLMUnavailableError(LLMError):
    """OPENAI_API_KEY missing/unusable, or the provider could not be reached."""


class LLMRefusalError(LLMError):
    """The model refused or returned no parseable structured output."""


@dataclass
class TokenUsage:
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    @classmethod
    def from_response(cls, model: str, usage: Any) -> "TokenUsage":
        if usage is None:
            return cls(model=model)
        return cls(
            model=model,
            prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
            completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
            total_tokens=getattr(usage, "total_tokens", 0) or 0,
        )

    def as_dict(self) -> dict[str, int | str]:
        return {
            "model": self.model,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
        }


class AnswerOutput(BaseModel):
    """Structured answer envelope (spec_v005 §11, §16 + Task 16 §9).

    The universal-hybrid answerer is a relevance judge: it explicitly accepts or
    rejects each probe as a candidate reference and selects which probes drive
    viewer highlights. The probe-decision fields default empty/false so the
    legacy answer path (which does not use probes) stays valid."""

    model_config = ConfigDict(extra="forbid")

    answer: str = Field(min_length=1)
    used_general_knowledge: bool = False
    disclosed_conflicts: bool = False
    model_evidence_sufficient: bool = True
    inference_used: bool = False
    # --- Group relevance decisions (Task 17 §8) ---
    primary_group_ids: list[str] = Field(default_factory=list)
    supporting_group_ids: list[str] = Field(default_factory=list)
    context_group_ids: list[str] = Field(default_factory=list)
    rejected_group_ids: list[str] = Field(default_factory=list)
    viewer_primary_group_ids: list[str] = Field(default_factory=list)
    viewer_context_group_ids: list[str] = Field(default_factory=list)
    inference_basis_group_ids: list[str] = Field(default_factory=list)


@dataclass
class PlanResult:
    plan: QueryPlan
    usage: TokenUsage


@dataclass
class PolicyResult:
    plan: RetrievalPolicyPlan
    usage: TokenUsage


@dataclass
class AnswerResult:
    output: AnswerOutput
    usage: TokenUsage


@dataclass
class LLMCallLog:
    """Per-call, secret-free trace accumulated by a client instance."""

    calls: list[dict[str, Any]] = field(default_factory=list)


class OpenAIQueryClient:
    """Real planner/answer client. Constructs the OpenAI SDK lazily."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._client: "OpenAI | None" = None
        self.log = LLMCallLog()

    def _get_client(self) -> "OpenAI":
        if self._client is None:
            api_key = self.settings.openai_api_key
            if api_key is None or not api_key.get_secret_value().strip():
                raise LLMUnavailableError(
                    "OPENAI_API_KEY is not configured; cannot reach the planner/answer model."
                )
            from openai import OpenAI

            self._client = OpenAI(
                api_key=api_key.get_secret_value(),
                timeout=self.settings.openai_timeout_s,
            )
        return self._client

    def plan_query(self, planner_context: dict[str, Any]) -> PlanResult:
        """OpenAI call 1: route + complete typed plan (spec_v005 §2, §5)."""
        model = self.settings.get_planner_model()
        parsed, usage = self._structured_call(
            model=model,
            system=planner_prompt(),
            user_payload=planner_context,
            response_format=QueryPlan,
            prompt_version=PLANNER_PROMPT_VERSION,
            role="planner",
        )
        return PlanResult(plan=parsed, usage=usage)

    def plan_retrieval_policy(self, policy_context: dict[str, Any]) -> PolicyResult:
        """Task 17 LLM call 1: the QUERY-ONLY retrieval policy + facet plan. The
        input carries no active-model candidates/schema (see build_policy_context),
        so modality selection cannot depend on model contents."""
        model = self.settings.get_planner_model()
        parsed, usage = self._structured_call(
            model=model,
            system=policy_planner_prompt(),
            user_payload=policy_context,
            response_format=RetrievalPolicyPlan,
            prompt_version=POLICY_PLANNER_PROMPT_VERSION,
            role="policy_planner",
        )
        return PolicyResult(plan=parsed, usage=usage)

    def generate_answer(self, evidence_payload: dict[str, Any]) -> AnswerResult:
        """OpenAI call 2 (legacy path): grounded answer from bounded evidence."""
        model = self.settings.get_answer_model()
        parsed, usage = self._structured_call(
            model=model,
            system=answerer_prompt(),
            user_payload=evidence_payload,
            response_format=AnswerOutput,
            prompt_version=ANSWERER_PROMPT_VERSION,
            role="answerer",
        )
        return AnswerResult(output=parsed, usage=usage)

    def generate_group_answer(self, evidence_payload: dict[str, Any]) -> AnswerResult:
        """Task 17 LLM call 2: group-level relevance judgment + answer from
        accepted evidence groups (Task 17 §8)."""
        model = self.settings.get_answer_model()
        parsed, usage = self._structured_call(
            model=model,
            system=group_answerer_prompt(),
            user_payload=evidence_payload,
            response_format=AnswerOutput,
            prompt_version=GROUP_ANSWERER_PROMPT_VERSION,
            role="group_answerer",
        )
        return AnswerResult(output=parsed, usage=usage)

    def _structured_call(
        self,
        *,
        model: str,
        system: str,
        user_payload: dict[str, Any],
        response_format: type[BaseModel],
        prompt_version: str,
        role: str,
    ) -> tuple[Any, TokenUsage]:
        client = self._get_client()
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": dumps_context(user_payload)},
        ]
        # Bounded retry on transient provider errors only (timeout / rate limit /
        # connection / 5xx) — gpt-5-nano reasoning latency is high, so a single
        # retry keeps the pipeline robust without an unbounded loop (spec_v005 §17).
        attempts = max(1, self.settings.openai_max_retries + 1)
        last_exc: Exception | None = None
        completion = None
        for attempt in range(attempts):
            try:
                completion = client.chat.completions.parse(
                    model=model,
                    messages=messages,
                    response_format=response_format,
                    max_completion_tokens=self.settings.openai_max_output_tokens,
                )
                break
            except Exception as exc:  # noqa: BLE001 - classify then retry/raise
                last_exc = exc
                if attempt + 1 < attempts and _is_transient(exc):
                    time.sleep(self.settings.openai_retry_backoff_s * (attempt + 1))
                    continue
                raise LLMUnavailableError(f"{role} model call failed: {_sanitize(exc)}") from None
        if completion is None:  # pragma: no cover - defensive
            raise LLMUnavailableError(f"{role} model call failed: {_sanitize(last_exc)}")

        usage = TokenUsage.from_response(model, completion.usage)
        self.log.calls.append(
            {"role": role, "model": model, "prompt_version": prompt_version, **usage.as_dict()}
        )
        message = completion.choices[0].message
        if getattr(message, "refusal", None):
            raise LLMRefusalError(f"{role} model refused the request")
        if message.parsed is None:
            raise LLMRefusalError(f"{role} model returned no parseable structured output")
        return message.parsed, usage


_TRANSIENT_ERROR_NAMES = frozenset(
    {
        "APITimeoutError",
        "APIConnectionError",
        "RateLimitError",
        "InternalServerError",
        "APIStatusError",
    }
)


def _is_transient(exc: Exception | None) -> bool:
    """True for provider errors worth one retry (timeout / rate limit / 5xx),
    False for deterministic errors like auth/validation that a retry won't fix."""
    if exc is None:
        return False
    name = type(exc).__name__
    if name in _TRANSIENT_ERROR_NAMES:
        status = getattr(exc, "status_code", None)
        if name == "APIStatusError" and status is not None:
            return int(status) >= 500 or int(status) == 429
        return True
    return isinstance(exc, (TimeoutError, ConnectionError))


def _sanitize(exc: Exception | None) -> str:
    """Strip anything key-shaped from a provider error string."""
    import re

    text = str(exc) if exc is not None else "unknown error"
    text = re.sub(r"sk-[A-Za-z0-9_-]{8,}", "***", text)
    return text[:300]


def get_llm_client(settings: Settings | None = None) -> OpenAIQueryClient:
    """Factory used by the query service. Model is configurable; no eager call."""
    return OpenAIQueryClient(settings)
