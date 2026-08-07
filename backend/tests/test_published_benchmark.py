"""Every published benchmark number is derivable from the results file (Task 36).

Offline: reads two files off disk. No database, no OpenAI, no model.

The failure this prevents is a documentation drift that is invisible to a
reader: a table in `evaluation/benchmark_v003.md` or `README.md` that no longer
matches `evaluation/results/benchmark_v003.json`, or that was never derived from
it at all. A benchmark whose published figures cannot be recomputed is a claim,
not a measurement.
"""

from __future__ import annotations

import json
import statistics
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_RESULTS = _REPO_ROOT / "evaluation" / "results" / "benchmark_v003.json"
_REPORT = _REPO_ROOT / "evaluation" / "benchmark_v003.md"
_README = _REPO_ROOT / "README.md"


@pytest.fixture(scope="module")
def results() -> dict:
    return json.loads(_RESULTS.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def report() -> str:
    return _REPORT.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def readme() -> str:
    return _README.read_text(encoding="utf-8")


def _measured(results: dict) -> list[dict]:
    """Cases that actually made a model call, so have latency and tokens."""
    return [c for c in results["cases"] if "latency_ms" in c]


def _percentile(values: list[float], p: int) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, round((p / 100) * (len(ordered) - 1)))
    return ordered[index]


# ---------------------------------------------------------------------------
# The headline
# ---------------------------------------------------------------------------


def test_the_headline_pass_count_matches_the_results_file(results, report, readme):
    summary = results["summary"]
    passed, total = summary["cases_passed"], summary["total_cases"]

    assert passed == sum(c["case_pass"] for c in results["cases"])
    assert total == len(results["cases"])

    headline = f"**{passed} / {total}**"
    assert headline in report
    assert headline in readme


def test_zero_grounding_failures_is_a_fact_not_a_claim(results, report, readme):
    assert results["summary"]["grounding_flags"] == 0
    assert "**0**" in report
    assert "**0**" in readme


def test_the_corpus_was_unchanged_by_the_run(results):
    """A read-only backend that mutated the corpus would invalidate everything."""
    summary = results["summary"]
    assert summary["corpus_unchanged"] is True
    assert summary["corpus_before"] == summary["corpus_after"]


# ---------------------------------------------------------------------------
# Per-route table
# ---------------------------------------------------------------------------


def test_every_route_row_matches_the_recorded_cases(results, report):
    by_route: dict[str, list[dict]] = {}
    for case in results["cases"]:
        by_route.setdefault(case["route"], []).append(case)

    for route, cases in by_route.items():
        passed = sum(c["case_pass"] for c in cases)
        row = f"| `{route}` | {len(cases)} | {passed} |"
        assert row in report, f"route row for {route!r} is missing or stale"


def test_the_route_medians_match(results, report):
    by_route: dict[str, list[dict]] = {}
    for case in _measured(results):
        by_route.setdefault(case["route"], []).append(case)

    for route, cases in by_route.items():
        latency = statistics.median(c["latency_ms"] for c in cases) / 1000
        tokens = statistics.median(c["tokens"] for c in cases)
        assert f"{latency:.1f} s | {tokens:,.0f} |" in report, (
            f"median latency/tokens for {route!r} do not match the results file"
        )


# ---------------------------------------------------------------------------
# Distribution
# ---------------------------------------------------------------------------


def test_the_latency_and_token_distribution_matches(results, report, readme):
    measured = _measured(results)
    latencies = [c["latency_ms"] for c in measured]
    tokens = [c["tokens"] for c in measured]

    assert f"{_percentile(latencies, 50) / 1000:.1f} s" in report
    assert f"{_percentile(latencies, 90) / 1000:.1f} s" in report
    assert f"{_percentile(tokens, 50):,}" in report

    # The README quotes the same two medians.
    assert f"{_percentile(latencies, 50) / 1000:.1f} s" in readme
    assert f"{_percentile(tokens, 50):,}" in readme


def test_total_tokens_matches(results, report):
    total = sum(c["tokens"] for c in _measured(results))
    assert total == results["summary"]["total_tokens"]
    assert f"**{total:,} tokens**" in report


def test_the_zero_llm_cases_are_disclosed_rather_than_averaged_in(results, report):
    """Two cases make no model call. Silently folding them into the medians as
    zeros would understate latency; dropping them without saying so would hide
    that the sample is 25, not 27."""
    silent = [c["id"] for c in results["cases"] if "latency_ms" not in c]
    assert silent, "expected the state-change cases to make no model call"
    for case_id in silent:
        assert case_id in report
    assert f"n={len(_measured(results))}" not in report  # not a raw dump
    assert str(len(_measured(results))) in report


# ---------------------------------------------------------------------------
# Failures are published
# ---------------------------------------------------------------------------


def test_every_failing_case_is_named_in_the_report(results, report):
    failures = [c for c in results["cases"] if not c["case_pass"]]
    assert failures, "a benchmark reporting no failure at all deserves suspicion"
    for case in failures:
        assert case["id"] in report, f"failing case {case['id']} is not disclosed"


def test_cases_needing_a_repair_call_are_disclosed(results, report):
    for case in results["cases"]:
        if case.get("repaired"):
            assert case["id"] in report


def test_cases_answering_from_general_knowledge_are_disclosed(results, report):
    for case in results["cases"]:
        if case.get("general_knowledge_used"):
            assert case["id"] in report


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------


def test_the_report_states_its_dataset_model_and_version(report):
    for required in ("v003", "IFC2X3", "gpt-5-nano", "bge-m3", "source_model_id=1"):
        assert required in report, f"provenance is missing {required!r}"


def test_an_unrecorded_field_is_stated_as_unknown_not_guessed(report):
    """The results file has no run date. Inventing one would be worse than the gap."""
    assert "Not recorded in the results file" in report


def test_the_report_does_not_publish_a_cost_it_cannot_compute(report):
    """Tokens were recorded; prices were not. A dollar figure here would be fiction."""
    assert "Cost is deliberately not published" in report


def test_the_report_discloses_that_the_measured_pipeline_has_changed(report):
    assert "model roster has since changed" in report
    assert "no claim is made about today's accuracy" in report


def test_the_readme_does_not_overstate_the_result(readme):
    """The summary must carry its own caveat, not just link to one."""
    assert "as it was measured" in readme
    assert "no baseline comparison" in readme
    assert "evaluation/benchmark_v003.md" in readme


def test_the_missing_baseline_arm_is_admitted(report):
    """Without a vector-only or SQL-only arm this shows the pipeline works, not
    that hybrid retrieval beats anything."""
    assert "No baseline comparison" in report


# ---------------------------------------------------------------------------
# Budgets (Task 37)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def evaluation_readme() -> str:
    return (_REPO_ROOT / "evaluation" / "README.md").read_text(encoding="utf-8")


def test_budgets_are_stated_and_the_published_run_is_scored_against_them(evaluation_readme):
    """A budget that appears only after a good result is not a budget."""
    assert "## Budgets" in evaluation_readme
    for budget in ("Grounding failures", "Median latency", "Median tokens", "Corpus mutation"):
        assert budget in evaluation_readme


def test_the_published_run_actually_meets_the_stated_budgets(results, evaluation_readme):
    """The thresholds must be checked against the data, not just asserted in prose."""
    summary = results["summary"]
    measured = _measured(results)

    assert summary["grounding_flags"] == 0
    assert summary["cases_passed"] / summary["total_cases"] >= 0.90
    assert summary["corpus_before"] == summary["corpus_after"]

    latencies = [c["latency_ms"] for c in measured]
    assert _percentile(latencies, 50) <= 30_000
    assert _percentile(latencies, 90) <= 60_000
    assert max(latencies) <= 120_000

    tokens = [c["tokens"] for c in measured]
    assert _percentile(tokens, 50) <= 12_000
    assert _percentile(tokens, 90) <= 20_000


def test_the_latency_budget_is_not_dressed_up(evaluation_readme):
    """24.6 s is too slow for interactive use, and the docs have to say so."""
    prose = " ".join(evaluation_readme.split())
    assert "Latency is the weak number and is not dressed up" in prose
    assert "far too slow for interactive use" in prose


def test_grounding_has_a_zero_budget_and_route_accuracy_does_not(evaluation_readme):
    """The asymmetry is the point: a defensible alternate route is not a defect;
    a confident fabrication about a building is the failure this system exists
    to prevent."""
    prose = " ".join(evaluation_readme.split())
    assert "**0.** Non-negotiable" in prose
    assert "Grounding is allowed to be wrong *never*" in prose
