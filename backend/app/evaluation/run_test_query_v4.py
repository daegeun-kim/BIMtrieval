"""Live acceptance runner that regenerates `specs/test_query_v4.md`.

Runs the SAME 42-case benchmark as v2/v3 (imported verbatim from
`run_test_query_suite`) against the experiment2_v4 pipeline and writes
`specs/test_query_v4.md` with the exact query, the exact final response, the
exact highlighted GlobalIds, and per-case metrics read back from the permanent
query trace. The queries and expected values are unchanged, so v2/v3/v4 form a
standardized benchmark even though the recorded models are only 1 and 2.

**This makes real, billed OpenAI calls** — two per answered question (three when
one corrective call fires). Never imported by the request path, never in pytest.

Usage from `backend/`:
    python -m app.evaluation.run_test_query_v4 --smoke
    python -m app.evaluation.run_test_query_v4
    python -m app.evaluation.run_test_query_v4 --only B9 C8
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass
from pathlib import Path

from app.api.schemas.request import HistoryTurn, SessionQueryRequest
from app.evaluation.run_test_query_suite import (
    REFERENCE_TABLE,
    SECTIONS,
    Case,
    _request_cost,
    _TpmPacer,
)
from app.query.service import QueryService
from app.query.trace_v2 import resolve_trace_path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_OUTPUT_V4 = _REPO_ROOT / "specs" / "test_query_v4.md"

#: Highlighted GlobalIds shown inline per case; the full list is in the trace.
_INLINE_ID_CAP = 12


@dataclass
class OutcomeV4:
    case: Case
    answer: str
    route: str
    highlighted_ids: list[str]
    highlighted_total: int
    part_facts: list[str]
    latency_ms: int
    llm_calls: int
    prompt_tokens: int
    completion_tokens: int
    db_statements: int
    used_fallback: bool
    used_correction: bool
    terminal_status: str
    cost_usd: float | None = None
    cost_note: str | None = None
    paced_model_tokens: int = 0
    error: str | None = None


def _last_trace_record(request_id: str) -> dict:
    """Read the terminal trace record for this request (§14)."""
    from app.config.settings import get_settings

    path = resolve_trace_path(get_settings().query_trace_path)
    if not path.exists():
        return {}
    try:
        for line in reversed(path.read_text(encoding="utf-8").strip().splitlines()):
            record = json.loads(line)
            if record.get("request_id") == request_id:
                return record
    except Exception:  # noqa: BLE001 - diagnostics are best-effort
        return {}
    return {}


def _part_facts(record: dict) -> list[str]:
    facts: list[str] = []
    for part in record.get("results", []):
        summary = f"{part.get('part_id')}: {part.get('result_kind')} → {part.get('status')}"
        for fact in part.get("facts", []):
            if fact.get("kind") in ("count", "scalar", "extremum", "sample"):
                value = fact.get("value", fact.get("count", fact.get("key")))
                summary += f" [{fact.get('fact_id')}={value}]"
        facts.append(summary)
    return facts


def _run_case(service: QueryService, case: Case, history: list[dict]) -> OutcomeV4:
    client = service._client()
    usage_start = len(client.log.calls)
    request = SessionQueryRequest(
        session_id=f"v4-{case.session or case.case_id}",
        question=case.query,
        active_source_model_id=case.model_id,
        history=[HistoryTurn(role=t["role"], content=t["content"]) for t in history],
    )
    started = time.perf_counter()
    try:
        response = service.handle_query(request)
    except Exception as exc:  # noqa: BLE001 - a crash is itself a recorded result
        elapsed = int((time.perf_counter() - started) * 1000)
        return OutcomeV4(
            case, f"(pipeline raised {type(exc).__name__}: {exc})", "error",
            [], 0, [], elapsed, 0, 0, 0, 0, False, False, "error", error=str(exc),
        )
    elapsed = int((time.perf_counter() - started) * 1000)

    calls = client.log.calls[usage_start:]
    cost_usd, cost_note = _request_cost(calls)
    paced_models = {service.settings.get_binder_model(), service.settings.get_correction_model()}
    paced_tokens = sum(
        int(c.get("total_tokens", 0) or 0) for c in calls if c.get("model") in paced_models
    )
    record = _last_trace_record(response.request_id)
    highlighted = list(response.viewer_actions.primary_global_ids or [])
    summary = response.result_summary
    return OutcomeV4(
        case=case,
        answer=response.answer,
        route=response.route.value,
        highlighted_ids=highlighted,
        highlighted_total=(summary.viewer_matches_total if summary and summary.viewer_matches_total else len(highlighted)),
        part_facts=_part_facts(record),
        latency_ms=elapsed,
        llm_calls=len(calls),
        prompt_tokens=sum(int(c.get("prompt_tokens", 0) or 0) for c in calls),
        completion_tokens=sum(int(c.get("completion_tokens", 0) or 0) for c in calls),
        db_statements=int(record.get("database_statements", 0) or 0),
        used_fallback=bool(record.get("used_fallback")),
        used_correction=bool(record.get("used_correction")),
        terminal_status=str(record.get("terminal_status", "")),
        cost_usd=cost_usd,
        cost_note=cost_note,
        paced_model_tokens=paced_tokens,
    )


def _format_case(o: OutcomeV4) -> str:
    case = o.case
    model = f"model {case.model_id}" if case.model_id else "no active model (catalog)"
    answer = "\n".join(f"> {line}" for line in (o.answer or "").splitlines())
    cost = f"${o.cost_usd:.6f}" if o.cost_usd is not None else f"cost unavailable ({o.cost_note})"

    if o.highlighted_ids:
        shown = o.highlighted_ids[:_INLINE_ID_CAP]
        ids = ", ".join(f"`{g}`" for g in shown)
        if o.highlighted_total > len(shown):
            ids += f" … (+{o.highlighted_total - len(shown)} more; full list in query_trace.jsonl)"
        highlighted = f"**Highlighted ({o.highlighted_total}):** {ids}"
    else:
        highlighted = "**Highlighted (0):** none"

    facts = "\n".join(f"- {f}" for f in o.part_facts) if o.part_facts else "- (no executed parts)"
    parts = [
        f"### {case.case_id} — {model}",
        "",
        f"**Query:** {case.query}",
        "",
        "**Answer (verbatim):**",
        "",
        answer or "> (empty)",
        "",
        "**Authoritative result:**",
        "",
        facts,
        "",
        highlighted,
        "",
        f"**Expected:** {case.expected}",
        "",
        "**Verdict:** _(to be assessed)_",
        "",
        (
            f"*route={o.route} · terminal={o.terminal_status} · llm_calls={o.llm_calls} · "
            f"tokens={o.prompt_tokens}p/{o.completion_tokens}c · cost={cost} · "
            f"db={o.db_statements} · {o.latency_ms} ms*"
        ),
    ]
    tags = []
    if o.used_correction:
        tags.append("CORRECTION USED")
    if o.used_fallback:
        tags.append("FALLBACK USED (model answer failed grounding; result is authoritative)")
    if tags:
        parts += ["", "*" + " · ".join(tags) + "*"]
    return "\n".join(parts)


def _header(run_date: str, service: QueryService) -> list[str]:
    from app.llm.pricing import PRICING_REGISTRY_VERSION, PRICING_SOURCE_URL, get_rates

    s = service.settings

    def _rate(role: str, model: str, effort: str) -> str:
        r = get_rates(model)
        if r is None:
            return f"- {role}: `{model}` ({effort}) — rate not on the recorded card"
        return (
            f"- {role}: `{model}` ({effort}) — ${r.uncached_input:g} / 1M input, "
            f"${r.cached_input:g} cached, ${r.cache_write:g} cache-write, ${r.output:g} / 1M output"
        )

    return [
        "# Query & Answer Log — v4 (experiment2_v4 / Task 26 pipeline)",
        "",
        "Regenerated from `test_query.md` against the experiment2_v4 pipeline: the v002",
        "semantic manifest and its compact binder projection, the phrase-level requirement",
        "ledger, always-parallel recall, the typed logical query algebra, ten-layer",
        "validation with per-part gates, the contract-driven relational compiler,",
        "operation-specific result variants, and the permanent query trace. Queries and",
        "expected values are identical to v1/v2/v3 (a standardized benchmark); answers,",
        "highlighted objects, and measurements are new. Compare against `test_query_v3.md`",
        "for the Task 25 baseline.",
        "",
        "The recorded benchmark covers models 1 and 2 only (as in v1-v3); the four-model",
        "structural repairs are documented separately in the deterministic section that",
        "follows this live log.",
        "",
        "Answers are recorded verbatim as returned to the user, with the exact highlighted",
        "GlobalIds (bounded inline; the full set is in `backend/app/evaluation/query_trace.jsonl`).",
        f"Captured live on {run_date} with:",
        "",
        _rate("binder", s.get_binder_model(), s.binder_reasoning_effort),
        _rate("correction", s.get_correction_model(), s.correction_reasoning_effort),
        _rate("answer", s.get_answer_model(), s.answer_reasoning_effort),
        "",
        "Metrics line: `llm_calls` is 2 for a normally-answered question and 3 when the one",
        "corrective call fires; `db` is the database statement count; `cost` is the",
        f"whole-request USD from the versioned pricing registry (`{PRICING_REGISTRY_VERSION}`,",
        f"rates from <{PRICING_SOURCE_URL}>). `CORRECTION USED` marks the one budget-gated",
        "corrective call; `FALLBACK USED` marks a deterministic answer returned because the",
        "model's own answer failed grounding validation (the structured result is still",
        "authoritative). Every request also appended one terminal record to the permanent",
        "`query_trace.jsonl`.",
        "",
        "---",
        "",
    ]


def _write_report(outcomes: list[OutcomeV4], run_date: str, service: QueryService) -> None:
    lines = _header(run_date, service)
    by_section: dict[str, list[OutcomeV4]] = {}
    for o in outcomes:
        for section in SECTIONS:
            if o.case in section.cases:
                by_section.setdefault(section.title, []).append(o)
    for section in SECTIONS:
        rows = by_section.get(section.title)
        if not rows:
            continue
        lines += [f"## {section.title}", "", section.preamble, "", "---", ""]
        for o in rows:
            lines.append(_format_case(o))
            lines += ["", "---", ""]
    priced = [o.cost_usd for o in outcomes if o.cost_usd is not None]
    total = f"${sum(priced):.6f}" if priced else "n/a"
    mean = f"${sum(priced) / len(priced):.6f}" if priced else "n/a"
    lines += [
        f"## Cost summary ({len(outcomes)} queries)",
        "",
        f"Total measured cost: **{total}** (mean {mean}/query, priced {len(priced)}/{len(outcomes)}).",
        "",
        "---",
        "",
        REFERENCE_TABLE,
    ]
    _OUTPUT_V4.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--smoke", action="store_true", help="run a 4-case smoke subset")
    parser.add_argument("--only", nargs="*", help="run only these case ids")
    parser.add_argument("--tpm-limit", type=int, default=200_000)
    args = parser.parse_args()

    cases = [c for s in SECTIONS for c in s.cases]
    if args.smoke:
        wanted = {"Q2", "Q6", "B20", "C11"}
        cases = [c for c in cases if c.case_id in wanted]
    elif args.only:
        wanted = set(args.only)
        cases = [c for c in cases if c.case_id in wanted]

    service = QueryService()
    outcomes: list[OutcomeV4] = []
    history_by_session: dict[str, list[dict]] = {}
    pacer = _TpmPacer(args.tpm_limit)

    for index, case in enumerate(cases, start=1):
        key = case.session or case.case_id
        history = history_by_session.setdefault(key, [])
        print(f"[{index}/{len(cases)}] {case.case_id}: {case.query[:60]}", flush=True)
        pacer.wait_if_needed()
        outcome = _run_case(service, case, history)
        pacer.record(outcome.paced_model_tokens)
        outcomes.append(outcome)
        history.append({"role": "user", "content": case.query})
        history.append({"role": "assistant", "content": (outcome.answer or "")[:2000]})
        cost = f"${outcome.cost_usd:.6f}" if outcome.cost_usd is not None else "unavailable"
        print(
            f"    -> {outcome.latency_ms} ms · {outcome.llm_calls} calls · "
            f"highlighted={outcome.highlighted_total} · cost={cost}"
            + (" · CORRECTION" if outcome.used_correction else "")
            + (" · FALLBACK" if outcome.used_fallback else ""),
            flush=True,
        )

    if not args.smoke and not args.only:
        _write_report(outcomes, time.strftime("%Y-%m-%d"), service)
        print(f"\nwrote {_OUTPUT_V4}")

    priced = [o.cost_usd for o in outcomes if o.cost_usd is not None]
    latencies = sorted(o.latency_ms for o in outcomes)
    median = latencies[len(latencies) // 2] if latencies else 0
    print(
        f"\ncases={len(outcomes)} median_latency={median} ms "
        f"cost=${sum(priced):.6f} (priced {len(priced)}/{len(outcomes)}) "
        f"corrections={sum(1 for o in outcomes if o.used_correction)} "
        f"fallbacks={sum(1 for o in outcomes if o.used_fallback)} "
        f"errors={sum(1 for o in outcomes if o.error)}"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
