"""Task 29 development-set runner (visible).

Runs the 15 development messages of `logs/debug_queries_v5.md` in their frozen
sessions and model contexts, and writes the COMPLETE detailed result of each —
answer, authoritative result parts, viewer identities, stage record, resolved
intent, preservation verdicts, calls, tokens, cost, latency — to a JSON file the
debugging process may inspect freely.

**This makes real, billed OpenAI calls.** Never imported by the request path,
never in pytest.

Usage from `backend/`:
    python -m app.evaluation.run_v5_debug --tag iter000
    python -m app.evaluation.run_v5_debug --tag iter001 --only D05 D06
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from app.api.schemas.request import HistoryTurn, SessionQueryRequest
from app.evaluation.run_test_query_suite import _request_cost, _TpmPacer
from app.evaluation.v5_cases import DEV_CASES, DevCase
from app.query.service import QueryService
from app.query.trace_v2 import resolve_trace_path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_LOGS = _REPO_ROOT / "logs"


def _last_trace_record(trace_path: Path) -> dict[str, Any]:
    if not trace_path.exists():
        return {}
    last = ""
    with trace_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                last = line
    try:
        return json.loads(last) if last else {}
    except json.JSONDecodeError:
        return {}


def _run_case(
    service: QueryService,
    case: DevCase,
    history: list[dict[str, str]],
    trace_path: Path,
) -> dict[str, Any]:
    client = service._client()
    usage_start = len(client.log.calls)
    request = SessionQueryRequest(
        session_id=f"v5dev-{case.session}",
        question=case.query,
        active_source_model_id=case.model_id,
        history=[HistoryTurn(role=t["role"], content=t["content"]) for t in history],
    )
    started = time.perf_counter()
    error = None
    try:
        response = service.handle_query(request)
    except Exception as exc:  # noqa: BLE001 - a crash is itself a recorded result
        elapsed = int((time.perf_counter() - started) * 1000)
        return {
            "case_id": case.case_id,
            "model_id": case.model_id,
            "query": case.query,
            "expected": case.expected,
            "answer": f"(pipeline raised {type(exc).__name__}: {exc})",
            "error": str(exc)[:500],
            "latency_ms": elapsed,
            "llm_calls": 0,
            "cost_usd": None,
        }
    elapsed = int((time.perf_counter() - started) * 1000)

    calls = client.log.calls[usage_start:]
    cost_usd, cost_note = _request_cost(calls)
    trace = _last_trace_record(trace_path)
    summary = response.result_summary

    return {
        "case_id": case.case_id,
        "session": case.session,
        "model_id": case.model_id,
        "intended_path": case.intended_path,
        "query": case.query,
        "expected": case.expected,
        "answer": response.answer,
        "route": response.route.value,
        "terminal": {"stage": trace.get("terminal_stage"), "status": trace.get("terminal_status")},
        # --- authoritative execution evidence -----------------------------
        "results": trace.get("results", []),
        "status_summary": trace.get("status_summary", {}),
        # --- v5 stage evidence --------------------------------------------
        "resolved_intent": trace.get("resolved_intent"),
        "semantic_preservation": trace.get("semantic_preservation"),
        "clarification": trace.get("clarification"),
        "ledger": trace.get("ledger"),
        "recommendations": trace.get("recommendations", [])[:24],
        "grounding_output": trace.get("grounding_output"),
        "correction_output": trace.get("correction_output"),
        "validation": trace.get("validation"),
        "stages": trace.get("stages", []),
        # --- delivery ------------------------------------------------------
        "viewer_parts": trace.get("viewer_parts", {}),
        "viewer_global_ids": trace.get("delivery", {}).get("viewer_global_ids", [])[:40],
        "viewer_total": summary.viewer_matches_total if summary else None,
        "class_counts": dict(summary.class_counts) if summary else {},
        "warnings": trace.get("warnings", []),
        # --- accounting -----------------------------------------------------
        "latency_ms": elapsed,
        "llm_calls": len(calls),
        "prompt_tokens": sum(int(c.get("prompt_tokens", 0) or 0) for c in calls),
        "completion_tokens": sum(int(c.get("completion_tokens", 0) or 0) for c in calls),
        "db_statements": int(trace.get("database_statements", 0) or 0),
        "used_correction": bool(trace.get("used_correction")),
        "used_fallback": bool(trace.get("used_fallback")),
        "used_deterministic_intent": bool(trace.get("used_deterministic_intent")),
        "cost_usd": cost_usd,
        "cost_note": cost_note,
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
        "error": error,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True, help="iteration tag, e.g. iter000")
    parser.add_argument("--only", nargs="*", default=None, help="case ids to run")
    parser.add_argument("--tpm-limit", type=int, default=200_000)
    args = parser.parse_args()

    service = QueryService()
    trace_path = resolve_trace_path(service.settings.query_trace_path)
    pacer = _TpmPacer(args.tpm_limit)

    wanted = set(args.only) if args.only else None
    # A follow-up needs its session predecessor to have run in the same process.
    if wanted:
        for case in DEV_CASES:
            if case.case_id in wanted:
                wanted.update(case.follows)

    histories: dict[str, list[dict[str, str]]] = {}
    records: list[dict[str, Any]] = []

    for case in DEV_CASES:
        history = histories.setdefault(case.session, [])
        if wanted is not None and case.case_id not in wanted:
            continue
        pacer.wait_if_needed()
        print(f"  {case.case_id} (model {case.model_id}, {case.session}) …", flush=True)
        record = _run_case(service, case, history, trace_path)
        pacer.record(record.get("paced_model_tokens", 0))
        records.append(record)
        history.append({"role": "user", "content": case.query})
        history.append({"role": "assistant", "content": record["answer"]})
        cost = record.get("cost_usd")
        print(
            f"    {record.get('llm_calls')} calls · "
            f"{record.get('latency_ms')} ms · "
            f"{('$%.6f' % cost) if cost is not None else 'cost n/a'}",
            flush=True,
        )

    out = _LOGS / f"_dev_results_{args.tag}.json"
    out.write_text(
        json.dumps({"tag": args.tag, "cases": records}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    total = sum(r["cost_usd"] for r in records if r.get("cost_usd") is not None)
    print(f"\nwrote {out}  ({len(records)} cases, ${total:.6f})")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
