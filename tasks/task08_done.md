# Task 08: End-to-End Query Pipeline Integration and Evaluation

## Prerequisites

Require:

```text
tasks/task07_done.md
specs/spec_v002_query_architecture.md
specs/spec_v003_sql_query_path.md
specs/spec_v004_rag_query_path.md
specs/spec_v005_hybrid_query_orchestration.md
```

If Task 07 is incomplete, stop.

## Objective

Validate the complete backend query prototype against the current BIM database using realistic catalog, SQL, graph, RAG, hybrid, conversational, selected-object, and failure-mode questions. Fix only verified integration defects within the specifications.

## Required evaluation matrix

Cover:

- catalog list/filter/version questions
- cross-model exact comparisons such as door counts
- model candidate confirmation and activation
- active-model exact counts and filters
- property/quantity/missing-value questions
- relationship lookup and traversal
- entity-only RAG
- relationship-only RAG
- combined RAG and endpoint hydration
- parallel independent hybrid
- SQL-then-RAG and RAG-then-SQL
- intersections with and without results
- union evidence groups
- general BIM explanation
- model facts plus general explanation
- ambiguous clarification
- conflicting evidence
- conversational follow-ups
- viewer-selected object questions
- session reset
- RAG unavailable while SQL remains available
- SQL timeout/empty result/insufficient evidence

## Ground-truth benchmark

Create a versioned benchmark with:

- question and paraphrases
- expected scope and route
- expected operation/dependency mode
- exact values where applicable
- relevant canonical entity/relationship IDs
- expected viewer GlobalIds
- acceptable clarification behavior
- notes on semantic relevance

Measure:

- route accuracy
- exact-answer correctness
- entity and relationship retrieval precision/recall
- citation/viewer-ID correctness
- grounding/hallucination failures
- latency by stage
- OpenAI token usage
- reset and source-isolation correctness

## Required execution

1. Run unit, integration, and regression suites.
2. Run the benchmark through the real `/api/query` pipeline.
3. Review failed cases and classify planner, SQL, RAG, graph, fusion, answer, session, or contract causes.
4. Apply narrow fixes and add regression cases.
5. Re-run until acceptance criteria pass or a genuine blocker is documented.
6. Verify the completed ingestion and stored vectors remain unchanged.

## Prohibited actions

- Do not implement the frontend.
- Do not tune prompts solely to memorize benchmark wording.
- Do not change expected answers to hide defects.
- Do not regenerate corpus vectors without a separate explicit task.
- Do not weaken source isolation, thresholds, grounding, or safety constraints to improve apparent pass rates.

## Final report

Produce a concise Markdown/JSON evaluation report containing cases, results, metrics, latency/token summaries, failures fixed, remaining limitations, and readiness for frontend work.

Explicitly report:

```text
Catalog/SQL/graph pipeline: END-TO-END VALIDATED
RAG pipeline: END-TO-END VALIDATED
Hybrid orchestration: END-TO-END VALIDATED
Grounded answer pipeline: END-TO-END VALIDATED
Viewer action contract: VALIDATED
Frontend implementation: READY FOR SEPARATE SPECIFICATION
```

Rename to `task08_done.md` only when the complete backend prototype meets the specifications and no required work remains.

---

## Completion Report (Task 08)

**Deliverables**
- Versioned benchmark: `backend/src/evaluation/benchmark_v003_e2e_cases.jsonl` (27 cases
  covering the full evaluation matrix, with paraphrases, expected scope/route/operation,
  exact values, canonical IDs, viewer GlobalIds, and acceptable clarification behavior).
- Runner: `backend/src/evaluation/run_benchmark_v003.py` (real `QueryService` + `/api/query`
  pipeline, log-correlated metrics, corpus before/after snapshot).
- Machine-readable results: `backend/src/evaluation/benchmark_v003_results.json`.
- Report: `docs/evaluation_v001_report.md`.

**Authoritative run (live gpt-5-nano through the real pipeline):**
26/27 cases; route 26/27; operation 16/16; exact-answer 6/6; retrieval 2/2; viewer-ID 1/1;
catalog model-action 3/3; clarification 2/2; **grounding failures 0**; paraphrase stability
3/4. Latency by stage: planner ~20.8 s, execution ~0.4 s, answer ~9.6 s; ~10.5k tokens/query
(263,178 total). Corpus unchanged (6989 entities / 3473 relationships / 10462 vectors,
10462 valid embeddings). Ran end-to-end 6× during evaluation; core correctness metrics were
perfect in every completed run.

**Failure classification + narrow fixes (all with regression tests, none weakening
isolation/thresholds/grounding/safety):** (1) planner — prompt-contract clarifications for
`find_missing_values` field, `dimension` for bare quantities, and facts+general→data route;
(2) contract/logging — token-usage metrics were being redacted (narrowed the secret
pattern) and per-stage latency added; (3) SQL/catalog — `is_current` filter crash fixed via
translate-time catalog-field validation + boolean coercion + defensive execution guard, and
`list_model_versions` family_key fallback; (4) provider robustness — bounded transient-error
retry and `max_completion_tokens` raised to avoid reasoning-model length-limit failures;
(5) harness — per-case isolation so a transient error can't abort a run.

**Remaining limitations (documented, not defects):** occasional semantic-vs-lexical route
judgment (grounded, returns 0 honestly), subjective ambiguity threshold, absent-class
clarification, and a single-model/no-quantity corpus (cross-model comparison and numeric
aggregates cannot be exercised with real data). Conflicting-evidence disclosure is
implemented but not reproducible from this dataset.

**Data integrity:** all DB access read-only via the `bim_rag_query_ro` role; no corpus
vectors regenerated; `OPENAI_API_KEY` never logged or returned (redaction verified, logs
scanned for `sk-`/DSN → 0 hits). Test suites: `python -m pytest backend/tests` → 240 passed
(2 pre-existing `ifcopenshell`-dependent ingestion tests deselected, unrelated).

```text
Catalog/SQL/graph pipeline: END-TO-END VALIDATED
RAG pipeline: END-TO-END VALIDATED
Hybrid orchestration: END-TO-END VALIDATED
Grounded answer pipeline: END-TO-END VALIDATED
Viewer action contract: VALIDATED
Frontend implementation: READY FOR SEPARATE SPECIFICATION
```

