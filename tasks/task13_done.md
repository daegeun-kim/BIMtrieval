# Task 13: Backend Observability, Complete Viewer Matches, and Component Detail APIs

## Prerequisites and execution order

Require:

```text
tasks/task09_done.md
tasks/task10_done.md
tasks/task11_done.md
tasks/task12_done.md
specs/spec_v002_query_architecture.md
specs/spec_v003_sql_query_path.md
specs/spec_v004_rag_query_path.md
specs/spec_v005_hybrid_query_orchestration.md
specs/spec_v006_frontend_application.md
```

Complete this task before starting Task 14. This task changes the Poetry/FastAPI backend and its
OpenAPI contract only. Do not modify frontend behavior here.

## Objective

Extend the existing read-only backend so that:

1. optional developer tracing clearly shows API, SQL, RAG, and result-summary activity;
2. aggregate/count questions return matching object identities for viewer highlighting;
3. exact counts, viewer identities, and LLM evidence use separate appropriate limits;
4. chat answers receive compact summaries rather than long component listings;
5. the frontend can deterministically request truthful instance/type/family details and highlight
   groups without an LLM call.

Preserve the current SQL/RAG/graph/hybrid architecture and source-model isolation. The database is
the only connection between the independent ingestion and backend applications.

## 1. Developer trace mode

Add a backend setting controlled by:

```text
BIM_RAG_TRACE=1
```

It must be disabled by default. It is local terminal observability, not a client response feature.
Do not require this variable in `.env` and do not enable it automatically in tests or production.

When enabled, print concise, readable records for the following. Prefer an indented/nested list or
similarly scannable structure over dense one-line JSON.

### API record

For every backend endpoint call, include:

- request/correlation ID;
- HTTP method and route path;
- response status;
- elapsed time in **seconds**, not milliseconds.

Do not log request bodies, chat history, credentials, authorization headers, query strings that may
contain user data, or filesystem paths.

### SQL record

For SQL-path operations, include:

- operation name;
- the exact parameterized SQL statement executed;
- returned exact count and/or row count;
- elapsed time in seconds;
- a compact result histogram by IFC class, such as `IfcDoor: 5, IfcWindow: 3`.

Never print parameter values, including sanitized or masked parameter values. Never interpolate
values into the SQL shown in the terminal.

### RAG record

For vector retrieval, print a nested record containing:

- semantic query text;
- requested document kinds;
- `top_k` and similarity threshold;
- parameterized vector SQL operation/statement;
- retrieved document count;
- similarity-score range when results exist;
- compact retrieved IFC-class/document-kind histogram;
- elapsed time in seconds.

Never print the embedding vector, vector literal, database URL, API key, full canonical JSON, or a
long list of entity/relationship IDs. Hybrid/graph operations should produce the corresponding
bounded sub-operation records under one request ID.

Use ordinary structured logging facilities rather than scattered unconditional `print` calls.
Tracing must not alter query results or introduce extra OpenAI calls.

## 2. Separate exact-count, viewer, and LLM limits

Implement these independent limits:

```text
Exact database count: no artificial application row cap
Viewer match identities: maximum 2,000 per response
LLM evidence entities/documents: maximum 50
```

Requirements:

- `COUNT_ENTITIES` and other aggregate questions must retain the exact database count.
- If an aggregate has entity filters, run a deterministic, identity-only retrieval for the same
  filtered set so the viewer can highlight matching objects.
- Identity-only retrieval should return only fields required by the viewer/API contract, primarily
  active-model-scoped entity ID/GlobalId and minimal class identity.
- Apply a stable explicit ordering before the viewer cap. If more than 2,000 match, return the first
  2,000 deterministically plus `viewer_matches_total` and `viewer_matches_truncated=true`.
- Do not send all viewer identities or full object details to the answer LLM. Keep its evidence at
  50 and supply compact aggregate/class summaries separately.
- Do not change the exact count merely because viewer or evidence results were truncated.
- Every query remains scoped by `source_model_id` and uses parameterized SQL.

For natural-language plural `wall`/`walls`, the SQL entity-class mapping must include both
`IfcWall` and `IfcWallStandardCase`. Keep other class expansions explicit and testable; do not use
unsafe fuzzy class-name matching.

Ensure viewer actions are produced for matching identities from count/aggregate questions just as
they are for list questions. For example, “How many doors are there?” must return the exact count
and a select/fit action for the matching rendered doors, with the response indicating any viewer
truncation.

## 3. Compact answer/result contract

Extend the typed response contract compatibly so Task 14 can render an answer without listing every
retrieved object. Provide deterministic fields equivalent to:

```text
result_summary
  exact_total, when applicable
  returned/viewer match count
  truncated flag
  compact counts grouped by IFC class
viewer match GlobalIds through the existing viewer-action mechanism
bounded evidence retained for grounding/debug UI
```

The answer-generation context should emphasize the exact result and compact summary. In normal
SQL, RAG, graph, and hybrid responses, instruct the answer layer not to enumerate individual
components unless the user explicitly asks for a sample or a specific component’s details.

Add a typed planner/output indication for explicit sample-detail intent. A query such as “pick a
sample door and show me the details” may select one deterministic matching entity and include its
bounded details. Do not treat ordinary count/list/show/highlight requests as sample-detail intent,
and do not let the LLM invent a sample not returned by the database.

Preserve existing evidence internally and in the bounded API contract for grounding and debugging;
Task 14 will change its default visual presentation.

## 4. Truthful component-detail endpoint

Add a narrow read-only endpoint using the existing route conventions, recommended:

```text
GET /api/models/{source_model_id}/entities/{global_id}/details
```

It must:

- scope every lookup to `source_model_id` plus exact GlobalId;
- make no LLM or embedding call;
- return 404 for unknown/cross-model identity without revealing other-model existence;
- return only an allowlisted, bounded schema rather than arbitrary canonical JSON;
- expose enough identity metadata for an instance detail panel and deterministic group actions.

Return available values from the current IFC-derived database, including as applicable:

- instance: GlobalId, IFC class, name, description, object/predefined type, tag, storey/elevation,
  material names, selected quantities/dimensions, and bounded selected property values;
- explicit IFC type: name, GlobalId, IFC class, predefined type, when `canonical_json.type` or its
  established equivalent contains it;
- explicit family: value plus source property-set name and property name, only when an allowlisted
  family property exists in stored IFC property sets;
- availability flags for instance, same-type, and same-family actions.

Keep the property/quantity allowlist explicit, centralized, and bounded by count/string length.
Never return raw canonical JSON, relationship expansion, geometry, vector content, prompts, SQL,
paths, or credentials.

### Type/family semantics

These rules are mandatory:

- Instance identity is always available for a valid entity.
- Type is available only when the source IFC explicitly supplied type information stored by the
  existing ingestion pipeline.
- Family is not a universal IFC concept. It is available only from an explicit normalized
  allowlist of family-like property names in stored property sets.
- Return the family property’s source property-set/property names for transparency.
- Never infer type or family from the instance name, naming patterns, IFC class, material, or LLM.
- The current Schependomlaan file has no useful `IfcRelDefinesByType` data; unavailable type/family
  is therefore a valid expected result, not an error.
- The existing ingestion already stores type data when present and all property sets. Do not add a
  migration, re-ingest the IFC, or import ingestion/IfcOpenShell code for this feature.

## 5. Deterministic instance/type/family match endpoint

Add one typed read-only endpoint, recommended:

```text
POST /api/models/{source_model_id}/entities/highlight-group
```

Request:

```json
{
  "selected_global_id": "...",
  "scope": "instance | type | family"
}
```

Response must contain:

- selected scope and truthful availability;
- exact total matches;
- up to 2,000 deterministically ordered matching GlobalIds;
- truncation flag;
- compact IFC-class summary;
- bounded reason when a type/family action is unavailable.

Matching rules:

- `instance`: the selected entity only;
- `type`: prefer exact explicit type GlobalId; if the IFC provides an explicit type name without a
  GlobalId, use exact normalized stored type identity within the same model;
- `family`: exact normalized explicit family value from the allowlisted property mechanism; keep
  the match tied to explicit stored family data, never a name-derived guess.

This endpoint must not create a chat message, call an LLM, create an embedding, or mutate session
history. It exists solely for the component-panel buttons in Task 14.

## 6. OpenAPI, compatibility, and tests

Update FastAPI schemas and OpenAPI for all new/changed response fields and routes. Preserve current
routes compatibly where possible so the existing frontend remains operational between Task 13 and
Task 14.

Add tests covering at minimum:

- trace disabled by default and enabled only by `BIM_RAG_TRACE=1`;
- API elapsed time uses seconds;
- SQL trace shows parameterized SQL but no parameter values;
- RAG nested trace fields and no vector output;
- no secrets, canonical JSON, long ID lists, request bodies, or chat history in logs;
- exact count independent from 50-evidence and 2,000-viewer limits;
- aggregate/count question produces viewer identities/actions;
- deterministic truncation and total reporting above 2,000;
- plural walls maps to both IFC wall classes;
- compact summaries by IFC class;
- explicit sample-detail intent versus ordinary queries;
- details endpoint allowlist, missing optional type/family, and cross-model isolation;
- explicit type/family extraction from synthetic stored canonical JSON fixtures;
- no name-based type/family inference;
- instance/type/family group matching, disabled/unavailable results, limits, and ordering;
- zero LLM calls for details and group endpoints;
- OpenAPI accuracy and the full existing backend regression suite.

Normal tests must use mocked providers and must not call live OpenAI. Live database validation is
read-only.

## Required validation

From `backend/` run the established Poetry commands, including:

```powershell
poetry run ruff check app tests
poetry run pytest -m "not live"
```

Then perform bounded read-only local checks with tracing both off and on. Confirm:

- existing health/readiness/query behavior remains valid;
- a door count gives the exact count and matching viewer GlobalIds/actions;
- all-wall retrieval uses both wall classes and returns all matches if below 2,000;
- the current model’s type/family fields honestly report unavailable where absent;
- details/group calls make no OpenAI call;
- all five BIM tables, catalog tables, and vector metadata are unchanged.

Do not run ingestion, model conversion, vector generation, or a standalone live OpenAI test.

## Prohibited actions

- Do not modify the frontend in this task.
- Do not import or modify `ingestion`/`bim_rag` code.
- Do not parse IFC or regenerate the viewer artifact.
- Do not migrate/write/drop/truncate database data or vectors.
- Do not add PostGIS.
- Do not expose SQL/trace details through public API responses.
- Do not log SQL parameter values, embedding vectors, secrets, or full retrieved records.
- Do not remove all safety limits; keep the separate limits defined above.
- Do not infer family/type from names or use an LLM for deterministic component details/actions.

## Acceptance criteria

1. Trace mode is useful, readable, opt-in, timed in seconds, and does not leak protected data.
2. Count/aggregate queries return exact totals plus matching viewer identities/actions.
3. Exact count, viewer matches, and LLM evidence obey their independent limits.
4. Normal answer context uses compact summaries rather than long component enumeration.
5. Details and group endpoints are read-only, active-model-scoped, deterministic, and LLM-free.
6. Type/family data is shown only when explicitly stored by the IFC pipeline.
7. Existing backend behavior and tests remain valid.
8. Database rows, vectors, model artifacts, and frontend files are unchanged.

## Completion report

Rename this file to `tasks/task13_done.md` only when complete. Append:

- backend files/routes/schemas changed;
- trace examples with fake/non-sensitive values;
- exact/viewer/evidence limit behavior;
- aggregate highlighting and wall-class mapping results;
- component detail/group semantics and current-model availability results;
- OpenAPI and test results;
- before/after database counts and vector metadata;
- explicit statuses:

```text
Opt-in backend tracing: VALIDATED
Aggregate viewer identities: VALIDATED
Exact/viewer/evidence limits: VALIDATED
Compact result summaries: VALIDATED
Component detail endpoint: VALIDATED
Instance/type/family group endpoint: VALIDATED
Backend regression: VALIDATED
Database/vector/frontend state: UNCHANGED
```

---

# Completion Report (2026-07-15)

All six sections implemented, tested, and validated read-only against the live database.
No frontend file, ingestion module, database row, vector, or model artifact was modified.

## Backend files / routes / schemas changed

**New**

```text
app/config/trace.py                    opt-in trace facility (records, capture, rendering)
app/query/sql/class_aliases.py         explicit IFC entity-class expansion
app/viewer/details.py                  centralized allowlists + truthful type/family extraction
tests/test_trace_mode.py                             18 tests
tests/test_entity_details.py                         22 tests
tests/query_hybrid/test_viewer_limits.py             24 tests
tests/query_sql/test_dispatch_viewer_identities.py    6 tests
```

**Changed**

```text
app/config/settings.py        + bim_rag_trace (False), + max_viewer_match_ids (2000)
app/api/app.py                + _trace_requests HTTP middleware
app/api/routes/models.py      + GET  /api/models/{id}/entities/{global_id}/details
                              + POST /api/models/{id}/entities/highlight-group
app/api/schemas/models.py     + DetailValue, InstanceDetails, TypeDetails, FamilyDetails,
                                DetailAvailability, EntityDetailsResponse, HighlightScope,
                                HighlightGroupRequest, HighlightGroupResponse
app/api/schemas/response.py   + ResultSummary, SampleDetail; + envelope.result_summary
app/viewer/actions.py         + viewer_matches_total, viewer_matches_truncated
app/query/sql/entities.py     + select_viewer_identities, count_by_class, get_entity_canonical,
                                get_ifc_class_for_global_id, match_instance,
                                match_by_type_global_id, match_by_type_name, match_by_family
app/query/sql/dispatch.py     + trace wrapper, + viewer identity attachment
app/query/rag/search.py       + RAG trace wrapper
app/query/hybrid/schemas.py   + viewer_*/class_histogram/sample_detail on EvidencePackage
app/query/hybrid/evidence.py  + build_result_summary, build_sample_detail; payload gains summary
app/query/hybrid/orchestrator.py  + _ensure_viewer_matches/_finalize_viewer; settings threaded
app/query/service.py          + sample-detail attach, + result_summary on the envelope
app/llm/schemas.py            + QueryPlan.sample_detail_requested
app/llm/translate.py          + expand_entity_classes applied centrally
app/llm/prompts/planner_v001.md    sample-detail intent rules; corrected viewer-intent guidance
app/llm/prompts/answerer_v001.md   "summarize, do not enumerate" + sample-detail exception
tests/test_viewer_actions.py, tests/test_openapi_contract.py, tests/test_settings.py,
tests/test_no_openai_deterministic.py                extended
```

## 1. Trace examples (live, non-sensitive)

`BIM_RAG_TRACE` is **off by default**, absent from `.env`, and never enabled in tests. Timings are
seconds. Records are indented/nested, not one-line JSON, and pass through `redact_secrets`.

```text
[trace] api
  request_id: 8f2c1ab94d70
  method: GET
  route: /api/models/{source_model_id}/entities/{global_id}/details
  status: 200
  elapsed_s: 0.0121

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

[trace] rag
  semantic_query: components related to fire separation
  document_kinds:
    - entity
    - relationship
  top_k: 10
  minimum_similarity: 0.5
  vector_sql:
    - SELECT rag_documents.id, rag_documents.entity_id AS canonical_id, ...
        rag_documents.embedding <=> %(embedding_1)s AS distance
      FROM rag_documents
      WHERE rag_documents.source_model_id = %(source_model_id_1)s ...
      ORDER BY rag_documents.embedding <=> %(embedding_1)s
      LIMIT %(param_1)s
  retrieved_count: 20
  similarity_range: 0.4147 - 0.4584
  result_histogram: entity_description: 10, relationship_description: 10
  elapsed_s: 0.0895
```

**Why no value can leak:** the `after_cursor_execute` hook captures the statement text and *never
reads* `parameters` — values are never collected rather than masked afterwards. The query embedding
is a bound parameter, so the vector SQL shows `%(embedding_1)s` and the 1024-dim vector cannot
appear. The API record logs the route *template*, so query strings that may carry user data are
never logged; request bodies and chat history never reach the tracer at all.

## 2. Exact / viewer / evidence limit behavior

```text
exact database count      no application cap
viewer match identities   2000 (max_viewer_match_ids)
answer-LLM evidence         50 (max_primary_entities, unchanged)
```

- 205 doors -> exact 205, viewer 205 ids, evidence 50. All three independent.
- Above 2,000: first 2,000 in stable `id` order, plus `viewer_matches_total` and
  `viewer_matches_truncated`; the exact count is unchanged, and `class_counts` stay exact (own
  `GROUP BY` over the full matching set, not the truncated slice).
- Viewer identities are captured in the orchestrator **before** `apply_bounds`, so RAG/graph/hybrid
  highlight their full match set rather than the 50-item evidence subset.
- The 2,000 identities are never sent to the answer LLM.

## 3. Aggregate highlighting and wall-class mapping (live, model 1)

| check | before | after |
|---|---|---|
| "How many doors?" viewer ids | **0** (count returned only `facts={"count": n}`) | **205** + select/fit |
| "Show all walls" — classes matched | `IfcWall` only = **648** | `IfcWall` + `IfcWallStandardCase` = **880** |
| "Show all walls" — highlighted | 50 (evidence bound) | **880** (all, under the cap) |

The wall defect was real and material: **232 of 880 walls (26%) were silently missed** by `IfcWall`
alone. Expansion is explicit and testable — unknown classes pass through, an explicit
`IfcWallStandardCase` request is never widened, and no fuzzy matching is used (`IfcCurtainWall` and
`IfcWallElementedCase` are unaffected).

## 4. Component detail / group semantics and current-model availability

Both endpoints are read-only, `source_model_id`-scoped, deterministic, make **zero OpenAI/embedding
calls**, mutate no session/chat state, return allowlisted bounded output (never raw canonical JSON,
geometry, SQL, or paths), and return a bounded 404 for unknown *or* cross-model identity that never
reveals other-model existence.

Type comes only from stored `canonical_json["type"]`; family only from an allowlisted family-like
property name in a stored property set (returned with its source pset/property name). Neither is
ever inferred from name, class, material, or an LLM.

**Live result on Schependomlaan: 0 of 6,989 entities have explicit `canonical_json.type`.** So
`same_type`/`same_family` report unavailable with a concise reason — the expected, correct outcome
per this task, not an error. Sample entity `04PDIFJZXAA8R34kAXRvCn` (`IfcDoor`,
`stelkozijn_(#143009)`, storey `Storey-1`): type `None`, family `None`, materials/quantities/
properties empty — consistent with the documented v001 corpus (no quantity sets, one junk property
set). Its name is not mined for a family/type pattern, verified by test.

Family allowlist (explicit, centralized in `app/viewer/details.py`): `Family`, `FamilyName`,
`FamilyAndType`, `Reference`, `ObjectTypeOverride`. Property/quantity allowlists and the
count/string-length bounds live beside it.

## 5. OpenAPI and test results

New paths and every new schema (`EntityDetailsResponse`, `InstanceDetails`, `TypeDetails`,
`FamilyDetails`, `DetailAvailability`, `DetailValue`, `HighlightGroupRequest`,
`HighlightGroupResponse`, `HighlightScope`, `ResultSummary`, `SampleDetail`, the `ViewerActions`
truncation fields, and `QueryResponseEnvelope.result_summary`) appear in `/openapi.json` and are
asserted by tests. A further test asserts that no schema exposes `canonical_json`, `sql`,
`embedding`, `trace`, or `prompt` as a property.

```text
poetry run ruff check app tests            All checks passed!
poetry run ruff format --check app tests   135 files already formatted
poetry run pytest -m "not live"            349 passed  (268 baseline + 81 new)
```

All tests are offline with mocked providers; **zero live OpenAI calls**.
`frontend_openapi_snapshot.json` was deliberately not regenerated — that is Task 14's first step, so
the existing frontend kept running against the additive contract in between.

## 6. Before/after database and vector state (live, read-only)

| table | before | after |
|---|---|---|
| ifc_source_models | 1 | 1 |
| ifc_entities | 6989 | 6989 |
| ifc_relationships | 3473 | 3473 |
| relationship_members | 17668 | 17668 |
| rag_documents | 10462 | 10462 |
| model_families | 1 | 1 |
| source_model_catalog_entries | 1 | 1 |

Vector metadata: 10,462 rows / 10,462 non-null embeddings / 1 distinct embedding model / 1 distinct
dim / dim 1024 — identical before and after, including after a real bge-m3 + pgvector RAG query. All
access went through the `bim_rag_query_ro` read-only role. No ingestion, model conversion, vector
generation, or standalone live-OpenAI test was run.

## Statuses

```text
Opt-in backend tracing: VALIDATED
Aggregate viewer identities: VALIDATED
Exact/viewer/evidence limits: VALIDATED
Compact result summaries: VALIDATED
Component detail endpoint: VALIDATED
Instance/type/family group endpoint: VALIDATED
Backend regression: VALIDATED
Database/vector/frontend state: UNCHANGED
```
