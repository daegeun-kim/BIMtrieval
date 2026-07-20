# Specification v005: Hybrid Query Planning and Orchestration

## Current architecture and frontend-contract amendment

The active backend is the independent Poetry application under `backend/app/`. Read every
`backend/src/...` path later in this document as `backend/app/...`. The backend has no dependency
on ingestion Python code.

`spec_v006_frontend_application.md` is authoritative for frontend behavior. Its narrow deterministic
model-list, viewer-asset, and GlobalId-resolution endpoints do not add LLM calls and do not alter
the two-call planner/answer architecture described here.

The frontend sends selected IFC GlobalIds scoped to an active `source_model_id`. Trusted backend
code resolves them to canonical entity IDs before existing SQL/RAG/graph planning and execution.
Invalid, duplicate, cross-model, or excessive selections are rejected or safely bounded before
LLM context is constructed.

**Clear Chat** and **Reset App** are separate controls. Clear Chat removes visible and server-side
conversation history plus current answer evidence while preserving the active model and manual
viewer selection. Reset App returns to the initial no-model state and clears all conversational,
selection, result, and active-model state. Both create a fresh conversation identity; neither
deletes persistent BIM data, stored vectors, prepared viewer assets, or IndexedDB geometry cache.

Normal tests never call OpenAI. The one-time connectivity check from Task 09 is complete and its
live test module was deleted; do not recreate persistent live-provider tests.

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
backend/app/llm/
├── client.py
├── schemas.py
├── router.py
├── answerer.py
└── prompts/
    ├── planner_v001.md
    └── answerer_v001.md

backend/app/query/hybrid/
├── schemas.py
├── orchestrator.py
├── concurrency.py
├── combination.py
├── evidence.py
└── errors.py

backend/app/query/service.py
backend/app/viewer/actions.py
backend/app/evaluation/
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
backend/app/llm/
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

backend/app/query/
├── sql/dispatch.py         # execute typed SQL/catalog/graph plans -> normalized results
├── hybrid/{schemas,combination,concurrency,evidence,errors,orchestrator}.py
├── session.py              # SessionStore + candidate/follow-up state + reset
└── service.py              # full pipeline (planner -> validate/1-repair -> execute -> answer)

backend/app/viewer/actions.py   # + await_user_confirmation / load_model actions
backend/app/api/routes/{query.py (public), dev.py (dev-only, gated)}
backend/app/evaluation/hybrid_failure_cases_v001.jsonl   # curated reusable cases
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
12. **Tests at Task 07 completion**: `backend/tests/query_hybrid/` (offline) plus
    `backend/tests/query_live/`. Task 09 subsequently performed the authorized one-time provider
    connectivity check and deleted `test_hybrid_live_openai.py`; current normal tests make zero
    OpenAI calls and must remain offline/fake-LLM for provider behavior.

### Live validation performed

Real `gpt-5-nano` planner + answer calls against the live Schependomlaan model: exact
counts (205 doors, 259 windows), storey grouping, catalog await-confirmation, semantic
fire-separation retrieval, catalog→model load transition, reset, paraphrase equivalence,
and honest clarification when the model exposes no quantity data. No stored BIM/vector data
was modified. Secrets never logged or returned.

## 21. End-to-End Evaluation (Task 08 — VALIDATED)

Validated by `tasks/task08_done.md`. Full report: `docs/evaluation_v001_report.md`.

- Benchmark: `backend/app/evaluation/benchmark_v003_e2e_cases.jsonl` (27 versioned cases
  spanning the required matrix); runner `run_benchmark_v003.py`; committed machine-readable
  results `backend/app/evaluation/benchmark_v003_results.json`.
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

## 22. Task 13 Implementation Notes — tracing, compact answers, sample-detail intent

Task 13 (`tasks/task13_done.md`) added opt-in observability and changed what the answer stage
receives. The two-call planner/answer architecture (§2) is unchanged: tracing adds **no** OpenAI
call and alters no query result.

### 22.1 Opt-in developer trace mode

`app/config/trace.py`, enabled only by `BIM_RAG_TRACE=1` (setting `bim_rag_trace`, default
`False`, not required in `.env`, never auto-enabled in tests or production). It is local terminal
observability and is **never** exposed through the public API. Built on the existing stdlib
`logging` setup — no new dependency.

Three record kinds, correlated by one request id per HTTP request, rendered as indented nested
lists, and passed through the existing `config.logging.redact_secrets` choke point:

- **API** (middleware in `api/app.py`) — request id, method, **route template**, status, and
  `elapsed_s`. The route template rather than the raw URL means query strings carrying user data are
  never logged; bodies, chat history, headers, and credentials never are either.
- **SQL** (`sql/dispatch.py`) — operation, exact parameterized SQL, exact/row counts, per-class
  histogram, `elapsed_s`.
- **RAG** (`rag/search.py`) — semantic query, kinds, `top_k`, threshold, parameterized vector SQL,
  retrieved count, similarity range, document-kind histogram, `elapsed_s`.

**Timings are always seconds (`elapsed_s`), never milliseconds.**

The no-leak property is structural, not cosmetic: a SQLAlchemy `after_cursor_execute` hook captures
the `statement` text **only and never reads `parameters`**, so values are never collected rather
than masked afterwards. Because the query embedding is a bound parameter, the vector SQL shows
`%(embedding_1)s` and the 1024-dim vector cannot appear. Verified live:

```text
[trace] sql
  operation: count_entities
  sql:
    - SELECT count(*) AS count_1
      FROM ifc_entities
      WHERE ifc_entities.source_model_id = %(source_model_id_1)s
        AND ifc_entities.ifc_class IN (%(ifc_class_1_1)s)
  exact_count: 205
  row_count: 205
  result_histogram: IfcDoor: 205
  elapsed_s: 0.0046
```

### 22.2 Compact result summary (amends §10, §11)

The answer-LLM evidence bounds (50/50/20) are unchanged and still apply. What changed is that the
bounded entity lists are no longer the whole story sent to the answer model:
`hybrid/evidence.build_result_summary()` adds a `result_summary` carrying the **exact total**, the
viewer match count/total, a truncation flag, and exact per-IFC-class counts.

`build_answer_payload()` includes it, and `prompts/answerer_v001.md` now instructs the model to lead
with the exact total and compact class counts and **not to enumerate individual components** — the
entity arrays are grounding/citation evidence and a *sample*, never a list to dump. The viewer match
identities (up to 2,000) are **never** sent to the LLM.

`result_summary` is additive on `QueryResponseEnvelope`, so a client that ignores it keeps working.

### 22.3 Sample-detail intent

New typed planner field `QueryPlan.sample_detail_requested` (default `False`), with planner-prompt
guidance that ordinary count/list/show/highlight/which questions are **not** sample-detail intent.
When true, `query/service.py` picks **one deterministic** entity from the ordered result set (before
`apply_bounds`, so the choice is over the full set) and attaches its bounded details read from the
database via the same centralized allowlist as the details endpoint — so the answer model cannot
invent a sample or a property value.

### 22.4 Viewer matches for every route

`orchestrator._ensure_viewer_matches()` runs in the orchestrator **before** `apply_bounds`, so
RAG/graph/hybrid results highlight their full match set rather than the 50 entities kept as LLM
evidence. SQL entity operations supply an identity-only set directly (spec_v003 §19.1); other routes
derive one from the full pre-bound evidence. `ViewerActions` gained `viewer_matches_total` and
`viewer_matches_truncated`; §14's stable-shape guarantee is preserved.

## 23. Task 15 Amendment — terminal output semantics (supersedes parts of §22.1)

Task 15 (`tasks/task15_done.md`) restructured terminal output into two layers:

**Always on (standard operational output, not gated on `BIM_RAG_TRACE`):**

- Every SQL/RAG/vector statement actually submitted to PostgreSQL prints once, as the exact
  parameterized SQL, labelled `[SQL]` or `[RAG]`. The `after_cursor_execute` hook emits on real
  submission only (planned-but-unsubmitted SQL cannot print) and never reads parameters, so values
  — including the pgvector embedding, which shows as `%(embedding_1)s` — structurally cannot leak.
- One bounded `[API error]` record per HTTP **400–599** response (request id, method, route
  template, status, `elapsed_s`; never bodies/history/credentials/paths/exception internals).
  Successful 2xx/3xx/304 calls print **nothing** — uvicorn's own access lines are raised above
  INFO too, so a successful call is fully silent.
- One `[OpenAI usage]` block per user question that made OpenAI calls: the sums of API-reported
  `prompt_tokens` / `completion_tokens` / `total_tokens` over every call for that question
  (planner, one repair, answerer). No block for zero-OpenAI requests; no cumulative counter; no
  cost estimate. Implemented as a call-log snapshot in `service._handle_question` with a `finally`,
  so a failure after a completed planner call still prints the usage actually reported.

**Opt-in (`BIM_RAG_TRACE=1`, unchanged otherwise):** the §22.1 summary records keep their timing,
counts, and histograms but **no longer repeat the SQL statements** — statements print exactly once
through the always-on layer (no duplication, verified by test).

---

## Task 16 amendment — Probe array + answerer relevance judge

Task 16 replaces the active-model planner's single exclusive `sql_plan`/`rag_plan`/`graph_plan`
choice with a bounded **probe array**, and turns the answerer into an explicit relevance judge.
Where this conflicts with the v005 exclusive-route/combination wording, this governs. Catalog,
`explain_general`, and `clarify` paths are unchanged; `clarify` is now a last resort (§10).

- **Planner (call 1)** emits `route=hybrid` + `probes[]` (`backend/app/llm/schemas.py::Probe`).
  Probe kinds: `sql`, `model_vocabulary`, `ontology`, `rag_entity`, `rag_relationship`, `graph`.
  Each probe has a unique `probe_id`, a `purpose`, a `facet`, and exactly one typed allowlisted
  plan. Bounds (centralized in settings): ≤10 total, ≤4 sql, ≤4 ontology+model_vocabulary, ≤4
  rag, ≤2 graph. The planner uses the fewest useful probes; a simple exact question may use one
  sql probe.
- **Execution** (`backend/app/query/semantic/probes/executor.py`): independent SQL probes run
  concurrently on their own sessions; embedding-backed probes run sequentially. One probe failing
  is an explicit per-probe partial failure and never zeroes the others. Semantic/RAG retrieval is
  threshold-free (see v004 amendment).
- **Independent evidence groups.** Analytical questions (e.g. circulation) preserve separate facts
  (stair count, class absence, lift-related names, egress coverage, semantic candidates) as labeled
  `ProbeEvidence` without forcing a single canonical-ID intersection/union. The legacy
  intersection/union combinations remain for questions that truly need them.
- **Evidence package** (`ProbeEvidence`, Task 16 §8): per probe — `authority` ∈ {exact,
  structured_candidate, semantic_candidate, general_context}, `coverage` ∈ {complete, bounded,
  unknown, unavailable, failed}, bounded candidate references (rank + provenance, similarity
  internal), exact counts uncapped. Distinct states (exact zero vs absent class vs absent field vs
  all-rejected vs failed vs bounded-sample) are never conflated.
- **Answerer (call 2)** returns structured relevance decisions: `used_probe_ids`,
  `rejected_probe_ids`, `viewer_probe_ids`, `model_evidence_sufficient`, `inference_used`,
  `inference_basis_probe_ids`, plus `used_general_knowledge`/`disclosed_conflicts`. Unknown probe
  ids are ignored with a bounded warning. Viewer highlights and follow-up session state are built
  from **accepted** entity-bearing probes only. `answer_basis` stays evidence-dependent: a
  hybrid-routed question answered only by one exact SQL count still reports `exact_sql`.
- Prompts are versioned `planner_v002` / `answerer_v002`.

---

## Task 17 amendment — Evidence groups + group-level answerer

Task 17 supersedes the Task 16 probe array for the active-model path with an evidence-group
pipeline. The Task 16 probe modules are retired; catalog / explain_general / clarify are preserved.

- **Stage 2 (call 1)** `RetrievalPolicyPlan` (`app/llm/schemas.py`): `facets[]` (facet_id, question,
  role_hint, semantic_query, needs_exact_structured/entity_rag/relationship_rag/graph) +
  `retrieval_policy`. The authoritative frozen policy = the union of facet needs
  (`validation.frozen_policy`); the declared `retrieval_policy` must equal it (repairable).
- **Stage 3** `resolution.resolve_facets` resolves each facet against the ontology + model
  vocabulary; it cannot add/remove/cancel a retrieval mode.
- **Stages 4-5** `hybrid/groups/builder.build_groups`: one group per class candidate and per
  queryable fact candidate, deduped by predicate signature; a value predicate whose count equals its
  class total is merged into the class group (§4). SQL verifies queryable groups (authoritative
  count); RAG enriches representative examples and forms bounded `entity_id_set` RAG-only groups; it
  never adds to a count. Never a mixed `IN(...)` group.
- **Stage 6** deterministic factual profiles + `groups/allocation.allocate_examples`: ≤50 detailed
  examples across groups, group-diverse round-robin, small high-priority direct groups included whole
  (the 9 stairs), summaries kept for zero-example groups.
- **Stage 7 (call 2)** group-aware answerer (`AnswerOutput` primary/supporting/context/rejected +
  viewer group id lists). `groups/decision.resolve_group_answer` validates ids (unknown/contradictory
  fail safe), derives `answer_basis` (one accepted exact group → exact_sql).
- **Stages 8-9** `groups/viewer.hydrate_accepted_viewer_identities`: complete uncapped identity
  hydration for accepted viewer groups; follow-up state stores accepted evidence only. Ambiguous
  concept totals are forbidden — an exact total is set only when a single exact primary group is
  accepted.
- Prompts: `policy_planner_v001` / `group_answerer_v001`.

## Task 23 amendment — Constraint-preserving orchestration

### 1. Group construction

`build_groups` now receives the planner's facets. A facet carrying an intent tree produces COMPOUND
groups — one per candidate result class, each resolving the facet's conditions in that class's
context — instead of independent class/value groups. Unconstrained facets keep the exact Task 17
behavior.

- A COMPOUND group whose predicate executed is `authority=exact`: it is the precise answer to the
  FILTERED question.
- COMPOUND groups are exempt from `_dedupe_full_class_value_groups`. Even when a filtered count
  equals the class total, that group is the user's actual request and must survive as the group
  whose scope the answer and viewer use.
- A group whose required conditions did not resolve is `coverage=failed`, non-queryable, and carries
  the reason.

### 2. Clarification instead of a widened answer

Before the answer call, the service checks the constrained facets. A facet is blocked only when
EVERY candidate result class failed to resolve its required conditions; if any candidate resolved,
the question is answerable and the answerer chooses between them as usual. A blocked facet returns a
clarification naming what could not be resolved, and logs an `unresolved_required_constraint`
failure record.

### 3. Answer and viewer share one scope

Viewer identities for a COMPOUND group are hydrated from the same predicate, via the same
`_entity_where` compilation, as the exact count — so the highlighted set and the counted set are one
set by construction, not by convention.

The answer payload carries `applied_conditions` per group and instructs the answer model to state
the interpretation and never report an unfiltered class total as the answer to a filtered question.

### 4. Preserved decisions

Exactly two principal LLM calls; query-only modality policy isolated from active-model semantic
data; SQL exact / RAG bounded; existing allowlists, source-model isolation, graph limits, read-only
behavior, and vocabulary/index caches all unchanged. No additional router, resolver, verifier,
judge, or replanning call was added, and no late answerer-side reconstruction of a discarded
intersection exists.

### 5. Known limitation — graph scope

`retrieval_policy.graph` and `retrieval_policy.rag_relationship` are recorded and logged but are not
executed by the Task 17 group pipeline; graph traversal remains reachable only through the legacy
single-path route. Scoped graph seeding therefore has nothing to scope in the active pipeline today.
This is a pre-existing Task 17 gap, not a Task 23 regression. The mechanism a scoped traversal needs
already exists — `select_scope_entity_ids` returns exactly the constrained seed set — so wiring
graph execution into the group pipeline is the only remaining work.
