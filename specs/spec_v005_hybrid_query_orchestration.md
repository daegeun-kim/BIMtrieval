# Specification v005: Hybrid Query Planning and Orchestration

## 1. Purpose

Define how natural-language questions are planned, routed, executed, fused, answered, logged, and translated into frontend/viewer actions.

Governed by:

```text
spec_v002_query_architecture.md
spec_v003_sql_query_path.md
spec_v004_rag_query_path.md
```

This is a blueprint only. Implementation and execution require later task files.

## 2. No Separate Routing LLM Call

Do not add one LLM request solely to classify SQL/RAG/hybrid.

Use two principal OpenAI calls per answered natural-language question:

```text
LLM call 1
→ interpret language
→ choose scope and route
→ produce complete schema-enforced executable plan

Backend
→ validate
→ execute only selected SQL/RAG/graph paths
→ combine bounded evidence

LLM call 2
→ generate final grounded answer from evidence
```

This avoids an additional routing call while preserving paraphrase understanding.

Do not run SQL and RAG for every question. Always running both wastes database/model work, adds irrelevant evidence, and still requires natural-language planning.

## 3. Code Organization

```text
backend/src/llm/
├── client.py
├── schemas.py
├── router.py
├── answerer.py
└── prompts/
    ├── planner_v001.md
    └── answerer_v001.md

backend/src/query/hybrid/
├── schemas.py
├── orchestrator.py
├── concurrency.py
├── combination.py
├── evidence.py
└── errors.py

backend/src/query/service.py
backend/src/viewer/actions.py
backend/src/evaluation/
```

Keep prompts versioned. Keep typed schemas in Python. Do not place orchestration in FastAPI route handlers.

## 4. Planner Model and Configuration

Use OpenAI with initial configurable models:

```text
planner_model = gpt-5-nano
answer_model = gpt-5-nano
```

Load `OPENAI_API_KEY` only in the backend.

Planner and answer models must be independently configurable for later replacement.

Use schema-enforced structured output. Do not parse prompt-only JSON with regex repair.

## 5. Unified Planner Schema

The planner receives:

- current question
- bounded session history
- current scope and active model, if any
- up to five selected entity summaries
- catalog semantic schema or active-model semantic schema
- available operation contracts
- route definitions
- limits and unit conventions

It returns one complete plan equivalent to:

```json
{
  "scope": "active_model",
  "route": "hybrid",
  "source_model_id": 1,
  "catalog_plan": null,
  "sql_plan": {
    "operation": "filter_entities",
    "entity_classes": ["IfcDoor"],
    "filters": [],
    "limit": 500
  },
  "rag_plan": {
    "semantic_query": "doors related to fire separation",
    "search_entity_documents": true,
    "search_relationship_documents": true,
    "top_k_per_kind": 30,
    "threshold_profile": "default_v001"
  },
  "graph_plan": {
    "expand_relationship_endpoints": true,
    "max_depth": 1
  },
  "execution": {
    "mode": "parallel_independent",
    "combination": "intersection"
  },
  "needs_clarification": false,
  "clarification_question": null,
  "viewer_intent": "select_and_fit"
}
```

All subplans must conform to v003/v004 contracts.

## 6. Plan Validation and Repair

Validate:

- scope and active-model consistency
- operation allowlists
- field/operator/type compatibility
- model existence
- source-model isolation
- route/subplan agreement
- limits
- graph depth
- RAG settings
- combination semantics
- no raw SQL

Allow one automatic schema/semantic repair attempt through the planner. After one failed repair, return clarification or a safe error.

Do not enter an unbounded agent/replanning loop.

## 7. Route Semantics

### SQL

Execute only the validated SQL/catalog plan. Use for exact filters, counts, aggregations, metadata, versions, and comparisons.

### RAG

Execute semantic retrieval, then hydrate accepted results from structured tables. SQL hydration does not change the route classification.

### Graph

Execute deterministic relationship/member traversal only.

### Hybrid

Execute explicitly declared SQL, RAG, and/or graph components using the dependency mode below.

### Explain general

No model database retrieval is required unless the question also requests model facts. Return an empty viewer action.

### Clarify

Ask one concise question when ambiguity changes model, field, metric, or route substantially.

## 8. Execution Modes

Support:

```text
parallel_independent
sql_then_rag
rag_then_sql
rag_relationship_then_graph_then_sql
sql_relationship_then_graph_then_rag
```

Run independent SQL and RAG work concurrently using bounded asynchronous tasks.

Do not run in parallel when one path consumes candidates from another.

Apply separate timeouts and cancellation handling. One failure must be represented explicitly; do not silently pretend the missing path returned no matches.

## 9. Combination Semantics

Support explicit canonical-ID operations:

```text
intersection
union
sql_filter_of_rag
rag_rank_of_sql
relationship_endpoint_expansion
```

### Intersection

Return only canonical IDs present in both candidate sets. If empty, report that no object satisfied both constraints. Never silently fall back to union.

### Union

Preserve separate evidence groups:

- exact SQL matches
- semantic-only matches
- matches supported by both

Do not fabricate one comparable score across SQL and RAG.

### Relationship expansion

When a relationship is accepted, retrieve every direct endpoint. Promote endpoints satisfying the main query to primary; retain others as context.

### Rank behavior

Keep RAG scores/ranks internal. Exact SQL constraints behave as Boolean eligibility or separate evidence, not vector weights.

## 10. Evidence Package

Build one bounded evidence object containing:

- question and validated plan
- source-model/catalog context
- exact SQL results
- RAG results with internal scores/ranks
- graph/relationship paths and roles
- canonical IDs and GlobalIds
- primary and context entities
- relationship evidence
- aggregate coverage/missing data
- conflicts
- warnings and partial failures
- provenance classification

Limits supplied to the answer LLM:

```text
maximum primary entities = 50
maximum context entities = 50
maximum relationships = 20
```

When results exceed limits, summarize deterministically before the answer call. Preserve exact totals separately from samples.

Do not pass full canonical JSON or unrestricted generated documents.

## 11. Grounded Answer Call

The second OpenAI call generates the user-facing answer.

It must:

- state model-specific facts only from evidence
- calculate nothing authoritative itself
- preserve exact totals and units
- distinguish retrieval candidates from exhaustive results
- disclose material conflicts
- state missing coverage when it affects conclusions
- ask for clarification when evidence cannot resolve intent
- optionally add general BIM explanation without presenting it as measured model fact
- avoid exposing SQL, query JSON, vector scores, or internal IDs by default

Record internally whether general knowledge was used, even though the normal user-facing answer need not explicitly label it.

## 12. Conversational State

Persist for the browser session only:

- messages
- active source model
- selected model candidate state
- up to five selected viewer entity IDs
- previous canonical result sets
- last route/plan/evidence reference

Follow-up questions must use stored canonical IDs from previous turns, not reconstruct result sets from assistant prose.

Reset immediately clears all session chat, selection, result IDs, and active model. It does not delete database rows or vectors.

## 13. Catalog-to-Model Transition

Catalog results return model candidates and:

```text
viewer.model_action = await_user_confirmation
```

Do not load a large model automatically from an LLM choice.

After user click/confirmation:

- set active `source_model_id`
- reset prior model-specific result context
- instruct frontend to load the model's viewer source
- transition scope to `active_model`

## 14. Viewer Actions

Every response returns a stable viewer-action object, including no-op actions.

Support:

```text
no_op
await_user_confirmation
load_model
select_and_fit
clear_selection
```

Return:

- primary GlobalIds
- context GlobalIds
- semantic role groups
- selected model/viewer source when confirmed

The frontend decides colors and camera mechanics.

## 15. FastAPI Service Contract

Expose one public endpoint:

```text
POST /api/query
```

The endpoint calls a query service, not SQL/RAG modules directly.

The service performs:

1. session/context validation
2. schema-context selection
3. planner call
4. plan validation/one repair
5. selected-path execution
6. evidence combination
7. answer call
8. viewer-action construction
9. safe logging
10. stable response serialization

Use synchronous HTTP initially, with internal async concurrency where applicable. Streaming is deferred.

## 16. Logging and Failure Cases

Use local JSONL for the prototype.

Log safely:

- request/session/model IDs
- question
- planner/answer model identifiers
- validated plan
- execution stages and timing
- SQL operation names, not credentials
- canonical result IDs
- RAG ranks/scores
- combination outcome
- token usage
- answer basis
- warnings/errors
- general-knowledge-used flag
- optional user feedback

Store reusable failed/incorrect cases in versioned JSONL under `backend/evaluation/`.

Do not log secrets or unrestricted canonical JSON.

## 17. Degraded and Failure Behavior

Handle:

- planner refusal/invalid output
- one failed repair
- missing model scope
- SQL timeout
- RAG unavailable
- no candidate above threshold
- graph traversal limit
- partial hybrid failure
- conflicting evidence
- answer-provider failure

Do not silently change route or combination semantics.

If RAG is unavailable but the plan also contains an independent exact SQL path, return the SQL-supported portion with an explicit internal/user-appropriate warning. Do not label it a complete hybrid answer.

## 18. Tests and Evaluation

Test:

- single planner call includes route and complete subplans
- no separate route-classification call
- schema validation and one repair limit
- every route
- every execution dependency mode
- async parallelism only for independent paths
- intersection with empty result does not become union
- union evidence groups
- SQL-filter-of-RAG and RAG-rank-of-SQL
- relationship endpoint promotion/context
- evidence limits and deterministic summarization
- grounded answer restrictions
- conflict and insufficient-evidence behavior
- catalog confirmation transition
- follow-up canonical-ID state
- reset behavior
- stable viewer action shape
- JSONL logging and secret exclusion
- partial availability

Benchmark paraphrases, route accuracy, exact answer correctness, retrieval precision/recall, evidence grounding, hallucination rate, latency, and token usage.

## 19. Acceptance Criteria

Hybrid orchestration is acceptable when:

1. One schema-enforced planner call both chooses the route and creates complete subplans.
2. Python validates plans and executes only selected paths.
3. SQL and RAG run concurrently only when independent.
4. Canonical IDs govern all intersection, union, traversal, and follow-up state.
5. Empty intersections and partial failures are not silently reinterpreted.
6. Evidence supplied to the answer model is bounded and provenance-aware.
7. The answer model makes no unsupported model-specific claims.
8. Session state supports follow-ups and reset without altering stored BIM data.
9. Catalog selection requires user confirmation before viewer loading.
10. Every response contains stable machine-readable viewer actions.
11. Logs support prototype evaluation without exposing secrets.
12. Tests demonstrate routing, execution, fusion, grounding, session behavior, and failure handling.

## 20. Implementation (Task 07 — IMPLEMENTED AND VALIDATED)

This blueprint was implemented and validated by `tasks/task07_done.md`. Summary of the
delivered code and how it satisfies §19.

### Modules

```text
backend/src/llm/
├── schemas.py        # unified, non-recursive planner QueryPlan (all routes)
├── prompts/
│   ├── planner_v001.md
│   └── answerer_v001.md   (loaded via prompts/__init__.py, versioned)
├── client.py         # OpenAI structured-output calls (planner + answerer), token usage
├── serialization.py  # JSON payload builder for LLM calls
├── validation.py     # structural plan validation (no DB)
├── translate.py      # planner plan -> typed execution plans (DB-backed field/model checks)
├── context.py        # sanitized planner context (schema/catalog, ops, limits)
└── answerer.py       # grounded-answer + explain-general helpers

backend/src/query/
├── sql/dispatch.py         # execute typed SQL/catalog/graph plans -> normalized results
├── hybrid/{schemas,combination,concurrency,evidence,errors,orchestrator}.py
├── session.py              # SessionStore + candidate/follow-up state + reset
└── service.py              # full pipeline (planner -> validate/1-repair -> execute -> answer)

backend/src/viewer/actions.py   # + await_user_confirmation / load_model actions
backend/src/api/routes/{query.py (public), dev.py (dev-only, gated)}
backend/src/evaluation/hybrid_failure_cases_v001.jsonl   # curated reusable cases
```

### Prompt / schema versions

- planner prompt: `planner_v001`; answer prompt: `answerer_v001`.
- Planner output schema: `llm.schemas.QueryPlan` (strict, `extra="forbid"`).
- Answer schema: `llm.client.AnswerOutput` (answer + `used_general_knowledge`).
- Models: `planner_model = answer_model = gpt-5-nano`, independently configurable.

### How the acceptance criteria are met

1. **One planner call** produces route + all subplans (`OpenAIQueryClient.plan_query`,
   `chat.completions.parse`). There is no separate routing call — verified by
   `test_single_planner_call_and_no_separate_routing` (planner call count == 1).
2. **Validate + execute selected paths only**: `validate_plan_structure` + `translate_plan`
   with exactly one repair (`QueryService._plan_and_translate`); the orchestrator runs only
   declared paths.
3. **Concurrency only when independent**: `parallel_independent` uses
   `hybrid.concurrency.run_parallel` (thread-per-path, own session); dependent modes are
   sequenced.
4. **Canonical IDs govern everything**: `hybrid.combination` operates purely on id lists;
   session stores previous canonical ids for follow-ups.
5. **No silent reinterpretation**: empty intersection stays empty
   (`test_hybrid_empty_intersection_is_not_union`); a missing path is an explicit partial
   failure / degraded-hybrid warning.
6. **Bounded, provenance-aware evidence**: `hybrid.evidence.apply_bounds` (50/50/20) with
   deterministic overflow summaries; `build_answer_payload` excludes internal RAG scores.
7. **No unsupported claims**: answerer prompt + evidence-only payload; exact totals come
   from the backend, not the model.
8. **Session follow-ups + reset**: `SessionStore`; reset never touches persistent data.
9. **Catalog confirmation**: catalog results return `await_user_confirmation`;
   `confirm_model_id` performs the load transition.
10. **Stable viewer actions**: every response returns a full `ViewerActions` object.
11. **Safe logs**: JSONL via `config.logging.write_jsonl_event` (redacted), runtime logs
    under gitignored `backend/logs/`.
12. **Tests**: `backend/tests/query_hybrid/` (offline) + `backend/tests/query_live/`
    (`test_hybrid_pipeline.py` fake-LLM+DB, `test_hybrid_live_openai.py` real gpt-5-nano).

### Live validation performed

Real `gpt-5-nano` planner + answer calls against the live Schependomlaan model: exact
counts (205 doors, 259 windows), storey grouping, catalog await-confirmation, semantic
fire-separation retrieval, catalog→model load transition, reset, paraphrase equivalence,
and honest clarification when the model exposes no quantity data. No stored BIM/vector data
was modified. Secrets never logged or returned.

## 21. End-to-End Evaluation (Task 08 — VALIDATED)

Validated by `tasks/task08_done.md`. Full report: `docs/evaluation_v001_report.md`.

- Benchmark: `backend/src/evaluation/benchmark_v003_e2e_cases.jsonl` (27 versioned cases
  spanning the required matrix); runner `run_benchmark_v003.py`; committed machine-readable
  results `backend/src/evaluation/benchmark_v003_results.json`.
- Authoritative run through the real `/api/query` pipeline with live `gpt-5-nano`:
  **26/27 cases**, operation 16/16, exact-answer 6/6, viewer-ID 1/1, retrieval 2/2,
  grounding failures **0**, corpus **unchanged** (6989/3473/10462). Latency by stage:
  planner ~20.8 s, execution ~0.4 s, answer ~9.6 s; ~10.5k tokens/query.
- Verified integration defects fixed (with regression tests): log over-redaction of token
  metrics; structured-output length-limit (raised `max_completion_tokens`); catalog
  `is_current` filter crash + translate-time catalog-field validation + defensive execution
  guard; `list_model_versions` family_key fallback; bounded transient-error retry; per-stage
  latency logging; planner-prompt contract clarifications.
- Documented limitations (not defects): occasional semantic-vs-lexical route judgment,
  subjective ambiguity threshold, absent-class clarification, single-model/no-quantity
  corpus. All handled without hallucination.

