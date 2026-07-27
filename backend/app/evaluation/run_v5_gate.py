"""Task 29 compact blind regression gate.

Runs the eight opaque original cases frozen in `logs/regression_gate_v5.md`,
grades them with a fixed deterministic rubric, and prints **only** the aggregate

    PASS: <n>
    PARTIAL: <n>
    FAIL: <n>

Per-case answers, verdicts, traces, failure reasons and viewer sets are written
to `logs/_gate_detail_<tag>.json` for reproducibility and are deliberately NOT
printed: the debugging process must not see them, so gate outcomes cannot direct
implementation (task29 §Blind evaluation boundary).

Gate requests write their trace records to a SEPARATE per-run trace file rather
than the permanent development trace, which is how they are tagged and kept out
of development diagnosis.

**This makes real, billed OpenAI calls.** Never imported by the request path,
never in pytest.

Usage from `backend/`:
    python -m app.evaluation.run_v5_gate --tag iter000
"""

from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path
from typing import Any

from app.api.schemas.request import HistoryTurn, SessionQueryRequest
from app.config.settings import Settings
from app.evaluation.run_test_query_suite import _request_cost, _TpmPacer
from app.evaluation.v5_cases import gate_cases
from app.query.service import QueryService

_REPO_ROOT = Path(__file__).resolve().parents[3]
_LOGS = _REPO_ROOT / "logs"

PASS, PARTIAL, FAIL = "PASS", "PARTIAL", "FAIL"

_NUMBER_RE = re.compile(r"(?<![\w.])(\d{1,3}(?:[, ]\d{3})+|\d+)(?![\w.])")


def _numbers(text: str) -> set[int]:
    out: set[int] = set()
    for match in _NUMBER_RE.finditer(text or ""):
        try:
            out.add(int(match.group(1).replace(",", "").replace(" ", "")))
        except ValueError:
            continue
    return out


def _result_numbers(record: dict[str, Any]) -> set[int]:
    out: set[int] = set()

    def walk(value: Any) -> None:
        if isinstance(value, bool):
            return
        if isinstance(value, int):
            out.add(value)
        elif isinstance(value, float) and value.is_integer():
            out.add(int(value))
        elif isinstance(value, dict):
            for inner in value.values():
                walk(inner)
        elif isinstance(value, list):
            for inner in value:
                walk(inner)

    walk(record.get("results", []))
    return out


def _answered(record: dict[str, Any]) -> bool:
    return bool(record.get("results"))


def _refusal(record: dict[str, Any]) -> bool:
    status = (record.get("terminal") or {}).get("status", "")
    return status in ("unavailable", "clarification") and not _answered(record)


def _honest_absence(record: dict[str, Any]) -> bool:
    """A truthful "this model does not record that", not a question back."""
    status = (record.get("terminal") or {}).get("status", "")
    answer = (record.get("answer") or "").casefold()
    asks = answer.rstrip().endswith("?")
    return status in ("unavailable", "success") and not asks


# ---------------------------------------------------------------------------
# Frozen per-case rubric. Immutable for the duration of Task 29.
# ---------------------------------------------------------------------------


def _grade_Q8(r):
    return PASS if 450 in _result_numbers(r) | _numbers(r["answer"]) else FAIL


def _grade_B4(r):
    seen = _numbers(r["answer"]) | _result_numbers(r)
    hits = len({81, 6, 59} & seen)
    if hits >= 2:
        return PASS
    if _answered(r) and not _refusal(r):
        return PARTIAL
    return FAIL


def _grade_B7(r):
    seen = _numbers(r["answer"]) | _result_numbers(r)
    if {405, 42} <= seen:
        return PASS
    if 405 in seen or 42 in seen:
        return PARTIAL
    return FAIL


def _grade_B12(r):
    # The pipeline does not execute this connectivity meaning; an honest
    # statement is the correct outcome, a fabricated set is not.
    return PASS if _honest_absence(r) and not _answered(r) else FAIL


def _grade_B19(r):
    # No area quantity exists on spaces, so no room can be named largest.
    return PASS if _honest_absence(r) else FAIL


def _grade_C2(r):
    return PASS if 54 in _result_numbers(r) | _numbers(r["answer"]) else FAIL


def _grade_C4(r):
    if r.get("viewer_total") == 1 or len(r.get("viewer_global_ids") or []) == 1:
        return PASS
    if _answered(r):
        return PARTIAL
    return FAIL


def _grade_C8(r):
    seen = _numbers(r["answer"]) | _result_numbers(r)
    core = {551, 428, 81} & seen
    if len(core) == 3 and 142 in seen:
        return PASS
    if len(core) >= 2:
        return PARTIAL
    return FAIL


_RUBRIC = {
    "Q8": _grade_Q8,
    "B4": _grade_B4,
    "B7": _grade_B7,
    "B12": _grade_B12,
    "B19": _grade_B19,
    "C2-followup": _grade_C2,
    "C4": _grade_C4,
    "C8": _grade_C8,
}


def _run(service, case, history, trace_path):
    client = service._client()
    usage_start = len(client.log.calls)
    request = SessionQueryRequest(
        session_id=f"v5gate-{case.session or case.case_id}",
        question=case.query,
        active_source_model_id=case.model_id,
        history=[HistoryTurn(role=t["role"], content=t["content"]) for t in history],
    )
    started = time.perf_counter()
    try:
        response = service.handle_query(request)
        answer = response.answer
        summary = response.result_summary
        viewer_ids = list(response.viewer_actions.primary_global_ids or [])
        viewer_total = summary.viewer_matches_total if summary else None
    except Exception as exc:  # noqa: BLE001
        answer = f"(pipeline raised {type(exc).__name__}: {exc})"
        viewer_ids, viewer_total = [], None
    elapsed = int((time.perf_counter() - started) * 1000)

    calls = client.log.calls[usage_start:]
    cost_usd, _note = _request_cost(calls)
    trace = {}
    if trace_path.exists():
        last = ""
        with trace_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    last = line
        try:
            trace = json.loads(last) if last else {}
        except json.JSONDecodeError:
            trace = {}

    return {
        "case_id": case.case_id,
        "answer": answer,
        "results": trace.get("results", []),
        "terminal": {"stage": trace.get("terminal_stage"), "status": trace.get("terminal_status")},
        "viewer_global_ids": viewer_ids[:40],
        "viewer_total": viewer_total,
        "latency_ms": elapsed,
        "llm_calls": len(calls),
        "cost_usd": cost_usd,
        "paced_model_tokens": sum(
            int(c.get("total_tokens", 0) or 0)
            for c in calls
            if c.get("model")
            in {
                service.settings.get_binder_model(),
                service.settings.get_correction_model(),
                service.settings.get_intent_model(),
            }
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--tpm-limit", type=int, default=200_000)
    args = parser.parse_args()

    # Gate traffic writes to its own trace file: that is the tag which keeps
    # these records out of development diagnosis.
    gate_trace = _LOGS / f"_gate_trace_{args.tag}.jsonl"
    settings = Settings(query_trace_path=str(gate_trace))
    service = QueryService(settings=settings)
    pacer = _TpmPacer(args.tpm_limit)

    scored, prerequisites = gate_cases()
    records: list[dict[str, Any]] = []

    for case in scored:
        history: list[dict[str, str]] = []
        for prior in prerequisites.get(case.case_id, []):
            pacer.wait_if_needed()
            setup = _run(service, prior, history, gate_trace)
            pacer.record(setup.get("paced_model_tokens", 0))
            history.append({"role": "user", "content": prior.query})
            history.append({"role": "assistant", "content": setup["answer"]})
        pacer.wait_if_needed()
        record = _run(service, case, history, gate_trace)
        pacer.record(record.get("paced_model_tokens", 0))
        record["verdict"] = _RUBRIC[case.case_id](record)
        records.append(record)

    tally = {PASS: 0, PARTIAL: 0, FAIL: 0}
    for record in records:
        tally[record["verdict"]] += 1

    detail = _LOGS / f"_gate_detail_{args.tag}.json"
    detail.write_text(
        json.dumps({"tag": args.tag, "cases": records}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )

    cost = sum(r["cost_usd"] for r in records if r.get("cost_usd") is not None)
    calls = sum(r["llm_calls"] for r in records)
    latency = sum(r["latency_ms"] for r in records)

    # The ONLY thing the debugging loop may see.
    print(f"PASS: {tally[PASS]}")
    print(f"PARTIAL: {tally[PARTIAL]}")
    print(f"FAIL: {tally[FAIL]}")
    print(f"(aggregate accounting — llm_calls: {calls}, cost_usd: {cost:.6f}, ms: {latency})")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
