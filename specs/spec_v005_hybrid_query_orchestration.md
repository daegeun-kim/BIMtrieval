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


## Task 27 amendment — stage-boundary repairs in the experiment2_v4 pipeline

The Task 26 pipeline (deterministic requirement ledger → always-parallel recall → one typed
logical plan → ten-layer validation → contract-driven compilation → one execution per part →
answer packet → claim-citing answer) is unchanged in shape: same stages, same typed algebra, same
three configured roles (binder `gpt-5.4-nano` medium, correction `gpt-5.4-nano` high, answerer
`gpt-5.4-mini` low), two LLM calls for a normally-answered question and at most one correction.

Task 27 repaired the stage that OWNED each recorded failure. No downstream stage compensates for
incorrect upstream state, and no correctness gate was weakened.

### 1. Ledger construction (`binding/ledger_v2.py`, `binding/spans.py`)

- **Coordinated peer subjects.** A content run is split on `,`, `;`, `and`, `or`, `/`, `&`, `+`, so
  a list of nouns is a list of requirements. Language asking for ONE combined figure (`total`,
  `combined`, `altogether`, `together`, `overall`, `sum`) makes the peers TARGETs of the SAME part —
  one union. Without it they become independent requests, each with its own part hint (`P1`,
  `P1_2`, `P1_3`) and its own target. Previously the second noun of any list became a filter on the
  first, so a coordinated count lost every subject after the first one.
- **Requested-output markers.** A run consisting only of words that name "whatever you have"
  (`details`, `information`, `properties`, `attributes`, `data`, `values`, `overview`) is a
  non-required OUTPUT requirement, never an occurrence target. Verbs of selection (`pick`,
  `choose`, `select`, `fetch`, `identify`) joined the structural vocabulary.
- **Parts with no subject merge left.** After the skeleton is built, a part with no TARGET
  requirement hands its requirements to the previous part. "Pick a sample X and show me its
  details" is therefore ONE part: one sample operation, one occurrence target, limit one, and the
  requested report fields.
- **No duplicate unresolvable fragment.** A requested-output phrase overlapping a span already
  typed as material (a floor reference, a quoted value, a comparison) is not emitted a second time.
  And after model resolution, an unresolvable FILTER requirement whose every token is named by a
  sibling's resolved capability is discharged by that sibling: it becomes non-required with a note
  naming the binding that represents it. A resolved field/value filter discharges the COMPLETE
  qualifier phrase it represents.
- **Non-English normalization** (`binding/multilingual.py`). One shared lexicon of function words
  and everyday subject nouns for Swedish, Dutch, German, and Norwegian/Danish, diacritic-folded.
  Function words join the ledger's structural vocabulary; subject nouns map onto the English token
  every manifest label is derived from; whole-artefact nouns join the scope-reference vocabulary so
  building-wide topic language stays context, never a filter, in every supported language.

### 2. Recall (`binding/recall.py`, `binding/concept_vectors.py`)

- **The dense channel actually runs.** `get_concept_vector_index` called `embed_texts`, a method
  the backend's `EmbeddingService` has never had; the bare `except` around it reported
  `dense_available: false` for every recorded request. `concept_vectors.batch_embed` now resolves
  whichever batch API the service exposes (`embed_texts`, else `embed_documents`, else per-text
  `embed_query`).
- **An exact name match is its own channel.** Fusion combines RANKS, so an exact label/alias match
  that tied with an unrelated value-channel hit lost on alphabetical id order. `_exact_channel`
  contributes it separately.
- **Two stable ordering passes, never an eligibility change.** A concept offered for the use the
  requirement's role NAMES outranks one admitted through a related use (a class before a field for
  a target slot); then a field applicable to the part's likely target — read from the target
  requirement's own fused list — outranks same-named fields for incompatible classes. A field for
  the wrong class is still offered, just not first.
- **Descriptive outputs reach the derived profiles.** An OUTPUT requirement admits a
  `derived_profile` whose only permitted use is `target`, so "a summary", "the circulation of this
  building", "made of" resolve instead of reporting `not_representable` while the concept that
  answers them ranked first.
- **Qualifier value linking.** When a phrase's head noun resolves to a class, the qualifier tokens
  are looked up individually through the same authoritative value-linking stage, which may then
  propose a typed target-plus-filter plan. When an exhaustive stored-value scan matches a qualifier
  nowhere in the model, the requirement records `value_scan_absent`, and an `unavailable`
  disposition for it is honest rather than a silently dropped condition.

### 3. Binder bookkeeping is done in code (`binding/plan_normalize.py`)

`node_id` is a LOCAL handle and `semantic_id` is an exact manifest id; nothing distinguished them,
so the binder wrote semantic ids into `node_id`, where the 24-character bound truncates them
mid-token (`prop:Pset_WallCommon.IsU`, `agg:count_stairs_plus_r{`). Valid plans then failed filter
provenance and lexical coverage for conditions that were in fact bound.

Before validation runs, deterministically and with no model call:

1. every node takes a canonical handle from its position and kind — `t1`, `f1..fn`, `s1`, `v1..vn`,
   `g1`, `a1`, `o1`, and `p1..pn` for reported projections;
2. each disposition's node references resolve onto those handles by exact match against the handle,
   the original node id, or the node's semantic id;
3. a reference matching nothing is repaired ONLY when the mapping is unique — the requirement's
   role names one node kind and the part holds exactly one node of it. Two candidates is ambiguous,
   nothing is guessed, and validation fails safely;
4. duplicate part ids are made unique, and a disposition with no `part_id` attaches to the only
   part when there is only one.

No semantic id, operator, value, target, or disposition kind is ever changed. The binder prompt
states the two identifier kinds explicitly, carries a small set of schema-generic structural shapes
(no benchmark question, model fact, or expected answer), and ends with a mechanical self-check. The
correction input names the exact rejected string per failing node with valid ids of the same kind
that may replace it.

### 4. Validation (`binding/validate_v2.py`)

Accepts a semantically valid plan when provenance is mechanically clear; still rejects a dropped
requested condition, an invented narrowing filter, an incompatible field, and a silently broadened
target.

- Union members contribute to the requirements they represent: the primary target and every union
  peer cover their own words, whichever member is primary.
- Projections are addressable nodes (`p1..pn`), so a disposition for a requested OUTPUT may name
  the projection that reports it.
- Lexical coverage is checked through a word's English equivalent as well as the word itself, so an
  inflection, a synonym, or another supported language cannot invalidate a valid binding.
- All filter-provenance checks compare normalized local node ids.
- An `unavailable` disposition is accepted for a requirement whose exhaustive value scan found
  nothing, and still rejected for one that resolved against the manifest.

### 5. Execution and evidence (`binding/compile_v2.py`, `binding/execute_v2.py`)

- **Multi-valued array distribution.** `json.material_name` and `json.classification_field` have no
  scalar path, so a material distribution failed dry compilation outright. An `array_element` group
  spec unnests the array; buckets count DISTINCT objects, the covered figure is the objects with
  any value (never the bucket sum), and the viewer highlights only the objects the buckets describe.
- **Derived floor counts.** `count:floor_levels` and `count:occupiable_floor_levels` are attached at
  manifest parse time from the artifact's own floor derivation — no re-ingestion, no change to the
  integrity hash. Each is an ordinary selectable target answering a scalar question with ZERO
  database statements, and refuses to be filtered. The binder no longer enumerates band ids in a
  union (the shape that produced an invented band id).
- **Thematic profiles describe their theme.** A theme's relevant structured subjects are the classes
  of the objects its bounded retrieval actually returned, reported with their model counts beside
  the retrieved excerpts. A profile's evidence search is restricted to entity documents, because
  relationship text records no subject class. When nothing clears the primary similarity threshold
  the part is PARTIAL with an explicit limitation — the closest recorded objects, never a claim that
  the theme is absent from the real building.
- **A vector-index miss is never absence.** When a nearest-neighbour search returns ZERO rows, the
  same bounded query is repeated exactly with index scans disabled for that statement, and the
  interpretation notes record it. A healthy index never returns an empty answer for a non-empty
  scope, so this costs nothing once the index is sound.
- **Catalog schema.** Catalog display metadata lives in `source_model_catalog_entries`, joined to
  `ifc_source_models` by `source_model_id`. Selecting `display_name` from the source-model table
  raised `UndefinedColumn` and turned every catalog question into a pipeline error.

### 6. User-facing answers (`binding/phrasing.py`, `binding/answer_validation_v2.py`)

One rewrite table turns internal sentences into plain language, and it is applied where the text is
CREATED — `add_limitation`, coverage reasons, interpretation notes, known/unknown parts — so the
same wording reaches the answerer, the deterministic fallback, and the trace. Property names are
humanized (`prop:Pset_WallCommon.FireRating` → "fire rating").

`grounded_answerer_v002` is rules only, with no examples. Answers lead with the direct result in
ordinary language, say "this model", describe an exact absence as no such objects being present,
describe partial data as what is recorded and what remains unknown, never equate "no value recorded"
with a false real-world property, and omit limitations when an exact result has none.

Deterministic answer validation moved in both directions, because the recorded run failed both ways:

- **Less strict about citations.** A claim is checked against every citable value of the fact it
  names — a grouped extremum carries a bucket key AND a count — and an id that exists in the packet
  is accepted whatever claim kind carries it. Six recorded answers were discarded over bookkeeping
  of this kind and replaced by the fallback.
- **Stricter about prose.** An answer is rejected when it uses internal vocabulary (target class,
  match/matches, zero match, predicate, coverage, semantic id, packet, an internal status label, or
  a literal semantic identifier), when it sets `disclosed_limitation` without a recorded limitation,
  when it adds uncertainty to an exact unqualified result, or when it says information was not
  provided while the results contain it.

The deterministic fallback follows the same rules for exact, zero, partial, and unavailable results;
the pipeline's own unavailable and clarification prose passes through the same rewrite.

### 7. Preserved decisions

Configured models, reasoning efforts, and roles unchanged. No added LLM call, agent loop, router,
judge, model-written SQL, retrieval store, framework, ontology, or database. Binder projection
still the compact complete universe under the same USD request budget. No exact-query fallback,
expected-count rule, or model-specific behavior exists.

---

## Task 28 amendment — experiment2_v5: semantic intent and reliable pipeline transfer

The Task 26/27 pipeline computed correct answers to questions it had quietly changed. Every
deterministic layer proved the plan was internally well formed — real ids, compatible uses,
applicable subjects, compilable nodes — and none proved the plan still expressed what the user
meant. Task 28 is the systemic repair: user meaning is resolved ONCE, made authoritative, and
carried intact through grounding, execution, answer, and viewer selection. Individual recorded
failures were not patched, and no benchmark wording, expected value, model fact, IFC name, or
semantic ID entered code, prompts, or tests.

The typed plan, semantic access contracts, deterministic compilation and execution, result states,
and grounded answer design are preserved unchanged.

### 1. One semantic planning boundary, two cheap calls

```text
complete conversation
    -> semantic intent resolver          (planning call 1)
    -> normalized standalone request     (authoritative from here on)
    -> deterministic backend recommendation
    -> grounding planner                 (planning call 2)
    -> validated typed plan
    -> deterministic execution
    -> grounded answer and viewer filter
```

Both planning calls reuse the existing cheap planning configuration: the resolver defaults to the
binder model and effort (`intent_model` / `intent_reasoning_effort` override it, and
`intent_max_output_tokens` is 4,000 because its output is a small typed object). No advanced
planning model, router, runtime judge, agent loop, or provider was added. Neither call writes SQL.

A normally-answered question is **three** LLM calls — resolve, ground, answer. One budget-gated
mechanical correction may still fire, so no request exceeds four. The resolver is tracked as its
own budget role, so cost is attributable per successfully answered request including correction and
fallback work.

### 2. Semantic intent resolver (`llm/schemas_v5.py`, `query/binding/intent.py`)

Runs BEFORE the ledger and recall. It receives the current message, the complete conversation in
original order, the active model identity and the minimal session facts needed to resolve a
reference, and any pending clarification. It receives **no manifest, no projection, and no
database**, which is why it is cheap despite carrying every turn — and why anything backend-shaped
in its output can only have been invented.

`serialize_conversation` passes every available turn intact: the v4 20-turn window and the
400-character-per-message truncation are gone from this path, and the API request cap moved from 20
to 200 turns as a request-size guard rather than a context window. Only an explicit provider
character budget may withhold a turn; when it does, the oldest turns go, the count and reason are
recorded in the trace and surfaced as a warning, and the current message is never the turn dropped.

`ResolvedIntent` is model-neutral and compact: the normalized standalone request, language, active
topic, one part per independently answerable request (with its operation, the user own words for
its subject, the characteristics requested for reporting, and whether it is highlightable), typed
constraints (attribute, comparison, spatial, relationship, grouping, previous result, selection —
each with negation and OR grouping), visualization intent, superseded earlier constraints,
structured unresolved slots, whether this message resolves a pending clarification, and per-element
turn provenance.

`sanitize_intent` enforces the contract deterministically: a manifest-style identifier, an IFC or
property-set name, or a query fragment that the user did not themselves type is a violation, as is
a constraint or slot naming a part that does not exist or provenance past the end of the
conversation. `repair_intent` fixes only structurally impossible bookkeeping — an orphaned
constraint is REATTACHED, never deleted, because deleting a condition is the defect, not the fix.

`deterministic_intent` builds the same typed object with no provider, so an absent, unavailable, or
contract-breaking resolver degrades to reading the current message verbatim rather than abandoning
the request. It finds less; it invents nothing; the degradation is recorded.

The resolved intent is preserved in the permanent query trace under `resolved_intent`, with its
provenance, any contract violations, and the conversation diagnostics.

### 3. Stateful conversation, not standalone reparsing

The resolver reads the raw conversation; every stage after it reads the resolved request. Pending
clarification state and the last resolved intent live in the existing `SessionState` (typed,
process-local, minimal) — no memory service, summarizer, or database was added. A clarification
answer completes the pending intent instead of being parsed as an unrelated new request.

### 4. Ledger and recommendation subordinate to resolved intent

`build_ledger_from_intent` is the active path. Requirements are phrase- and intent-level: one per
part target, per requested output, and per constraint, each carrying the `intent_ref` handle of the
meaning it represents. Grammatical role comes from the resolver typed constraint kind, not from
word position — so a coherent concept is never split into independent word requirements and topic
context can never become a filter. A positional floor condition becomes a SCOPE resolved through
the derived bands; any other spatial condition becomes a FILTER that must resolve against a real
capability or be reported unavailable, never forced into a band it does not name.

`build_ledger_skeleton` (the lexical Task 26/27 path) remains as a deterministic retrieval aid and
audit artifact for the no-resolver path. It is no longer authoritative for topic, target, or role.

Recall itself is unchanged in mechanism — all channels, RRF fusion, value linking, dense
similarity, role compatibility, and the ordering pass — but it now runs over intent-derived
requirements, so its recommendations are phrase- and intent-level and aware of the intended target.

### 5. Grounding planner (`llm/grounding_context_v5.py`, `grounding_planner_v001`)

The v4 binder, narrowed. It receives the immutable normalized request, the typed intent, the
structured requirements, bounded recommendations, exact value matches, and the same compact
capability projection as its cacheable stable prefix. It does **not** receive the conversation:
that was already resolved, and re-sending it invites reinterpretation of settled meaning.

Its only job is to select supported semantic IDs and assemble the existing typed logical plan,
mapping every requested target, operation, constraint, scope, output, and visualization request to
a plan contribution or an explicit unsupported/ambiguous disposition. It may not reinterpret the
conversation, replace the requested topic with a nearby backend concept, silently add or remove
constraints, treat a backend limitation as uncertainty, or invent anything.

The one corrective call is unchanged in budget and scope and receives the SAME intent object
unchanged: a repair may change the plan, never what the user meant.

### 6. Backend-justified, persistent clarification (`query/binding/clarification.py`)

The gate verifies structured evidence rather than trusting a model-written question. Exactly two
things justify asking: a BLOCKING unresolved slot in the resolved intent, or a required requirement
the backend itself resolved to materially different plausible readings. Anything else is refused,
recorded in the trace as `rejected`, and the request continues to whatever it can honestly answer.

In particular, this model not recording the requested fact is a SOURCE LIMITATION and returns the
correct unavailable or partial result with an explanation — it is never converted into a question
that asks the user to supply data. Ordinary language, breadth, needing several capabilities, and a
safe returnable part are likewise never grounds to ask.

Only the smallest missing decisions are asked (at most two slot questions). A justified
clarification persists as a `PendingClarification` carrying the blocked request and its slots, so
the next turn completes the same plan, and a decision the user already supplied is never requested
twice.

### 7. Semantic preservation before execution (`query/binding/preservation.py`)

A deterministic boundary check between resolved intent and grounded plan, run before compilation
and again after any correction. Its verdicts fold into the existing per-part gates, and every part
is re-gated afterwards, so a preservation failure cannot coexist with a `ready` verdict:

- `INTENT_PART_DROPPED` — an independently answerable request produced neither a plan part nor an
  explanation of why this model cannot serve it;
- `INTENT_TARGET_DROPPED` / `INTENT_OUTPUT_DROPPED` — a subject or a requested detail is unbound
  and undisposed;
- `INTENT_CONSTRAINT_DROPPED` — a condition, scope, grouping, or relationship reached no
  requirement or was left unaccounted; an explicit unavailable/ambiguous disposition is NOT a drop,
  silence is;
- `INTENT_CONSTRAINT_INVENTED` — a filter node whose cited requirement is not a stated condition,
  or a part applying more narrowing conditions than the request states. A multi-word subject
  licenses at most ONE qualifier filter (a phrase can decompose); a bare noun licenses none;
- `INTENT_VISUALIZATION_DROPPED` — the request asks for matching objects to be shown and no part
  selects a viewer set;
- `UNRESOLVED_SLOT_EXECUTED` — a blocking slot coexists with an executable part. Deliberately NOT
  correctable: the missing decision is the user's, and guessing it is not a repair.

Correctable preservation issues feed the single existing corrective call. Meaning is never repaired
here: no different intent is ever inferred to make a plan executable.

### 8. Execution preserves information

Execution is unchanged and remains backend-authoritative: the LLM selects only typed semantic
operations, the compiler chooses parameterized access methods the semantic contract already
authorizes, and applicability, coverage, direction, model isolation, and completeness determine
exact / zero / partial / ambiguous / unavailable. An unsupported optional enrichment marks only
itself unknown and downgrades the part to partial while the supported core figure survives;
independent valid parts survive the failure of another.

### 9. One result contract for text and visualization

Viewer hydration now runs BEFORE the answer is written, so the packet names exactly the parts the
viewer will show. The v4 assumption that exactly one part is the visualization authority is gone:
`_visual_part_ids` derives the shown parts from the resolved visualization intent (all requested
sets, the primary one, or none) and the plan, and `hydrate_viewer_v2` combines the exact identities
of every such part, deduplicated, under one shared cap, with truncation disclosed per part rather
than inferred from deduplication. `part_global_ids` retains the per-part identities, so the
delivered text, result summary, viewer class counts, highlighted ids, and trace can be checked to
agree; the trace records them under `viewer_parts`.

Two safety rules survive: a zero, unavailable, or non-highlightable part contributes nothing and
can never cause an unrelated broader set to be shown; and a contextual base set is used only when
no requested set exists at all, so a broader stand-in never mixes into exact identities.

The answer packet carries the RESOLVED request rather than the raw question, so the answerer cannot
describe a different question from the one that was grounded. Answer validation gained two
stable-identity checks alongside the existing claim/value comparison: naming a `part_id` that was
never produced is rejected, and leaving an answered part of a multi-part request undescribed is
rejected. The deterministic fallback uses the same authoritative facts and limitations.

### 10. Rule-only prompts

The active roster is four prompts, all declarative rules, field definitions, and output-schema
instructions only — no examples, demonstrations, sample conversations, sample queries, sample
plans, benchmark wording, expected outputs, or model-specific facts:

| role | prompt |
| --- | --- |
| planning call 1 | `intent_resolver_v001` |
| planning call 2 | `grounding_planner_v001` |
| conditional repair | `correction_v003` |
| final answer | `grounded_answerer_v003` |

`binder_v003`, `correction_v002`, and `grounded_answerer_v002` were removed with the pipeline they
served; all three carried worked examples, placeholder plan shapes, and literal IFC class and
property-set names. `tests/binding/test_v5_preservation.py` enforces the contract on every prompt
in `ACTIVE_PROMPT_VERSIONS`: no example markers, no manifest-style identifier or IFC/Pset name, and
no quoted natural-language phrase.

### 11. Cost and call accounting

The resolver is priced as its own role through the existing versioned registry. Its input is the
prompt plus the conversation only — never the projection — so it is small and does not grow with
the model:

| conversation | input tokens | resolver cost (`gpt-5.4-nano`, 400-900 output tokens) |
| --- | ---: | --- |
| single turn | ~1,460 | $0.00079 - $0.00142 |
| 3-turn follow-up | ~1,540 | $0.00081 - $0.00143 |
| 12-turn conversation | ~2,680 | $0.00104 - $0.00166 |

Against the Task 27 measured mean of $0.008532/query, the added planning call is roughly 10-20% of
a request. It is deliberately not offset in this task: whether fewer corrections and fallbacks
recover it is a question for the next billed run, which Task 28 does not perform.

### 12. Preserved decisions

Typed logical algebra, semantic access contract, v002 manifest and its compact projection,
compiler adapters, result variants, ten validation layers, the USD request budget, the permanent
query trace, and the public query API are unchanged. No second query endpoint, feature flag,
duplicate pipeline, new database, ontology framework, ingestion change, conversation summarizer,
external memory, runtime evaluator, or agent architecture was added. No LLM generates SQL or
overrides deterministic execution evidence, and no correctness gate was weakened.
