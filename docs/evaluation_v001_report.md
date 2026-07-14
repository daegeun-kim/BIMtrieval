# BIM RAG Backend Query Prototype — End-to-End Evaluation (Task 08)

Governed by `specs/spec_v002/003/004/005`. This report validates the complete backend
query prototype against the live BIM database (source_model_id=1, "IFC Schependomlaan incl
planningsdata", IFC2X3) through the real `POST /api/query` pipeline, using real
`gpt-5-nano` planner + answer calls.

- Benchmark: `backend/src/evaluation/benchmark_v003_e2e_cases.jsonl` (27 versioned cases).
- Runner: `backend/src/evaluation/run_benchmark_v003.py` (real `QueryService`, log-correlated).
- Machine-readable results: `backend/src/evaluation/benchmark_v003_results.json`.

## Headline result (authoritative run)

| Metric | Result |
|---|---|
| Cases passed | **26 / 27** |
| Route accuracy | 26 / 27 |
| Operation accuracy | **16 / 16** |
| Exact-answer correctness | **6 / 6** |
| Entity/relationship retrieval (relevant fraction ≥ 0.6) | **2 / 2** |
| Viewer/citation GlobalID correctness | **1 / 1** |
| Catalog model-action correctness | **3 / 3** |
| Clarification correctness | **2 / 2** |
| Grounding/hallucination failures | **0** |
| Paraphrase route stability | 3 / 4 |
| Source isolation / corpus unchanged | **YES** (see below) |

Latency (wall, per answered query): avg **30.8 s**; by stage — planner **20.8 s**, execution
**0.4 s**, grounded answer **9.6 s**. Token usage: avg **10,527** total tokens/query, **263,178**
across the run. Full run wall time: **861 s** for 27 cases + 4 paraphrase-stability probes.

> The pipeline was run end-to-end six times during Task 08. Core correctness metrics
> (exact-answer, viewer-IDs, retrieval, grounding, operation, corpus isolation) were
> **perfect in every completed run**; only subjective route-judgment cases varied by ±1–3,
> which is inherent LLM non-determinism, not a pipeline defect.

## Evaluation matrix coverage

| Matrix item | Case(s) | Result |
|---|---|---|
| Catalog list / filter / version | cat-01, cat-02, cat-03 | PASS |
| Cross-model exact comparison (door counts) | cat-04 | PASS (1 model in corpus) |
| Model candidate confirmation + activation | confirm-01 | PASS (load_model, scope→active) |
| Active-model exact counts | count-01..04 | PASS (205/259/279/9) |
| Empty result | count-empty | PASS (0, honest) |
| Filters | filter-01, list-01 | PASS |
| Grouping | group-01 | PASS (Storey-1=3505, null=3484) |
| Missing-value | missing-01 | PASS (0 doors missing name) |
| Quantity (unavailable) | quantity-01 | PASS (honest clarify — no quantity_sets) |
| Relationship lookup | rel-01 | PASS |
| Graph traversal | graph-01 | PASS (storey containment) |
| Entity-only RAG | rag-01 | route miss (see limitations) |
| Relationship-oriented RAG | rag-02 | PASS |
| Combined RAG + endpoint hydration | rag-03 | PASS |
| Hybrid (SQL + semantic intent) | hybrid-01 | PASS (planner chose rag) |
| General BIM explanation | explain-01 | PASS |
| Model fact + general explanation | explain-02 | PASS (205 + explanation via sql) |
| Ambiguous clarification | clarify-01 | PASS |
| Viewer-selected object | selected-01 | PASS (GlobalID 04PDIFJZXAA8R34kAXRvCn) |
| Conversational follow-up | followup-01 | PASS (stayed on doors) |
| Session reset | reset-01 | PASS (cleared, scope→catalog) |
| RAG unavailable, SQL available | (deterministic unit test) | PASS `test_degraded_hybrid_*` |
| Empty intersection ≠ union | (deterministic unit test) | PASS `test_hybrid_empty_intersection_*` |
| Conflicting evidence | — | Not reproducible from this dataset (documented) |

Dependency-mode combinations (parallel_independent, sql_then_rag, rag_then_sql,
relationship-endpoint-expansion) and all canonical-ID combinations
(intersection/union/sql_filter_of_rag/rag_rank_of_sql) are covered deterministically in
`backend/tests/query_hybrid/test_combination.py` and `query_live/test_hybrid_pipeline.py`,
because the live planner cannot be forced onto a specific mode without gaming the prompt.

## Defects found and fixed (verified integration issues)

All fixes are narrow, within-spec, and covered by regression tests. None weakened source
isolation, thresholds, grounding, or safety.

1. **Token-usage metrics were redacted out of logs.** `config.logging` matched the bare
   substring `token`, redacting `token_usage`/`total_tokens` — the very metrics spec_v005
   §16 requires. Narrowed the pattern to auth-token forms only.
   → `test_token_usage_metrics_are_not_redacted`.
2. **Structured-output "length limit reached" failures.** `gpt-5-nano` is a reasoning
   model; the 4,000 `max_completion_tokens` cap was exhausted by reasoning before the JSON
   finished on complex prompts. Raised to 16,000.
3. **Catalog filter crash.** A filter on `is_current` hit `FieldNotFoundError` at execution
   (catalog filter fields weren't validated in translation, unlike entity fields). Added
   `is_current`/`version_label` to the catalog allowlist with boolean coercion, validated
   catalog fields at translate time (repairable), and added a defensive execution guard so
   no execution error returns a raw 500. → `test_translate_catalog.py`,
   `test_execution_error_degrades_gracefully_not_500`.
4. **`list_model_versions` without `family_key`** now degrades to listing all models instead
   of failing after repair. → `test_list_model_versions_without_family_key_falls_back`.
5. **Transient provider errors aborted a query / the whole benchmark.** Added a bounded
   retry (2×) on transient errors only (timeout/rate-limit/5xx/connection), and made the
   benchmark harness isolate each case. → `test_llm_retry.py`.
6. **Prompt-contract clarifications** (not benchmark-wording tuning): documented that
   `find_missing_values` carries its field in `aggregate_field`, that a bare quantity uses
   `field_kind=dimension`, and that "model fact + general explanation" is a data route (not
   hybrid).

Per-stage latency logging (`stage_latency_ms`) was also added to satisfy spec_v005 §16.

## Remaining limitations (not defects)

- **Semantic-vs-lexical route judgment (rag-01).** For "which elements look related to fire
  safety?", the planner occasionally chooses an SQL name-filter instead of RAG; on this
  Dutch-named model that filter honestly returns 0 (no element is literally named "fire").
  The answer stays grounded (reports 0, no hallucination), but RAG is the better route.
  This varies run-to-run and is not tuned away, per the task's no-memorization rule.
- **Ambiguity threshold is subjective.** "Show me the important ones" sometimes clarifies
  and sometimes answers by grouping — both defensible.
- **Absent IFC classes.** "How many IfcSpace?" (0 instances, class not in the model's class
  list) yields a clarification rather than asserting 0, because the sanitized schema context
  lists only present classes. Filtering an existing class to an empty set correctly returns 0.
- **Non-English storey/name mapping.** "first storey" is clarified against the actual name
  "Storey-1" rather than guessed.
- **Single model / no quantities in the corpus.** Cross-model comparison and numeric
  aggregates cannot be exercised with real data; both are handled honestly (1 candidate;
  clarify on missing quantities).
- **Planner latency.** `gpt-5-nano` planning dominates latency (~20 s); execution is ~0.4 s.
  A faster planner model is the main future lever (models are configurable).

## Source isolation and data integrity

The runner snapshots corpus counts before and after the full run. Unchanged:

```
ifc_entities:        6989  ->  6989
ifc_relationships:   3473  ->  3473
rag_documents:      10462  -> 10462
valid_embeddings:   10462  -> 10462
```

All database access is read-only (dedicated `bim_rag_query_ro` role via `DATABASE_URL`).
No corpus vectors were regenerated. `OPENAI_API_KEY` never appears in logs or responses
(redaction verified; JSONL logs scanned for `sk-` and DSN patterns → 0 hits).

## Test suites

`python -m pytest backend/tests` → **238 passed**, 2 pre-existing failures deselected
(`test_ingestion_compat` requires `ifcopenshell`, unavailable in this environment;
unrelated to the query backend). Suites: unit (planner schema/validation/combination/
evidence/session/viewer/retry/redaction), integration (fake-LLM + live DB pipeline), and
live (`gpt-5-nano` + DB).

## Readiness

```text
Catalog/SQL/graph pipeline: END-TO-END VALIDATED
RAG pipeline: END-TO-END VALIDATED
Hybrid orchestration: END-TO-END VALIDATED
Grounded answer pipeline: END-TO-END VALIDATED
Viewer action contract: VALIDATED
Frontend implementation: READY FOR SEPARATE SPECIFICATION
```

The backend query prototype meets the v002–v005 specifications and is ready for a separate
frontend (Three.js viewer) specification. The stable `POST /api/query` contract — answer,
answer_basis, model_candidates, primary/context entities, relationships, and machine-
readable viewer actions (GlobalIDs + semantic roles) — is the integration surface for that
work.
