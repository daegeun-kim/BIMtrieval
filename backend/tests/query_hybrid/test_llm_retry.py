"""Retry behaviour under the Task 24 §10.4 contract.

Offline — no network, no real OpenAI client, no key.

§10.4 changed this deliberately from the previous behaviour:

- SDK-internal retries are disabled so they cannot multiply with ours;
- a full request TIMEOUT is no longer retried;
- at most ONE bounded application retry, for a short transient connection,
  rate-limit, or provider 5xx failure;
- schema/validation/refusal/deterministic failures are never retried.
"""

from __future__ import annotations

import pytest

from app.config.settings import Settings
from app.llm.client import LLMUnavailableError, OpenAIQueryClient, _is_transient
from app.llm.schemas import BindingPlan


class _Msg:
    def __init__(self, parsed):
        self.parsed = parsed
        self.refusal = None


class _Choice:
    def __init__(self, parsed):
        self.message = _Msg(parsed)


class _Usage:
    prompt_tokens = 10
    completion_tokens = 20
    total_tokens = 30


class _Completion:
    def __init__(self, parsed):
        self.choices = [_Choice(parsed)]
        self.usage = _Usage()


class APITimeoutError(Exception):
    """Name matches the SDK's timeout class, which is what the classifier reads."""


class RateLimitError(Exception):
    """Name matches the SDK's rate-limit class."""


class InternalServerError(Exception):
    """Name matches the SDK's 5xx class."""


class _FakeParse:
    def __init__(self, fail_times, parsed, error=RateLimitError):
        self.calls = 0
        self._fail_times = fail_times
        self._parsed = parsed
        self._error = error

    def __call__(self, **kwargs):
        self.calls += 1
        if self.calls <= self._fail_times:
            raise self._error("provider unavailable")
        return _Completion(self._parsed)


class _FakeOpenAI:
    def __init__(self, parse):
        self.chat = type("C", (), {"completions": type("D", (), {"parse": parse})()})()


def _client(parse):
    c = OpenAIQueryClient(Settings(openai_max_retries=1, openai_retry_backoff_s=0.0))
    c._client = _FakeOpenAI(parse)  # bypass real construction / key check
    return c


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("error", [RateLimitError("x"), InternalServerError("x")])
def test_short_transient_provider_errors_are_retryable(error):
    assert _is_transient(error) is True


def test_a_full_timeout_is_NOT_retried():
    """§10.4: "do not automatically retry a full LLM timeout".

    A reasoning model that exhausted the timeout will almost certainly exhaust
    it again, so retrying only doubles the user's wait before failing anyway —
    the worst outcome for a pipeline whose latency is the main complaint.
    """
    assert _is_transient(APITimeoutError("x")) is False


@pytest.mark.parametrize("error", [ValueError("bad"), TypeError("bad"), None])
def test_deterministic_errors_are_not_retryable(error):
    assert _is_transient(error) is False


# ---------------------------------------------------------------------------
# Bounded retry
# ---------------------------------------------------------------------------


def test_one_transient_failure_is_retried_once_then_succeeds():
    parse = _FakeParse(fail_times=1, parsed=BindingPlan())
    client = _client(parse)
    result = client.bind_query({"question": "q"})
    assert isinstance(result.plan, BindingPlan)
    assert parse.calls == 2  # one failure + one success


def test_retry_is_bounded_to_a_single_attempt():
    parse = _FakeParse(fail_times=5, parsed=BindingPlan())
    client = _client(parse)
    with pytest.raises(LLMUnavailableError):
        client.bind_query({"question": "q"})
    assert parse.calls == 2  # initial + exactly one retry


def test_a_timeout_costs_exactly_one_call():
    """The whole point of excluding timeouts: no doubled wait."""
    parse = _FakeParse(fail_times=5, parsed=BindingPlan(), error=APITimeoutError)
    client = _client(parse)
    with pytest.raises(LLMUnavailableError):
        client.bind_query({"question": "q"})
    assert parse.calls == 1


def test_a_deterministic_error_costs_exactly_one_call():
    parse = _FakeParse(fail_times=5, parsed=BindingPlan(), error=ValueError)
    client = _client(parse)
    with pytest.raises(LLMUnavailableError):
        client.bind_query({"question": "q"})
    assert parse.calls == 1


def test_retry_policy_applies_to_the_answer_call_too():
    parse = _FakeParse(fail_times=1, parsed=_grounded_answer())
    client = _client(parse)
    result = client.generate_grounded_answer({"question": "q"})
    assert result.output.answer
    assert parse.calls == 2


def _grounded_answer():
    from app.llm.schemas import GroundedAnswer

    return GroundedAnswer(answer="42 doors.")


# ---------------------------------------------------------------------------
# SDK retries must not multiply with ours (§10.4)
# ---------------------------------------------------------------------------


def test_sdk_internal_retries_are_disabled(monkeypatch):
    """Otherwise one question could cost 3x2 = 6 provider calls invisibly."""
    captured: dict = {}

    class _FakeSDK:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            self.chat = type(
                "C", (), {"completions": type("D", (), {"parse": lambda **kw: None})()}
            )()

    import app.llm.client as client_module

    monkeypatch.setattr(client_module, "OpenAI", _FakeSDK, raising=False)
    monkeypatch.setitem(__import__("sys").modules, "openai", type("m", (), {"OpenAI": _FakeSDK}))

    from pydantic import SecretStr

    client = OpenAIQueryClient(Settings(openai_api_key=SecretStr("sk-test")))
    client._get_client()
    assert captured.get("max_retries") == 0
