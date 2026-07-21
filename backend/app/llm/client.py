"""OpenAI client for the two Task 24 LLM calls, using schema-enforced
structured outputs.

Two roles, independently configurable models (`planner_model` / `answer_model`,
kept separately configurable for later A/B evaluation per task24 §10.1):

- `bind_query()`             -> one `BindingPlan`. This is LLM call 1.
- `generate_grounded_answer()` -> one `GroundedAnswer`. This is LLM call 2.

There is no third method by design: no router, verifier, judge, repair,
reflection, correction, reranking, or replanning call exists (task24 §10.1).

Retry policy lives in exactly one place, `_structured_call`, and SDK-internal
retries are disabled so the two cannot multiply (task24 §10.4).

Secret handling: the API key is read from settings (runtime env / .env) only. It
is never logged, printed, hard-coded, or returned. If the key is absent, both
calls raise `LLMUnavailableError` with a sanitized message and no network call
is made. The `openai.OpenAI` object is built lazily, so importing this module
never touches the network.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from app.config.settings import Settings, get_settings
from app.llm.prompts import (
    BINDER_PROMPT_VERSION,
    GROUNDED_ANSWERER_PROMPT_VERSION,
    binder_prompt,
    grounded_answerer_prompt,
)
from app.llm.schemas import BindingPlan, GroundedAnswer
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


@dataclass
class BindingResult:
    plan: BindingPlan
    usage: TokenUsage


@dataclass
class GroundedAnswerResult:
    output: GroundedAnswer
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
                # Task 24 §10.4: "disable SDK-internal retries when application
                # retry behavior is active". The SDK defaults to 2 internal
                # retries; combined with this module's own bounded retry that is
                # up to 3x2 = 6 provider calls for one question, multiplying both
                # latency and spend invisibly. Retry policy lives in exactly one
                # place — `_structured_call` below.
                max_retries=0,
            )
        return self._client

    def bind_query(self, binder_context: dict[str, Any]) -> BindingResult:
        """Task 24 LLM call 1: bind the question to candidate slate IDs (§2).

        There is deliberately no repair variant of this call. §3.3 requires an
        invalid binding to produce a clarification or typed unavailable result,
        never a second planning request.
        """
        model = self.settings.get_planner_model()
        parsed, usage = self._structured_call(
            model=model,
            system=binder_prompt(),
            user_payload=binder_context,
            response_format=BindingPlan,
            prompt_version=BINDER_PROMPT_VERSION,
            role="binder",
        )
        return BindingResult(plan=parsed, usage=usage)

    def generate_grounded_answer(self, packet_payload: dict[str, Any]) -> GroundedAnswerResult:
        """Task 24 LLM call 2: express already-adjudicated answer parts (§8).

        Its output is validated deterministically against the packet; a failure
        produces a safe fallback, never a second answering call (§8.3).
        """
        model = self.settings.get_answer_model()
        parsed, usage = self._structured_call(
            model=model,
            system=grounded_answerer_prompt(),
            user_payload=packet_payload,
            response_format=GroundedAnswer,
            prompt_version=GROUNDED_ANSWERER_PROMPT_VERSION,
            role="grounded_answerer",
        )
        return GroundedAnswerResult(output=parsed, usage=usage)

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
    """True for provider errors worth ONE retry (Task 24 §10.4).

    Deliberately EXCLUDES a full request timeout. §10.4: "do not automatically
    retry a full LLM timeout." A reasoning model that exhausted the timeout is
    overwhelmingly likely to exhaust it again, so retrying doubles the user's
    wait before failing anyway — the worst possible outcome for a pipeline whose
    latency is already the main complaint.

    Schema, validation, refusal, and deterministic execution failures are also
    excluded: a retry cannot fix them.
    """
    if exc is None:
        return False
    name = type(exc).__name__
    if name == "APITimeoutError":
        return False
    if name in _TRANSIENT_ERROR_NAMES:
        status = getattr(exc, "status_code", None)
        if name == "APIStatusError" and status is not None:
            return int(status) >= 500 or int(status) == 429
        return True
    # A short connection blip is worth one retry; an exhausted timeout is not.
    return isinstance(exc, ConnectionError)


def _sanitize(exc: Exception | None) -> str:
    """Strip anything key-shaped from a provider error string."""
    import re

    text = str(exc) if exc is not None else "unknown error"
    text = re.sub(r"sk-[A-Za-z0-9_-]{8,}", "***", text)
    return text[:300]


def get_llm_client(settings: Settings | None = None) -> OpenAIQueryClient:
    """Factory used by the query service. Model is configurable; no eager call."""
    return OpenAIQueryClient(settings)
