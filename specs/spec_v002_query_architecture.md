# Specification v002: BIM Query Architecture

## 1. Purpose

Define the shared architecture and contracts for querying the IFC data and vector embeddings created by the completed ingestion pipeline.

The system must allow a user to converse naturally with one or more preprocessed BIM/IFC models through:

- exact SQL retrieval
- IFC relationship traversal using PostgreSQL
- semantic retrieval using pgvector
- hybrid SQL and semantic retrieval
- final natural-language answers grounded in retrieved evidence
- machine-readable viewer actions for a later Three.js BIM frontend

This specification establishes the boundaries shared by all query paths. Detailed behavior will be specified separately:

```text
spec_v003_sql_query_path.md
spec_v004_rag_query_path.md
spec_v005_hybrid_query_orchestration.md
spec_v006_frontend_application.md
```

Frontend behavior is defined by `spec_v006_frontend_application.md`. Where an older frontend
example in this specification conflicts with v006, v006 is authoritative.

## 1.1 Current application and frontend-contract amendment

Task 09 established three independent top-level applications:

```text
ingestion/   # Conda/IfcOpenShell IFC-to-database and stored-vector pipeline
backend/     # pyenv-win/Poetry FastAPI read-only query application
frontend/    # npm/Vite/React/TypeScript viewer and chat application
```

The active backend package root is `backend/app/`, not `backend/src/`. The backend owns its
read-only database definitions and has no imports or runtime dependency on `bim_rag`.

The frontend MVP is desktop-oriented and local-only. It uses a full-window bright Three.js/
That Open viewer with a resizable, collapsible floating chat panel placed over the viewer with
outer margin and rounded corners. It does not use the older hard split-panel drawing below.

The MVP has no IFC upload, authentication, charts, editing, PostGIS geometry path, model catalog
page, or catalog-card landing page. It has a minimal display-name model selector and allows
catalog questions through chat.

Renderable geometry is delivered as a preprocessed, immutable That Open Fragments artifact.
The backend serves the artifact through a narrow validated read-only endpoint; it never converts
IFC at request time. A one-time TypeScript preparation tool creates the artifact from the local
IFC independently of `bim_rag`. PostGIS is reserved for later spatial SQL and does not replace
the optimized viewer artifact.

Viewer clicks and chat citations use IFC GlobalIds at the browser boundary. The frontend does
not need to know database integer IDs. A narrow deterministic backend endpoint resolves selected
GlobalIds within the active `source_model_id`; object selection never requires an LLM call.

There are two distinct clearing actions:

- **Clear Chat** clears visible messages, LLM history, current answer evidence/result highlights,
  and establishes a fresh server conversation while keeping the loaded model, manual object
  selection, and IndexedDB geometry cache.
- **Reset App** returns to the initial model-selection state, clears conversation/model/selection/
  highlights, unloads the scene, cancels pending requests, and establishes a fresh session. It
  retains the IndexedDB geometry cache because that cache has no conversational meaning.

The required narrow backend additions must be implemented and validated separately before the
frontend integration task. They must not add an LLM call, IFC parsing, or database writes.

## 2. Product Intent

Build a local, single-user BIM exploration prototype.

The application will contain multiple IFC models that have already been imported and vectorized. Users do not upload IFC files through the first frontend version.

The intended layout is:

```text
┌──────────────────────────────┬──────────────────────────────┐
│ Three.js BIM viewer          │ Conversational chat          │
│                              │                              │
│ - pan                        │ - user questions             │
│ - rotate                     │ - grounded answers           │
│ - zoom                       │ - result history             │
│ - select                     │ - small evidence/route note  │
│ - highlight query results    │ - reset button               │
└──────────────────────────────┴──────────────────────────────┘
```

Before a model is active, the user can query the available model catalog. The user may also select a model using frontend buttons/cards.

Examples:

```text
Show me a residential model.
Which building has the most doors?
Show the available versions of this project.
Load the Schependomlaan model.
```

After the user confirms and loads a model, the session becomes scoped to that model until the user
uses **Reset App** or selects another model. **Clear Chat** starts a fresh conversation but keeps
the same active model.

Examples:

```text
How many doors are in this building?
Which doors are located on Level 2?
Which components relate to fire separation?
Highlight the walls connected through this relationship.
```

## 3. Existing Data Foundation

The query architecture must use the existing PostgreSQL tables:

```text
ifc_source_models
ifc_entities
ifc_relationships
relationship_members
rag_documents
```

Their canonical identity relationships are:

```text
ifc_source_models.id
├── ifc_entities.source_model_id
├── ifc_relationships.source_model_id
├── relationship_members.source_model_id
└── rag_documents.source_model_id

ifc_entities.id
├── relationship_members.entity_id
└── rag_documents.entity_id

ifc_relationships.id
├── relationship_members.relationship_id
└── rag_documents.relationship_id
```

The query system must never use names, generated prose, or approximate matching as substitutes for canonical database identity.

IFC GlobalIds are the bridge from database results to rendered IFC objects in the future viewer.

## 4. Query Scopes

Every query plan must declare one of two scopes.

### 4.1 Model-catalog scope

```text
scope = model_catalog
```

Use this when no model is active or when the user explicitly asks about available models or compares models.

Supported architectural intents include:

- list available models
- filter models using catalog metadata
- show versions of a model family
- compare model-level facts
- rank models using exact aggregates such as door count
- retrieve source-model metadata
- request that a model be loaded

The first catalog implementation must use SQL over model metadata and exact structured aggregates. Cross-model RAG is deferred.

Catalog questions must not search every model's `rag_documents` in the first version.

### 4.2 Active-model scope

```text
scope = active_model
```

Use this after one source model has been selected and confirmed.

Every SQL, relationship, vector, and hybrid operation must be constrained to exactly one active `source_model_id`.

The model scope persists for the current browser session until:

- the user presses reset
- the user explicitly selects another model
- the user asks to return to catalog browsing

### 4.3 No implicit global detailed search

If no model is active, detailed entity, relationship, or vector queries must not silently search all models.

The planner must either:

- interpret the request as a catalog query
- ask the user to choose a model
- return model candidates for confirmation

## 5. Model Catalog and Version Metadata

The model catalog requires additional metadata beyond the existing file fingerprint and IFC schema.

Extend the source-model representation, either directly or through normalized related tables, to support:

- display name
- model-family identity
- version label
- version order
- current-version indicator
- building/project type or use, such as residential or office
- discipline, when known
- manually editable tags
- optional short description
- model availability/status
- viewer source/artifact location

### 5.1 Metadata provenance

Catalog metadata must distinguish provenance:

```text
ifc_extracted
manual
derived_exact
```

Use IFC-extracted metadata where reliable and permit manually editable fields.

Do not treat LLM-inferred tags such as `residential` as authoritative catalog metadata.

### 5.2 Version identity

Use an explicit model-family/version structure equivalent to:

```text
model_family_id
version_label
version_order
is_current
```

Different IFC fingerprints may belong to the same model family.

The system must not infer version ordering from filenames alone.

### 5.3 Model loading

Catalog queries return model cards/candidates. They must not automatically load a potentially large IFC model.

The user must click or confirm the desired model. Only then does the session adopt its `source_model_id` and instruct the viewer to load it.

## 6. LLM Configuration

Use the OpenAI API.

Initial planner and answer model:

```text
gpt-5-nano
```

The model name must be configuration-driven so it can be changed later without rewriting query logic or schemas.

Load the API key from:

```text
OPENAI_API_KEY
```

Requirements:

- Store the key in `.env` or the runtime environment.
- Claude and application logs must never print, expose, or hard-code the key.
- Do not place the key in frontend code.
- All OpenAI calls occur in the backend.
- Sanitize provider errors before returning them to the frontend.

## 7. LLM Role and Structured Planning

An LLM call is required for every natural-language user question.

The LLM interprets paraphrases and user intent. For example, these must map to the same underlying operation:

```text
How many doors are there?
What is the total door count?
Count all doors in this building.
```

### 7.1 Schema-enforced output

Use schema-enforced structured output for the query plan.

Do not rely only on prompt instructions such as `Output valid JSON` followed by regex repair.

The planner must return a typed, validated object represented by Pydantic models or an equivalent strict JSON Schema.

### 7.2 No raw SQL generation

The LLM must never generate or execute raw SQL.

It must not provide unrestricted:

- table names
- column lists
- join expressions
- `WHERE` fragments
- SQL functions
- JSONB paths
- ordering expressions

Instead, it returns semantic operations and validated arguments. Trusted backend code compiles those operations into parameterized SQL.

### 7.3 Planner responsibility

The LLM decides:

- query scope
- route
- semantic operation
- relevant filters
- whether relationship expansion is needed
- whether model confirmation is required
- how SQL and RAG evidence should be combined for hybrid questions

Python code validates and executes the plan. Python must not attempt to replace natural-language interpretation with fragile keyword matching.

### 7.4 Initial route vocabulary

Every plan declares one route:

```text
sql
rag
graph
hybrid
explain_general
clarify
```

Meanings:

- `sql`: exact structured filtering, aggregation, or catalog query
- `rag`: semantic retrieval over entity or relationship descriptions
- `graph`: deterministic traversal of IFC relationships stored relationally
- `hybrid`: coordinated SQL, graph, and/or RAG retrieval
- `explain_general`: general BIM/IFC explanation not requiring model data
- `clarify`: missing scope or ambiguity prevents safe execution

## 8. Shared Query-Plan Contract

The exact schemas will be finalized in the path specifications, but the architecture must support a plan equivalent to:

```json
{
  "scope": "active_model",
  "route": "hybrid",
  "active_source_model_id": 1,
  "catalog_plan": null,
  "sql_plan": {
    "operation": "filter_entities",
    "entity_classes": ["IfcDoor"],
    "filters": [],
    "limit": 50
  },
  "rag_plan": {
    "semantic_query": "components associated with fire separation",
    "search_entity_documents": true,
    "search_relationship_documents": true,
    "top_k_per_kind": 30,
    "minimum_similarity": null
  },
  "graph_plan": {
    "expand_relationship_endpoints": true,
    "max_depth": 1
  },
  "combination": "intersection",
  "answer_basis_expected": "hybrid_evidence",
  "viewer_intent": "select_and_fit"
}
```

All fields must be allowlisted and type-validated.

The backend must reject or repair through a bounded replanning step any plan that:

- uses an unsupported operation
- omits required scope
- requests cross-model detailed retrieval unintentionally
- exceeds limits
- uses unsupported operators
- requests raw SQL
- refers to nonexistent model IDs

## 9. SQL and Deterministic Query Boundary

SQL is authoritative for:

- exact counts
- exact filtering
- grouping
- sorting
- aggregation
- model comparison
- model metadata
- property and quantity lookup
- missing-value analysis
- relationship membership
- relationship traversal

SQL operations must be compiled from validated semantic plans and executed using parameterized statements.

Initial result limits:

```text
default list limit = 50
maximum list limit = 500
```

Exact counts and aggregates operate over the full matching set even if returned example rows are limited.

### 9.1 Units

Use normalized internal units:

```text
length = mm
area   = mm²
volume = mm³
angle  = degrees
```

Preserve source values and provenance where available.

User-facing formatting may convert normalized values into readable units, but calculations and comparisons must use normalized values.

### 9.2 Calculation boundary

The first version may support reliable generic operations:

- count
- sum
- minimum
- maximum
- average
- group by

Only use them on validated numeric facts with known units and meaning.

Specialized BIM metrics require dedicated deterministic functions and definitions. RAG and the LLM must not perform authoritative numerical calculations from prose.

### 9.3 Pandas boundary

Pandas may be used for bounded post-retrieval transformations, presentation, and prototype analysis.

Do not retrieve large raw datasets merely to reproduce filtering, joining, grouping, or aggregation that PostgreSQL can perform safely.

## 10. IFC Relationship and Graph Boundary

No graph database is required in the first version.

Graph traversal means deterministic PostgreSQL traversal through:

```text
ifc_relationships
→ relationship_members
→ ifc_entities
```

Initial traversal controls:

```text
default depth = 1
maximum depth = 3
cycle prevention = required
source_model_id isolation = required
```

If a relationship is retrieved through SQL or RAG, retrieve all of its direct endpoint entities together.

Distinguish:

- primary matches
- relationship context endpoints

The frontend highlights entity geometry. Relationship records themselves are evidence and traversal structures, not rendered meshes.

## 11. RAG Boundary

Use the existing local embedding model:

```text
BAAI/bge-m3
dimension = 1024
distance = cosine
```

The query embedding service must remain loaded persistently in the backend rather than loading the model for each request.

Query vectors are ephemeral. Resetting chat or changing questions does not delete stored document embeddings.

### 11.1 Search kinds

The RAG path supports:

- entity-description search
- relationship-description search

Search them separately and fuse results only when both are relevant.

The planner may disable relationship search for questions that only require entity semantics.

### 11.2 Initial retrieval settings

Use architecture defaults equivalent to:

```text
display candidates = 10
internal candidates per searched kind = up to 30
minimum similarity threshold = required and configurable
```

The final threshold must be calibrated through representative BIM questions. Do not treat cosine similarity as a probability.

### 11.3 Rank fusion

When entity and relationship results are combined, preserve per-kind similarity and rank information.

Use a documented rank-fusion method such as reciprocal rank fusion for the first version instead of assuming raw entity and relationship cosine scores are directly comparable.

### 11.4 Partial availability

If the local embedding service is unavailable:

- SQL and graph routes remain available.
- RAG and hybrid routes report degraded capability.
- The system must not silently substitute an incompatible embedding model.

## 12. Hybrid Execution

Hybrid plans may use:

```text
SQL candidates → semantic ranking
RAG candidates → SQL filtering
SQL and RAG in parallel → ID intersection
SQL and RAG in parallel → ID union
RAG relationship results → endpoint expansion → SQL filtering
SQL relationship results → endpoint expansion → semantic ranking
```

Run SQL and RAG in parallel only when their inputs are independent.

Do not run both paths for every question merely because both exist.

The hybrid specification must define explicit:

- execution order
- dependency rules
- union/intersection semantics
- rank retention
- relationship expansion
- empty-result behavior
- exact-count versus retrieval-candidate language

Never count the top-k RAG results as though they represent an exhaustive database set.

## 13. Evidence and Answer Grounding

Final answers must be based on retrieved SQL, graph, and/or RAG evidence.

The answer generator must not invent model-specific facts.

Every response must internally classify its basis:

```text
exact_sql
semantic_retrieval
graph_traversal
hybrid_evidence
general_knowledge
insufficient_evidence
```

The user does not need to see these internal labels prominently. The frontend may show a small route/evidence note near the bottom of the answer.

### 13.1 Model evidence and general knowledge

The LLM may answer general BIM/IFC questions and may add useful general explanation to model-derived facts.

Internally distinguish:

- facts retrieved from the selected IFC/database
- general BIM knowledge
- inference

This distinction does not need to be explicit in normal prose, but the answer must not present an unsupported generalization as a measured property of the model.

Example:

```text
Supported: The model contains 84 doors across six storeys.
Allowed general context: Door counts vary with occupancy and layout.
Unsupported without reference data: This is a normal door count.
```

### 13.2 Conflicting evidence

When retrieved records conflict, preserve all relevant evidence and disclose the conflict in the answer.

Do not silently ask the LLM to choose an authoritative value without a deterministic precedence rule.

### 13.3 IDs and citations

Canonical database IDs and IFC GlobalIds remain in structured evidence and logs.

Do not show IDs to users by default. Show them only when:

- the user explicitly asks
- a developer/evaluation view is enabled
- the frontend requires GlobalIds for viewer selection

The frontend may display a small citation/evidence summary without exposing internal SQL or full canonical JSON.

## 14. Answer Pipeline

Use a controlled two-stage logical process:

```text
Question + session context
→ schema-enforced LLM query plan
→ validated backend execution
→ structured evidence package
→ grounded LLM answer generation
→ frontend answer + viewer actions
```

This may use one managed OpenAI conversation/tool loop internally, but planning, execution, and evidence must remain separately loggable and testable.

The answer generator receives only bounded, relevant evidence rather than unrestricted database dumps.

## 15. Session and Conversation State

The first version is local and single-user.

Maintain state for the current browser session only:

- chat messages
- active `source_model_id`
- selected viewer object IDs
- last query results
- model-catalog versus active-model mode

Provide a reset action equivalent to Explorentory.

Reset clears:

- chat history
- active model selection
- selected viewer objects
- prior result context

Reset must not delete:

- IFC source records
- structured database rows
- stored embeddings
- catalog metadata

Support conversational references after single-turn behavior is validated:

```text
Show fire-rated doors.
Which of those are on Level 2?
```

Limit selected viewer objects supplied to LLM context to five.

Represent selected objects by canonical IDs and compact summaries, not complete canonical JSON.

## 16. Backend API Contract

Use FastAPI.

The public natural-language query endpoint is:

```text
POST /api/query
```

Low-level SQL, RAG, graph, and planning endpoints remain development-only. The narrow deterministic
model-list, viewer-asset, and GlobalId-resolution endpoints defined by v006 are also public frontend
contracts, but they never invoke an LLM.

### 16.1 Request envelope

Support a request equivalent to:

```json
{
  "question": "Which doors relate to fire separation?",
  "session_id": "browser-session-id",
  "active_source_model_id": 1,
  "selected_global_ids": ["IFC-GLOBAL-ID-1", "IFC-GLOBAL-ID-2"],
  "history": []
}
```

The active model may be null for catalog queries. Browser selection uses GlobalIds; database
integer entity IDs are backend-internal/backward-compatible inputs only.

### 16.2 Response envelope

Return a response equivalent to:

```json
{
  "request_id": "...",
  "session_id": "...",
  "status": "success",
  "scope": "active_model",
  "route": "hybrid",
  "answer_basis": "hybrid_evidence",
  "answer": "...",
  "active_source_model_id": 1,
  "model_candidates": [],
  "primary_entities": [],
  "context_entities": [],
  "relationships": [],
  "viewer_actions": {},
  "evidence_summary": {},
  "warnings": []
}
```

Do not return by default:

- raw SQL
- database credentials
- OpenAI credentials
- full canonical JSON
- full prompts
- unrestricted debug traces

### 16.3 Timing and limits

Use synchronous requests initially with:

- database statement timeouts
- OpenAI request timeouts
- bounded history
- bounded evidence
- bounded result counts

Streaming is deferred.

## 17. Viewer Contract

The backend must return semantic viewer actions even though frontend implementation is deferred.

Example:

```json
{
  "viewer_actions": {
    "model_action": "keep_current",
    "selection_action": "select_and_fit",
    "primary_global_ids": ["..."],
    "context_global_ids": ["..."],
    "role_groups": [
      {
        "role": "primary_match",
        "global_ids": ["..."]
      },
      {
        "role": "relationship_context",
        "global_ids": ["..."]
      }
    ]
  }
}
```

Default result behavior:

- select matching objects
- fit camera to selection
- keep the remaining model visible
- distinguish primary results from context objects

The backend supplies semantic roles. The frontend chooses colors and rendering style.

The backend must not generate camera coordinates or directly control Three.js.

## 18. Current Three.js/IFC Frontend Direction

The frontend loads a preprocessed That Open Fragments artifact using the current supported That
Open/Three.js stack. It must not parse the full raw IFC during normal application startup.

The database remains the source of semantic/structured information. The immutable Fragments file
is the browser rendering source. A manual TypeScript preparation tool may read the local IFC to
produce that artifact; it is not an ingestion import and must not run during an HTTP request.

Use IFC GlobalId mapping:

```text
query result entity
→ IFC GlobalId
→ rendered viewer object
```

Cache prepared artifacts in IndexedDB by source-model identity and model fingerprint. Keep the
initial cache policy conservative and bounded. PostGIS geometry is explicitly deferred and is not
a replacement for the rendering artifact.

Clicking an object in the viewer must be able to:

- select it visually
- obtain its IFC GlobalId from the rendered artifact
- resolve the GlobalId deterministically through the backend within the active model
- add it to chat context
- support questions such as `What is this?` and `What connects to this?`

Use frontend caching and selection debouncing. Indexed object lookup should not require loading full canonical JSON unless requested.

## 19. Source-Code Organization

The tree below records the original scaffold plan. Task 09 superseded its Python paths. The active
top-level applications are `ingestion/`, `backend/`, and `frontend/`; backend code is under
`backend/app/`, with no backend ingestion package. The authoritative frontend tree and boundaries
are defined in `spec_v006_frontend_application.md`.

Separate backend and frontend at repository level.

Target structure:

```text
backend/
├── src/
│   ├── config/
│   │   ├── settings.py
│   │   └── logging.py
│   ├── db/
│   │   ├── models.py
│   │   ├── session.py
│   │   └── repositories/
│   ├── ingestion/
│   │   ├── entities.py
│   │   ├── relationships.py
│   │   └── embeddings.py
│   ├── llm/
│   │   ├── client.py
│   │   ├── schemas.py
│   │   ├── router.py
│   │   ├── answerer.py
│   │   └── prompts/
│   ├── query/
│   │   ├── catalog/
│   │   ├── sql/
│   │   ├── graph/
│   │   ├── rag/
│   │   ├── hybrid/
│   │   └── service.py
│   ├── api/
│   │   ├── app.py
│   │   ├── routes/
│   │   └── schemas/
│   ├── viewer/
│   │   └── actions.py
│   ├── evaluation/
│   │   ├── cases.py
│   │   └── metrics.py
│   └── shared/
│       ├── types.py
│       └── errors.py
└── tests/

frontend/
├── src/
│   ├── viewer/
│   ├── chat/
│   ├── api/
│   ├── state/
│   └── components/
└── tests/
```

Detailed prompt text belongs in versioned files under:

```text
backend/app/llm/prompts/
```

Typed planner and answer schemas belong in:

```text
backend/app/llm/schemas.py
```

Do not place all LLM, SQL, RAG, and API logic in one Python module.

### 19.1 Existing ingestion code

Preserve the working ingestion/vectorization implementation initially.

Do not move or rewrite completed ingestion modules as part of initial query-path work unless necessary for imports. Perform broad relocation through a dedicated refactoring task protected by regression tests.

Generated frontend types from OpenAPI are not required initially.

## 20. Security and Reliability

The application is local and single-user, but still enforce:

- backend-only database access
- backend-only OpenAI access
- dedicated read-only database role for query execution
- parameterized SQL
- table/field/operator allowlists
- required source-model scoping
- statement timeouts
- result limits
- bounded graph traversal
- bounded conversation history
- bounded LLM evidence context
- secret sanitization
- no arbitrary SQL

Although PostgreSQL is local, the backend must connect to it. “Local” means the connection does not need to leave the machine, not that database access can be omitted.

## 21. Logging and Prototype Evaluation

The primary goal is a functional prototype, but retain enough structured logs to evaluate failures.

For each query, log safely:

- request ID
- timestamp
- session ID
- active source model
- question
- schema-validated plan
- selected route
- operations executed
- retrieved canonical IDs
- vector ranks/scores
- relationship expansions
- latency by stage
- OpenAI token usage
- final answer
- warnings/errors
- optional user feedback

Do not log secrets or unrestricted canonical JSON.

Maintain a small benchmark set with expected:

- scope
- route
- answer type
- relevant canonical IDs when practical
- exact counts when applicable
- required relationship classes

Retrieval precision and recall are evaluation metrics, not training requirements. They measure whether RAG returned the correct existing IFC records.

Store incorrect or ambiguous questions as reusable failure cases in a dedicated versioned evaluation file.

Normal users do not see raw query plans or evidence. A development mode may expose a compact collapsible diagnostic panel. The normal frontend shows only natural-language results, highlighted geometry, and a small evidence/route citation.

## 22. Explicit Non-Goals for v002

This architecture specification does not authorize implementation of:

- the detailed SQL tool set
- the detailed RAG search implementation
- the hybrid execution engine
- the Three.js frontend
- IFC upload through the frontend
- cross-model RAG
- geometry storage in PostgreSQL
- PostGIS geometry queries
- a graph database
- arbitrary model-generated SQL
- streaming answers
- multi-user authentication
- model deletion workflows
- persistent chat history across application restarts
- automatic authority resolution for conflicting IFC data

Those items require later specifications where applicable.

## 23. Required Follow-on Specifications

### v003: SQL query path

Must define:

- catalog SQL
- active-model SQL
- allowlisted operations
- property/quantity querying
- normalized units
- exact aggregation
- relational IFC graph traversal
- response/evidence contracts

### v004: RAG query path

Must define:

- persistent query-embedding service
- entity and relationship searches
- threshold calibration
- per-kind ranking
- relationship endpoint expansion
- source-model isolation
- RAG evidence hydration

### v005: Hybrid orchestration

Must define:

- final planner schema
- SQL/RAG/graph execution dependencies
- parallel execution rules
- intersection/union
- rank fusion
- grounded answer generation
- conversational follow-ups
- failure and degraded-mode behavior

### Later frontend specification

Must define:

- model catalog UI
- model confirmation/loading
- Three.js/IFC viewer
- chat interface
- viewer selection and highlighting
- session reset
- compact evidence citations
- selected-object chat context

## 24. Architecture Acceptance Criteria

This architecture is considered correctly implemented by later tasks only when:

1. Every natural-language question is interpreted through an OpenAI schema-enforced planner call.
2. The configured initial model is `gpt-5-nano` and can be changed without rewriting schemas.
3. No LLM-generated raw SQL is accepted or executed.
4. Catalog and active-model scopes are explicit and cannot leak into each other.
5. Catalog SQL can discover, compare, and select among preprocessed models.
6. Detailed SQL, graph, RAG, and hybrid queries require one active model.
7. Every detailed database and vector operation is constrained by `source_model_id`.
8. SQL answers remain exact and distinct from semantic candidate retrieval.
9. Relationship traversal uses canonical IDs and returns endpoint entities as context.
10. Hybrid execution preserves canonical identity across SQL, graph, and RAG.
11. Final model-specific claims are grounded in retrieved evidence.
12. General BIM explanations do not masquerade as measured model facts.
13. The public FastAPI contract exposes only `/api/query` to the frontend initially.
14. Responses include natural-language answers plus machine-readable viewer actions.
15. Viewer actions use IFC GlobalIds and distinguish primary matches from context.
16. Chat and active-model state persist only for the current browser session and can be reset.
17. Query execution uses read-only database access, timeouts, allowlists, and bounded results.
18. Backend modules are organized into dedicated LLM, SQL, graph, RAG, hybrid, API, viewer-contract, and evaluation subfolders.
19. Existing working ingestion/vectorization behavior remains protected during query development.
20. Query plans, evidence, latency, and failures are logged safely for prototype evaluation.

## 25. Task 04 Implementation Notes

Task 04 (`tasks/task04_done.md`) implemented the shared foundation described
above: the `backend/`/`frontend/` folder structure (Section 19), a FastAPI
skeleton with `/health`, `/ready`, and `POST /api/query`, Pydantic base
schemas (query scope/route, `QueryPlan` shells, session/query request,
viewer actions, model candidates, primary/context entity and relationship
results, the response envelope), an `LLMClient` interface configured for
`gpt-5-nano` with no reachable production OpenAI call, versioned prompt-file
locations with no prompt text yet, session-state models with `reset()`
semantics, an additive (NOT EXECUTED) catalog-metadata migration proposal,
JSONL logging with secret redaction, and compatibility shims over the
existing `src/bim_rag/` ingestion pipeline. Full command reference:
`docs/architecture_v002.md`.

No SQL, RAG, graph, or hybrid query path was implemented — those remain
governed by `spec_v003_sql_query_path.md`, `spec_v004_rag_query_path.md`,
and `spec_v005_hybrid_query_orchestration.md`. 198/198 tests pass (158
pre-existing ingestion tests + 40 new `backend/tests`); `ruff format`/`ruff
check` clean.

```text
Catalog database migration: NOT EXECUTED
Production OpenAI calls: NOT EXECUTED
SQL path: NOT IMPLEMENTED
RAG query path: NOT IMPLEMENTED
Hybrid orchestration: NOT IMPLEMENTED
```


---

## Task 09 Addendum: Three Independent Applications (Database-Only Boundary)

Task 09 restructured the repository into three independently managed top-level
projects. **PostgreSQL is the only runtime integration boundary between them.**

```text
ingestion/   IFC → PostgreSQL structured tables + stored corpus vectors (Conda `bim_rag`, Python 3.11)
backend/     FastAPI SQL/RAG/graph/hybrid query service, read-only on BIM data (pyenv-win 3.11 + Poetry)
frontend/    (placeholder) future Three.js BIM viewer + chat UI
```

### Boundary rules

- The backend does **not** import ingestion code (`bim_rag`), parse IFC files,
  create/migrate BIM tables, or generate stored corpus vectors.
- Ingestion does not import backend code.
- The backend owns its own read-oriented SQLAlchemy models (`backend/app/db/models.py`)
  mirroring the live schema, its own DB config (`backend/app/config/database.py`:
  `get_db_url`, `sanitize_db_error`, `THREAD_LIMIT`), and its own query-embedding
  runtime (BAAI/bge-m3, dim 1024), validated against stored vectors at query time
  (`app/query/rag/search.py::check_compatibility`).
- Similar-looking model/config definitions across the two applications are
  intentional duplication: independence over de-duplication.

### Schema ownership

Ingestion creates/migrates the five canonical tables (`ifc_source_models`,
`ifc_entities`, `ifc_relationships`, `relationship_members`, `rag_documents`) and
the two catalog tables (`model_families`, `source_model_catalog_entries`). Schema
and read-only-role admin utilities live under `ingestion/src/bim_rag/db_admin/`
(`apply_catalog_migration`, `bootstrap_readonly_role`). The backend is read-only:
no table creation/alteration, no corpus/vector mutation, and no superuser fallback
for ordinary operation (it uses the dedicated `bim_rag_query_ro` role via `DATABASE_URL`).

### Authoritative commands

```powershell
# Ingestion (from ingestion/, Conda bim_rag)
pip install -e .
pytest

# Backend (from backend/, pyenv-win 3.11 + Poetry)
poetry install
poetry run uvicorn app.main:app --reload     # authoritative
poetry run pytest                             # offline; ZERO OpenAI calls
poetry run pytest tests/query_live            # live read-only PostgreSQL tests
```

`app.main:app` exposes the same FastAPI application and public endpoints
(`POST /api/query`, `/health`, `/ready`) as the previous `api.app:app`. Normal
test runs make zero OpenAI API calls (LLM behavior is mocked/faked); there is no
automatic or opt-in live-OpenAI test setup.

---

## Task 16 amendment — Universal hybrid semantic evidence pipeline

Task 16 amends the query architecture for conversational **active-model** questions. Where this
section conflicts with earlier v002 route wording, this section governs.

- **New backend resource: IFC ontology.** A committed, versioned, machine-readable IFC schema
  ontology (`backend/app/query/semantic/ontology/IFC2X3.json`, the 301-class `IfcRoot` hierarchy)
  plus a committed BGE-M3 semantic index. It is read-only at runtime; generated by an offline dev
  utility (IfcOpenShell). No synonym/alias gate — classes are searched semantically.
- **New backend resource: model vocabulary.** A bounded, read-only, in-memory semantic vocabulary
  derived per source model from the live DB (class/observed-fact/quantity profiles). No BIM-table
  or corpus-vector writes; no migration; cache keyed by
  (source_model_id, file_fingerprint, extraction_version, profile_builder_version, embedding_model).
- **Pipeline shape (still two OpenAI calls).** Pre-planner semantic resolution → planner (call 1)
  emits a bounded array of typed **probes** (route reuses the `hybrid` value) → deterministic probe
  execution + structured verification → answerer (call 2) judges probe relevance and writes the
  answer. No third routing/judge call; no unbounded replan loop.
- **Exceptions preserved:** catalog, `explain_general`, `clarify` (last resort), and deterministic
  component detail/group endpoints are unchanged.
- The public `/api/query` response envelope is unchanged (additive backend behavior only).

---

## Task 17 amendment — Query-only retrieval policy, evidence groups, complete viewer

Task 17 restructures the conversational active-model pipeline into nine stages and corrects the
Task 16 circulation defect (a SQL `IN(...)` count reported as a concept total). Where this conflicts
with Task 16 wording, this governs. Completed task history is not rewritten.

- **Two LLM calls, reordered.** Call 1 is now a **query-only retrieval-policy + facet planner**
  (`build_policy_context` carries NO active-model candidates/schema); its SQL/RAG/graph decision is
  **frozen before** semantic resolution runs (now Stage 3). Call 2 is the group-aware answerer.
- **Modality isolation** is a dataflow guarantee: retrieval modes depend only on
  query/history/selection/scope, and are identical across resolver fixtures (tested).
- **Evidence groups** replace mixed probes: each group is one semantic claim (one class, or one
  typed name/property predicate, or one bounded RAG candidate set) with a stable id, a safe typed
  predicate, authority, coverage, and a deterministic factual profile.
- **Complete viewer identities**: the fixed `max_viewer_match_ids=2000` cap is removed from result
  meaning; every accepted-group GlobalId is hydrated post-answer; missing GlobalIds are reported
  distinctly (not truncation). The 50-example LLM budget no longer constrains the viewer set.
- The public `/api/query` envelope is unchanged (viewer identity list is simply uncapped).
