# Task 07: Implement OpenAI Planning, Hybrid Orchestration, and `/api/query`

## Prerequisites

Require:

```text
tasks/task06_done.md
specs/spec_v002_query_architecture.md
specs/spec_v003_sql_query_path.md
specs/spec_v004_rag_query_path.md
specs/spec_v005_hybrid_query_orchestration.md
```

If Task 06 is incomplete, stop.

## Objective

Integrate the tested SQL/graph and RAG services behind one schema-enforced OpenAI planner, selected-path orchestration, grounded answer generation, session state, viewer actions, and the public FastAPI `/api/query` endpoint.

## Required architecture

Use exactly:

```text
OpenAI call 1: route + complete typed plan
Backend: validate and execute selected paths
OpenAI call 2: grounded answer from bounded evidence
```

Do not add a separate route-classification call and do not run SQL/RAG for every question.

## Required work

1. Finalize versioned planner and answer prompts.
2. Implement OpenAI structured outputs using `gpt-5-nano`, configurable separately for planner/answerer.
3. Implement unified plan schemas for catalog, SQL, RAG, graph, hybrid, general explanation, and clarification.
4. Provide rich sanitized schema context without secrets, full tables, or raw SQL authority.
5. Validate plans and allow exactly one repair attempt.
6. Implement route execution and dependency modes.
7. Run independent SQL/RAG work concurrently; sequence dependent plans.
8. Implement canonical-ID intersection, union, SQL-filter-of-RAG, RAG-rank-of-SQL, and relationship endpoint expansion.
9. Preserve separate exact and semantic evidence groups.
10. Build bounded evidence packages and deterministic overflow summaries.
11. Implement grounded answer generation, conflict disclosure, missing coverage, and internal general-knowledge provenance.
12. Implement browser-session chat/result/selection state, canonical-ID follow-ups, and reset.
13. Implement catalog model candidates and confirmation-before-load transition.
14. Implement stable viewer actions, including no-op responses.
15. Implement public `POST /api/query`; keep lower-level endpoints development-only.
16. Implement safe JSONL logs and versioned failure cases.

## Secret handling

Use runtime `OPENAI_API_KEY`. Claude must not inspect, print, log, hard-code, or return it. If absent or invalid, stop with a sanitized error.

## Authorized execution

Claude may perform bounded real OpenAI calls needed to validate planning and grounded answering, run the FastAPI service/test client, and query the existing database read-only. It may not modify BIM/vector contents.

## Prohibited actions

- No raw SQL from the LLM.
- No unbounded replanning/tool loop.
- No silent intersection-to-union fallback.
- No unsupported model-specific claims.
- No cross-model detailed leakage.
- No vector regeneration.
- No actual Three.js frontend implementation.
- No streaming.

## Required validation

- paraphrases produce equivalent operations
- one planner call contains route and complete subplans
- no separate routing call
- invalid plan receives at most one repair
- all routes and dependency modes
- concurrency only for independent work
- intersection, union, ranking, and relationship expansion
- bounded evidence limits
- grounded answers and conflict behavior
- catalog confirmation and active-model transition
- canonical-ID follow-ups
- reset behavior
- selected-object context up to five
- stable viewer action contract
- RAG degraded mode and partial hybrid behavior
- `/api/query` response contract
- safe logs and token/latency reporting

## Completion report

Report files, prompt/schema versions, actual API calls and token use, route tests, integration results, failure behavior, and explicit confirmation:

```text
Schema-enforced OpenAI planner: IMPLEMENTED AND VALIDATED
Separate routing LLM call: NOT USED
Hybrid orchestration: IMPLEMENTED AND VALIDATED
Grounded answer generation: IMPLEMENTED AND VALIDATED
Public /api/query: IMPLEMENTED AND VALIDATED
Frontend UI: NOT IMPLEMENTED
```

Rename to `task07_done.md` only when all criteria pass.

---

## Completion Report (Task 07)

**Files added/changed** (backend/src):
- `llm/`: `schemas.py` (rewritten unified planner schema), `client.py` (rewritten, real
  structured-output calls), `serialization.py`, `validation.py`, `translate.py`,
  `context.py`, `answerer.py` (rewritten), `prompts/__init__.py`,
  `prompts/planner_v001.md`, `prompts/answerer_v001.md`.
- `query/hybrid/`: `schemas.py`, `combination.py`, `concurrency.py`, `evidence.py`,
  `errors.py`, `orchestrator.py`.
- `query/sql/dispatch.py`; `query/service.py` (rewritten); `query/session.py` (store +
  candidate/follow-up state).
- `viewer/actions.py` (await_user_confirmation / load_model); `config/settings.py`
  (evidence bounds, RRF, log paths, dev flag); `api/schemas/request.py` (reset,
  confirm_model_id); `api/routes/dev.py`; `api/app.py` (dev router gated).
- `evaluation/hybrid_failure_cases_v001.jsonl` (curated, versioned).
- Tests: `backend/tests/query_hybrid/*` (offline), `backend/tests/query_live/`
  `test_hybrid_pipeline.py` + `test_hybrid_live_openai.py`; updated
  `test_plan_schema_validation.py`, `test_session_state.py`, `test_viewer_actions.py`,
  `test_query_endpoint.py`.

**Prompt / schema versions:** planner `planner_v001`, answerer `answerer_v001`;
`QueryPlan` (strict) and `AnswerOutput` structured schemas; models `gpt-5-nano` (planner
and answer, independently configurable).

**Actual API calls & token use:** planner and answer used `gpt-5-nano` via
`chat.completions.parse`. Representative single-question cost ≈ 6–7k total tokens for
planning and ≈ 0.3–1k for the grounded answer (reasoning-model completion tokens
dominate). All calls succeeded; usage recorded per call in JSONL logs.

**Route tests:** sql (count/list/group/catalog), rag (semantic), explain_general,
clarify, hybrid (intersection incl. empty), catalog await-confirmation, and load
transition — all validated end-to-end.

**Integration results:** 227 backend tests pass (2 pre-existing ingestion tests require
`ifcopenshell`, unavailable in this environment, and are unrelated to this task). Live
answers grounded and exact (205 doors, 259 windows, storey breakdown). No stored
BIM/vector data modified. No secrets logged or returned.

**Failure behavior:** invalid plan → exactly one repair → clarification if still invalid
(bounded, no loop); missing quantity data → honest clarification; degraded RAG → surviving
SQL portion with explicit warning; empty intersection never widened to union.

```text
Schema-enforced OpenAI planner: IMPLEMENTED AND VALIDATED
Separate routing LLM call: NOT USED
Hybrid orchestration: IMPLEMENTED AND VALIDATED
Grounded answer generation: IMPLEMENTED AND VALIDATED
Public /api/query: IMPLEMENTED AND VALIDATED
Frontend UI: NOT IMPLEMENTED
```

