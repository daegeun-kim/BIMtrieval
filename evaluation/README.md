# Evaluation

BIMtrieval's benchmark: what it measures, where every published number comes
from, and how to reproduce it.

## The four parts

| Part | Location |
| --- | --- |
| **Versioned cases** | `backend/app/evaluation/benchmark_v00{1,2,3}_*.jsonl` |
| **Runner + configuration** | `backend/app/evaluation/` (`run_test_query_suite.py`, `cases.py`, `metrics.py`) |
| **Machine-readable results** | [`results/`](results/) — one JSON per published run |
| **Human-readable report** | [`benchmark_v003.md`](benchmark_v003.md) |

Cases and runner live with the backend because they are backend-owned code that
its own test suite imports. Results and reports live here because they are
published evidence, and a reader should not have to go spelunking for them.

## Current published result

**Benchmark v003** — 27 end-to-end cases, **26 passed**, 0 grounding failures.
Full provenance, per-route accuracy, latency distribution, token cost, and the
one honest failure are in [`benchmark_v003.md`](benchmark_v003.md).

## Reproducing it

### Offline — free, no key, no database

These assert the benchmark's *structure and scoring*, not its live accuracy:
that every case is well-formed, that the metric functions compute what they
claim, and that the published tables can be derived from the results file.

```powershell
cd backend
poetry run pytest tests/query_rag tests/query_hybrid tests/binding
```

### Live — the owner's key, real cost

**This spends money.** Two OpenAI calls per answered question. It is never
imported by the request path, never runs under `pytest`, and is not part of CI.

Prerequisites: a populated database (`bim-db-init` then `bim-import`), a
`DATABASE_URL` read-only role, and your own `OPENAI_API_KEY` in `.env`.

```powershell
cd backend
poetry run python -m app.evaluation.run_test_query_suite --smoke   # 4 cases
poetry run python -m app.evaluation.run_test_query_suite           # full suite
```

The database-backed acceptance suite, which makes **no** OpenAI calls:

```powershell
poetry run pytest -m live
```

## Budgets

What counts as acceptable, stated before the next run rather than after it.
These are derived from the v003 measurements, so they are what this system has
actually demonstrated — not aspirations.

| Budget | Threshold | v003 | Status |
| --- | --- | ---: | --- |
| **Grounding failures** | **0.** Non-negotiable | 0 | met |
| Exact-answer correctness | 100% — an arithmetic answer is right or it is a bug | 6/6 | met |
| Cases passed | ≥ 90% | 26/27 (96%) | met |
| Route accuracy | ≥ 90% | 26/27 (96%) | met |
| Median latency | ≤ 30 s per answered question | 24.6 s | met |
| p90 latency | ≤ 60 s | 41.3 s | met |
| Max latency | ≤ 120 s before the request is a failure | 105.4 s | met, barely |
| Median tokens | ≤ 12,000 per question | 9,357 | met |
| p90 tokens | ≤ 20,000 | 14,521 | met |
| Corpus mutation | **0 rows.** The backend is read-only by construction | unchanged | met |

**Latency is the weak number and is not dressed up.** A 24.6 s median is far too
slow for interactive use, and the max touched 105 s. Execution is ~0.4 s of that:
the cost is model reasoning, essentially in full. The lever is the model roster
and the size of the manifest sent to the binder, not the database.

**Correctness budgets are asymmetric on purpose.** Route selection is allowed to
be wrong 10% of the time because several cases have more than one defensible
route. Grounding is allowed to be wrong *never*, because a confident fabrication
about a building is the one failure this system exists to prevent.

A run that misses a budget is published with the miss stated. Budgets are
revised only with a reason recorded, never to match a disappointing result.

## Rules for publishing a result

1. Every published number traces to a file in `results/`. Nothing is retyped
   from memory.
2. Every result states its dataset, benchmark version, model roster, run date,
   and route — or states explicitly that a field was not recorded. Unknown is
   written as unknown; it is never inferred and never backfilled.
3. Historical results keep their original context and are labelled as
   historical. They are not silently reinterpreted under a newer scoring rule.
4. Failures are published. A benchmark that only reports its wins measures
   nothing.
