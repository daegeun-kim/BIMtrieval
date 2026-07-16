"""Per-question OpenAI token-usage terminal output (tasks/task15.md §1).

Offline: fake clients only — the tests prove the aggregation/snapshot wiring,
never a live call. The values summed are the ones the client log records from
API-reported usage (app/llm/client.py appends them post-completion).
"""

from __future__ import annotations

import logging
import re

import pytest

from app.api.schemas.request import SessionQueryRequest
from app.llm.client import LLMCallLog
from app.query.service import QueryService, _emit_question_usage
from app.shared.types import ResponseStatus


@pytest.fixture()
def logs(caplog):
    caplog.set_level(logging.INFO, logger="bim_rag_backend")
    return caplog


def _call(role: str, prompt: int, completion: int) -> dict:
    return {
        "role": role,
        "model": "gpt-5-nano",
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": prompt + completion,
    }


class _FakeClient:
    """Mimics OpenAIQueryClient's log surface; `plan_query` drives the calls."""

    def __init__(self, per_question_calls: list[list[dict]]):
        self.log = LLMCallLog()
        self._batches = list(per_question_calls)

    def plan_query(self, _context):
        raise AssertionError("not reached in these tests")


# ---------------------------------------------------------------------------
# Aggregation unit behavior
# ---------------------------------------------------------------------------


def test_usage_block_sums_planner_and_answerer(logs):
    _emit_question_usage([_call("planner", 6200, 900), _call("answerer", 3100, 400)])

    out = logs.text
    assert "[OpenAI usage]" in out
    assert "prompt_tokens: 9300" in out
    assert "completion_tokens: 1300" in out
    assert "total_tokens: 10600" in out


def test_usage_block_includes_a_repair_call_when_one_ran(logs):
    _emit_question_usage(
        [_call("planner", 6000, 800), _call("planner", 6100, 850), _call("answerer", 3000, 300)]
    )
    assert "prompt_tokens: 15100" in logs.text
    assert "completion_tokens: 1950" in logs.text
    assert "total_tokens: 17050" in logs.text


def test_no_usage_block_when_no_call_was_made(logs):
    """A zero-OpenAI question must not print a misleading zero block."""
    _emit_question_usage([])
    assert "[OpenAI usage]" not in logs.text


def test_usage_prints_only_the_three_aggregates(logs):
    _emit_question_usage([_call("planner", 10, 5)])
    block = logs.text[logs.text.index("[OpenAI usage]") :]
    # exactly the three numbers — no per-call breakdown, model names, or cost
    assert "prompt_tokens: 10" in block
    assert "completion_tokens: 5" in block
    assert "total_tokens: 15" in block
    assert "gpt-5-nano" not in block
    assert "cost" not in block.lower()
    assert "cumulative" not in block.lower()


def test_usage_block_prints_regardless_of_trace_mode(logs, monkeypatch):
    from app.config.settings import get_settings

    monkeypatch.delenv("BIM_RAG_TRACE", raising=False)
    get_settings.cache_clear()
    _emit_question_usage([_call("planner", 1, 1)])
    assert "[OpenAI usage]" in logs.text


# ---------------------------------------------------------------------------
# Service wiring: per-question snapshot, not cumulative
# ---------------------------------------------------------------------------


def _run_question(svc: QueryService, client: _FakeClient, calls: list[dict], *, fail=False):
    """Drive one question through handle_query with the LLM work stubbed to
    append `calls` to the client log (mimicking client.py's post-completion
    appends), so the snapshot/finally wiring is exercised end to end."""

    def _fake_answer(request, request_id, scope, c, state, t0):
        for entry in calls:
            c.log.calls.append(entry)
        if fail:
            raise RuntimeError("provider blew up after the planner completed")
        from app.query.service import _error_envelope

        return _error_envelope(request, "stub answer", request_id=request_id, scope=scope)

    svc._answer_question = _fake_answer  # instance-level stub
    req = SessionQueryRequest(question="how many doors?", session_id="s-usage")
    if fail:
        with pytest.raises(RuntimeError):
            svc.handle_query(req)
    else:
        svc.handle_query(req)


def _usage_blocks(text: str) -> list[tuple[int, int, int]]:
    blocks = []
    for m in re.finditer(
        r"prompt_tokens: (\d+)\s+completion_tokens: (\d+)\s+total_tokens: (\d+)", text
    ):
        blocks.append(tuple(int(g) for g in m.groups()))
    return blocks


def test_each_question_prints_its_own_sum_with_no_cumulative_counter(logs):
    client = _FakeClient([])
    svc = QueryService(llm_client=client)

    _run_question(svc, client, [_call("planner", 100, 10), _call("answerer", 50, 5)])
    _run_question(svc, client, [_call("planner", 200, 20)])

    blocks = _usage_blocks(logs.text)
    assert blocks == [(150, 15, 165), (200, 20, 220)]  # second block is NOT 350/35/385


def test_partial_failure_prints_only_the_usage_actually_reported(logs):
    """Planner completed and reported usage; the answer call then failed. The
    block must show the planner's real usage only — truthful, not zero."""
    client = _FakeClient([])
    svc = QueryService(llm_client=client)
    _run_question(svc, client, [_call("planner", 6200, 900)], fail=True)

    assert _usage_blocks(logs.text) == [(6200, 900, 7100)]


def test_reset_prints_no_usage_block(logs):
    class _Exploding:
        def plan_query(self, _c):  # pragma: no cover
            raise AssertionError("no OpenAI on reset")

    svc = QueryService(llm_client=_Exploding())
    resp = svc.handle_query(SessionQueryRequest(question="clear", session_id="s1", reset=True))
    assert resp.status is ResponseStatus.SUCCESS
    assert "[OpenAI usage]" not in logs.text


def test_client_without_a_log_surface_is_tolerated(logs):
    """Fake clients in older tests have no `.log`; the wiring must not crash."""

    class _NoLog:
        def plan_query(self, _c):  # pragma: no cover
            raise AssertionError("not reached")

    svc = QueryService(llm_client=_NoLog())

    def _fake_answer(request, request_id, scope, c, state, t0):
        from app.query.service import _error_envelope

        return _error_envelope(request, "stub", request_id=request_id, scope=scope)

    svc._answer_question = _fake_answer
    svc.handle_query(SessionQueryRequest(question="q", session_id="s2"))
    assert "[OpenAI usage]" not in logs.text
