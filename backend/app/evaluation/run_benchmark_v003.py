"""End-to-end benchmark runner for the query prototype (tasks/task08).

Runs the versioned ground-truth cases in `benchmark_v003_e2e_cases.jsonl`
through the REAL `QueryService` pipeline (planner -> validate/repair -> execute
-> grounded answer), correlates each response with the safe JSONL query log by
`request_id` to recover token usage and per-stage latency, scores each case
against its expected scope/route/operation/exact-value/viewer-id, and writes a
machine-readable results JSON plus a printed summary.

Read-only: it never modifies BIM/vector data. It also snapshots
`ifc_entities` / `rag_documents` row counts before and after the run to prove
the ingested corpus and stored vectors are unchanged (task08 required
execution item 6).

Usage (from backend/, Poetry env):
    poetry run python -m app.evaluation.run_benchmark_v003
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

# Allow running as a plain script: ensure the backend/ project root is importable
# so the `app.*` package resolves. Preferred:
#   poetry run python -m app.evaluation.run_benchmark_v003
_BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from sqlalchemy import text  # noqa: E402

from app.api.schemas.request import HistoryTurn, SessionQueryRequest  # noqa: E402
from app.config.settings import get_settings  # noqa: E402
from app.db.session import session_scope  # noqa: E402
from app.llm.client import get_llm_client  # noqa: E402
from app.llm.context import build_planner_context  # noqa: E402
from app.query.service import QueryService  # noqa: E402
from app.query.session import get_session_store  # noqa: E402

CASES_PATH = _BACKEND_ROOT / "app" / "evaluation" / "benchmark_v003_e2e_cases.jsonl"
RESULTS_PATH = Path("logs/benchmark_v003_results.json")


def _load_cases() -> list[dict]:
    cases = []
    for line in CASES_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            cases.append(json.loads(line))
    return cases


def _corpus_counts() -> dict:
    with session_scope() as s:
        return {
            "ifc_entities": s.execute(text("SELECT count(*) FROM ifc_entities")).scalar_one(),
            "ifc_relationships": s.execute(
                text("SELECT count(*) FROM ifc_relationships")
            ).scalar_one(),
            "rag_documents": s.execute(text("SELECT count(*) FROM rag_documents")).scalar_one(),
            "valid_embeddings": s.execute(
                text("SELECT count(*) FROM rag_documents WHERE embedding IS NOT NULL")
            ).scalar_one(),
        }


def _log_index() -> dict[str, dict]:
    path = Path(get_settings().query_log_path)
    index: dict[str, dict] = {}
    if not path.exists():
        return index
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if rec.get("event") == "query" and rec.get("request_id"):
            index[rec["request_id"]] = rec  # last write wins
    return index


def _plan_operation(rec: dict) -> str | None:
    plan = rec.get("validated_plan") or {}
    for key in ("sql_plan", "catalog_plan"):
        sub = plan.get(key)
        if sub and sub.get("operation"):
            return sub["operation"]
    return None


def _build_request(case: dict, session_id: str) -> SessionQueryRequest:
    return SessionQueryRequest(
        question=case["question"],
        session_id=session_id,
        active_source_model_id=case.get("active_source_model_id"),
        selected_entity_ids=case.get("selected_entity_ids", []),
        history=[HistoryTurn(**h) for h in case.get("history", [])],
        reset=case.get("reset", False),
        confirm_model_id=case.get("confirm_model_id"),
    )


def _score_case(case: dict, resp, rec: dict | None) -> dict:
    result: dict = {"id": case["id"], "category": case["category"], "checks": {}, "issues": []}
    checks = result["checks"]

    route = resp.route.value
    result["route"] = route
    result["scope"] = resp.scope.value
    result["answer_basis"] = resp.answer_basis.value
    result["answer_preview"] = resp.answer[:200]

    expected_routes = case.get("expected_routes")
    if expected_routes:
        checks["route_ok"] = route in expected_routes
        if not checks["route_ok"]:
            result["issues"].append(f"route {route} not in {expected_routes}")

    if case.get("scope"):
        checks["scope_ok"] = resp.scope.value == case["scope"]

    operation = _plan_operation(rec) if rec else None
    result["operation"] = operation
    if case.get("expected_operations") and operation is not None:
        checks["operation_ok"] = operation in case["expected_operations"]
        if not checks["operation_ok"]:
            result["issues"].append(f"operation {operation} not in {case['expected_operations']}")

    if "exact_value" in case:
        ev = case["exact_value"]
        sql_match = resp.evidence_summary.sql_match_count
        in_answer = str(ev) in resp.answer
        checks["exact_ok"] = (sql_match == ev) or in_answer
        result["sql_match_count"] = sql_match
        if not checks["exact_ok"]:
            result["issues"].append(
                f"exact value {ev} not matched (sql_match={sql_match}, in_answer={in_answer})"
            )

    if case.get("expected_model_action"):
        checks["model_action_ok"] = (
            resp.viewer_actions.model_action.value == case["expected_model_action"]
        )
        if not checks["model_action_ok"]:
            result["issues"].append(
                f"model_action {resp.viewer_actions.model_action.value} "
                f"!= {case['expected_model_action']}"
            )

    if case.get("expected_active_model") is not None:
        checks["active_model_ok"] = resp.active_source_model_id == case["expected_active_model"]

    if case.get("expected_viewer_global_ids"):
        present = set(resp.viewer_actions.primary_global_ids) | set(
            resp.viewer_actions.context_global_ids
        )
        missing = [g for g in case["expected_viewer_global_ids"] if g not in present]
        checks["viewer_ids_ok"] = not missing
        if missing:
            result["issues"].append(f"missing viewer global_ids: {missing}")

    if case.get("relevant_ifc_classes"):
        prim = resp.primary_entities
        rel = set(case["relevant_ifc_classes"])
        if prim:
            n_rel = sum(1 for e in prim if e.ifc_class in rel)
            result["retrieval_relevant_fraction"] = round(n_rel / len(prim), 3)
            checks["retrieval_ok"] = (n_rel / len(prim)) >= 0.6
        else:
            result["retrieval_relevant_fraction"] = None

    if case.get("clarification_ok") and route == "clarify":
        checks["clarify_ok"] = True

    # grounding heuristic for exact cases: a wrong number must not dominate
    if "exact_value" in case and not checks.get("exact_ok", True):
        result["grounding_flag"] = True

    if rec:
        result["stage_latency_ms"] = rec.get("stage_latency_ms", {})
        result["latency_ms"] = rec.get("latency_ms")
        result["tokens"] = sum(
            c.get("total_tokens", 0) for c in rec.get("token_usage", []) if isinstance(c, dict)
        )
        result["repaired"] = rec.get("repaired", False)
        result["general_knowledge_used"] = rec.get("general_knowledge_used", False)

    result["primary_count"] = len(resp.primary_entities)
    result["context_count"] = len(resp.context_entities)
    result["relationship_count"] = len(resp.relationships)
    result["case_pass"] = all(checks.values()) if checks else True
    return result


def _paraphrase_route_stability(case: dict, service: QueryService) -> dict | None:
    paraphrases = case.get("paraphrases") or []
    if not case.get("check_paraphrases") or not paraphrases:
        return None
    settings = get_settings()
    client = get_llm_client(settings)
    store = get_session_store()
    expected = set(case.get("expected_routes", []))
    routes = []
    for i, para in enumerate(paraphrases):
        req = _build_request({**case, "question": para}, f"para-{case['id']}-{i}")
        state = store.get_or_create(req.session_id)
        try:
            with session_scope() as s:
                ctx = build_planner_context(s, req, state, settings)
                plan = client.plan_query(ctx).plan
            routes.append(plan.route.value)
        except Exception:  # noqa: BLE001 - a transient probe failure is not fatal
            routes.append("error")
    stable = all(r in expected for r in routes) if expected else None
    return {"paraphrase_routes": routes, "paraphrase_stable": stable}


def main() -> None:
    cases = _load_cases()
    print(f"Loaded {len(cases)} benchmark cases from {CASES_PATH.name}")

    before = _corpus_counts()
    service = QueryService()  # real LLM client per request
    results = []
    t_start = time.perf_counter()

    for case in cases:
        session_id = f"bench-{case['id']}"
        req = _build_request(case, session_id)
        # Per-case isolation: a transient provider/network error on one case (or
        # its paraphrase probe) must never abort the whole benchmark run.
        try:
            resp = service.handle_query(req)
            rec = _log_index().get(resp.request_id)
            scored = _score_case(case, resp, rec)
            para = _paraphrase_route_stability(case, service)
            if para:
                scored.update(para)
        except Exception as exc:  # noqa: BLE001 - record and continue
            scored = {
                "id": case["id"],
                "category": case["category"],
                "route": "error",
                "checks": {},
                "issues": [f"harness error: {type(exc).__name__}: {str(exc)[:120]}"],
                "case_pass": False,
                "harness_error": True,
            }
        results.append(scored)
        status = "PASS" if scored["case_pass"] else "FAIL"
        print(
            f"  [{status}] {case['id']:<14} route={scored.get('route'):<15} "
            f"op={scored.get('operation')} tokens={scored.get('tokens')} "
            f"lat={scored.get('latency_ms')}ms"
        )
        if scored["issues"]:
            print(f"        issues: {scored['issues']}")

    wall_s = round(time.perf_counter() - t_start, 1)
    after = _corpus_counts()

    summary = _summarize(results, before, after, wall_s)
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_PATH.write_text(
        json.dumps({"summary": summary, "cases": results}, indent=2, default=str),
        encoding="utf-8",
    )
    print("\n=== SUMMARY ===")
    print(json.dumps(summary, indent=2))
    print(f"\nResults written to {RESULTS_PATH}")


def _summarize(results: list[dict], before: dict, after: dict, wall_s: float) -> dict:
    def _rate(key: str) -> str:
        vals = [r["checks"][key] for r in results if key in r.get("checks", {})]
        if not vals:
            return "n/a"
        return f"{sum(vals)}/{len(vals)}"

    tokens = [r["tokens"] for r in results if r.get("tokens")]
    lats = [r["latency_ms"] for r in results if r.get("latency_ms")]
    stage_keys = ("planner_ms", "execute_ms", "answer_ms")
    stage_avgs = {}
    for k in stage_keys:
        vs = [r["stage_latency_ms"].get(k, 0.0) for r in results if r.get("stage_latency_ms")]
        stage_avgs[k] = round(sum(vs) / len(vs), 1) if vs else None

    paraphrase = [r for r in results if "paraphrase_stable" in r]
    return {
        "total_cases": len(results),
        "cases_passed": sum(1 for r in results if r["case_pass"]),
        "route_accuracy": _rate("route_ok"),
        "operation_accuracy": _rate("operation_ok"),
        "exact_answer_accuracy": _rate("exact_ok"),
        "viewer_id_accuracy": _rate("viewer_ids_ok"),
        "retrieval_ok": _rate("retrieval_ok"),
        "model_action_accuracy": _rate("model_action_ok"),
        "clarify_ok": _rate("clarify_ok"),
        "grounding_flags": sum(1 for r in results if r.get("grounding_flag")),
        "paraphrase_stable": (
            f"{sum(1 for r in paraphrase if r['paraphrase_stable'])}/{len(paraphrase)}"
            if paraphrase
            else "n/a"
        ),
        "avg_tokens": round(sum(tokens) / len(tokens)) if tokens else None,
        "total_tokens": sum(tokens) if tokens else 0,
        "avg_latency_ms": round(sum(lats) / len(lats)) if lats else None,
        "avg_stage_latency_ms": stage_avgs,
        "wall_seconds": wall_s,
        "corpus_before": before,
        "corpus_after": after,
        "corpus_unchanged": before == after,
    }


if __name__ == "__main__":
    main()
