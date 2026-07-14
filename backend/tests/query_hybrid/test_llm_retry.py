"""Bounded retry on transient provider errors, no retry on deterministic ones
(spec_v005 §17). Offline — no network, no real OpenAI client."""

from __future__ import annotations

import pytest
from config.settings import Settings
from llm.client import LLMUnavailableError, OpenAIQueryClient, _is_transient
from llm.schemas import QueryPlan
from shared.types import QueryRoute, QueryScope


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
    """Name matches the transient-error allowlist used by _is_transient."""


class _FakeParse:
    def __init__(self, fail_times, parsed):
        self.calls = 0
        self._fail_times = fail_times
        self._parsed = parsed

    def __call__(self, **kwargs):
        self.calls += 1
        if self.calls <= self._fail_times:
            raise APITimeoutError("timeout")
        return _Completion(self._parsed)


class _FakeOpenAI:
    def __init__(self, parse):
        self.chat = type("C", (), {"completions": type("D", (), {"parse": parse})()})()


def _plan():
    return QueryPlan(scope=QueryScope.ACTIVE_MODEL, route=QueryRoute.SQL, source_model_id=1)


def _client(parse):
    c = OpenAIQueryClient(Settings(openai_max_retries=1, openai_retry_backoff_s=0.0))
    c._client = _FakeOpenAI(parse)  # bypass real construction / key check
    return c


def test_is_transient_classifies_by_name():
    assert _is_transient(APITimeoutError("x")) is True
    assert _is_transient(ValueError("bad")) is False
    assert _is_transient(None) is False


def test_transient_error_is_retried_once_then_succeeds():
    parse = _FakeParse(fail_times=1, parsed=_plan())
    client = _client(parse)
    result = client.plan_query({"question": "q"})
    assert result.plan.route is QueryRoute.SQL
    assert parse.calls == 2  # one failure + one success


def test_transient_error_exhausts_retries_and_raises():
    parse = _FakeParse(fail_times=5, parsed=_plan())
    client = _client(parse)
    with pytest.raises(LLMUnavailableError):
        client.plan_query({"question": "q"})
    assert parse.calls == 2  # bounded: initial + 1 retry only


def test_deterministic_error_is_not_retried():
    class _BadParse:
        def __init__(self):
            self.calls = 0

        def __call__(self, **kwargs):
            self.calls += 1
            raise ValueError("invalid request")

    parse = _BadParse()
    client = _client(parse)
    with pytest.raises(LLMUnavailableError):
        client.plan_query({"question": "q"})
    assert parse.calls == 1  # not retried
