# Benchmark v003 — end-to-end hybrid retrieval

Every number below is derived from
[`results/benchmark_v003.json`](results/benchmark_v003.json). Nothing here is
retyped, estimated, or carried over from a different run.

## Provenance

| Field | Value |
| --- | --- |
| Benchmark version | **v003** |
| Cases | 27, versioned in `backend/app/evaluation/benchmark_v003_e2e_cases.jsonl` |
| Dataset | `IFC Schependomlaan incl planningsdata.ifc` (IFC2X3), `source_model_id=1` — the only model in the corpus at run time |
| Corpus size | 6,989 entities · 3,473 relationships · 10,462 RAG documents (all with valid embeddings) |
| Embedding model | BAAI/bge-m3, dim 1024 |
| LLM roster | `gpt-5-nano` for both the planner and the answer writer |
| Reasoning effort | Not recorded in the results file |
| Run date | **Not recorded in the results file.** Committed 2026-07-15; the run is on or before that date |
| Database access | Read-only, through the dedicated `bim_rag_query_ro` role |
| Runner | The Task 08 harness, since superseded — see [Reproducibility](#reproducibility) |

> **What "not recorded" means here.** The v003 results file has no metadata
> block: run date, reasoning effort, and prompt versions were never written into
> it. They are stated as unknown rather than reconstructed from commit dates or
> current defaults, because a plausible guess in a benchmark table is worse than
> an admitted gap. Future runs should emit provenance alongside the metrics; that
> is a fix for the runner, not for this document.

> **The model roster has since changed.** The pipeline now defaults to
> `gpt-5.4-nano` (binder), `gpt-5-mini` (correction), and `gpt-5.4-mini` (answer),
> and Task 25 replaced the single planner call with a binder + constraint-ledger
> architecture. **These results describe the pipeline as it was**, and are not a
> measurement of the current one. Re-running v003 against the current roster is
> an owner-run step; until it happens, no claim is made about today's accuracy.

## Headline

| Metric | Result |
| --- | ---: |
| **Cases passed** | **26 / 27** |
| Route accuracy | 26 / 27 |
| Operation accuracy | 16 / 16 |
| Exact-answer correctness | 6 / 6 |
| Viewer/citation GlobalID correctness | 1 / 1 |
| Retrieval relevance (relevant fraction ≥ 0.6) | 2 / 2 |
| Catalog model-action correctness | 3 / 3 |
| Clarification correctness | 2 / 2 |
| **Grounding / hallucination failures** | **0** |
| Paraphrase route stability | 3 / 4 |
| Corpus unchanged after the run | yes |

## Accuracy and cost by route

The route the pipeline *chose* for each case. Latency and tokens are medians
over the 25 cases that made a model call.

| Route taken | Cases | Passed | Median latency | Median tokens |
| --- | ---: | ---: | ---: | ---: |
| `sql` | 19 | 18 | 24.1 s | 9,246 |
| `rag` | 3 | 3 | 41.3 s | 15,945 |
| `clarify` | 2 | 2 | 22.7 s | 10,732 |
| `explain_general` | 2 | 2 | 26.5 s | 8,848 |
| `graph` | 1 | 1 | 29.6 s | 12,976 |

Two cases — `confirm-01` (model activation) and `reset-01` (session reset) —
made **no** model call at all, so they carry no latency or token figure. That is
the design working: a state change should not cost a token.

`hybrid-01` is listed under the route the planner actually chose (`rag`), not the
route it was offered. Scoring credits a case when the chosen route is in its
expected set, so a legitimate alternative is not marked wrong.

### Coverage by query type

| Category | Cases |
| --- | --- |
| Catalog (list / filter / version / cross-model compare) | 4 |
| Exact count | 4 |
| Filter, list, group, missing-value | 4 |
| Relationship lookup, graph traversal | 2 |
| RAG (entity / relationship / combined) | 3 |
| Hybrid intersection | 1 |
| General + model-fact explanation | 2 |
| Clarification, ambiguity, empty result, unavailable quantity | 4 |
| Model activation, session reset, selected object, conversational follow-up | 4 |

## Latency and token distribution

Across the 25 model-calling cases:

| | min | p50 | p90 | max |
| --- | ---: | ---: | ---: | ---: |
| Latency | 15.9 s | 24.6 s | 41.3 s | 105.4 s |
| Tokens | 6,942 | 9,357 | 14,521 | 31,234 |

Total: **263,178 tokens** across the run; 861 s wall clock for 27 cases plus 4
paraphrase-stability probes.

By stage, averaged: planner **20.8 s**, execution **0.4 s**, grounded answer
**9.6 s**. Database execution is roughly 1.3% of end-to-end latency — the cost of
this system is model reasoning, essentially in full.

**Cost is deliberately not published.** The results file records tokens, not
prices, and the run predates the versioned pricing registry now in
`app/llm/pricing.py`. Multiplying old token counts by today's prices would
produce a number that looks precise and means nothing.

## The failure

One case failed, and it is the interesting one.

**`rag-01` — "which elements look related to fire safety?"**
Expected route `rag` or `hybrid`; the planner chose `sql` and applied a name
filter. On this Dutch-named model, no element is literally named "fire", so the
filter honestly returned **0**.

- The answer stayed **grounded**: it reported zero and invented nothing.
- The *route* was wrong. This is a semantic question, and a lexical name filter
  is the wrong instrument for it.
- Paraphrase stability was 3/4, and `rag-01` is the case that varied — the same
  question routed differently across runs.

It is left failing on purpose. Adding "fire safety" to a prompt or a route
heuristic would fix the number and fix nothing else.

### Cases that needed a repair call

`quantity-01`, `rag-03`, and `hybrid-01` each required the pipeline's bounded
one-time corrective call before producing a valid plan. All three then passed.

### Cases answering from general knowledge

`explain-01` and `explain-02` set `general_knowledge_used`. `explain-02` combines
a model fact (205 doors, from SQL) with a general explanation, and the flag
records that mixture rather than hiding it.

## Honest limitations

These bound what this benchmark can claim. None is a defect.

- **One model, one schema.** The corpus held a single IFC2X3 model, so
  cross-model comparison is exercised against a one-candidate catalog, and the
  ranking behaviour behind it is untested at scale.
- **No quantity sets in the dataset.** Numeric aggregates over IFC quantities
  cannot be measured here. `quantity-01` verifies the honest-clarification path
  instead, which is the correct behaviour but not the same as measuring the
  feature.
- **Route judgment is partly subjective.** Whether "show me the important ones"
  should clarify or group is genuinely arguable. Cases like this are scored
  against a set of acceptable routes, not one right answer.
- **27 cases is small.** These are categorical coverage probes, not a
  statistically powered accuracy estimate. A single case moving changes the
  headline by ~4 percentage points.
- **No baseline comparison.** There is no "vector-only" or "SQL-only" arm, so
  this measures whether the hybrid pipeline works — not how much hybrid
  retrieval *beats* a simpler approach. That comparison is the single most
  valuable addition to this benchmark and has not been run.
- **LLM non-determinism.** The pipeline was run end-to-end six times during the
  original task. Correctness metrics (exact answers, viewer IDs, retrieval,
  grounding, operations, corpus isolation) were identical every time; only
  route-judgment cases varied by ±1–3.

## Source isolation

The runner snapshots corpus counts before and after. Unchanged across the run:

```
ifc_entities:        6989  ->  6989
ifc_relationships:   3473  ->  3473
rag_documents:      10462  -> 10462
valid_embeddings:   10462  -> 10462
```

All access was read-only through `bim_rag_query_ro`. `OPENAI_API_KEY` never
appeared in logs or responses; JSONL logs were scanned for `sk-` and DSN
patterns with zero hits.

## Reproducibility

The v003 runner (`run_benchmark_v003.py`) was removed when Task 25 replaced the
planner architecture. Its successor is
`backend/app/evaluation/run_test_query_suite.py`, which runs the recorded query
set against the current binder pipeline and writes `specs/test_query_v3.md`.

**These two are not interchangeable**, and the difference matters: v003's
27-case scored JSON and the current suite's Markdown transcript measure
different pipelines with different scoring. Reproducing the table above
byte-for-byte is not possible; what *is* reproducible is the current pipeline's
behaviour on the same questions.

Commands are in [`README.md`](README.md).

## Historical results

Earlier runs are preserved with their original context and are **not** restated
under current scoring:

| Document | Scope |
| --- | --- |
| `docs/evaluation_v001_report.md` | The Task 08 report this benchmark's numbers come from, including the defects found and fixed during that run |
| `specs/test_query_v1.md` | First recorded query set |
| `specs/test_query_v2.md` | Regenerated against the Task 24 pipeline |
| `specs/test_query_v3.md`, `specs/test_query_v3-1.md` | Regenerated against the Task 25 binder pipeline |
| `backend/app/evaluation/rag_calibration_v001.jsonl` | The 8-question calibration behind the 0.50 / 0.55 similarity thresholds |
| `backend/app/evaluation/hybrid_failure_cases_v001.jsonl` | Curated failure cases kept as a regression dataset |
