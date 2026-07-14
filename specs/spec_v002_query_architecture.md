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
```

Frontend implementation will be specified later. This specification defines the backend/frontend contract that future frontend work must consume.

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

After the user confirms and loads a model, the session becomes scoped to that model until the user resets or selects another model.

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

The only public query endpoint in the first version is:

```text
POST /api/query
```

Low-level SQL, RAG, graph, planning, model, entity, and relationship endpoints may exist for development/testing but are not part of the public frontend contract.

### 16.1 Request envelope

Support a request equivalent to:

```json
{
  "question": "Which doors relate to fire separation?",
  "session_id": "browser-session-id",
  "active_source_model_id": 1,
  "selected_entity_ids": [101, 102],
  "history": []
}
```

The active model may be null for catalog queries.

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

## 18. Future Three.js/IFC Frontend Direction

The first frontend viewer may load the selected raw IFC directly in the browser using `web-ifc` or a compatible current That Open/Three.js stack.

The database remains the source of semantic/structured information. The IFC file remains the geometry source.

Use IFC GlobalId mapping:

```text
query result entity
→ IFC GlobalId
→ rendered viewer object
```

Because large IFC files may be slow to parse repeatedly, preserve the option to add cached Fragments-derived viewer artifacts later without storing geometry in PostgreSQL.

Clicking an object in the viewer must be able to:

- select it visually
- resolve its GlobalId/canonical entity ID
- retrieve a compact indexed database summary
- add it to chat context
- support questions such as `What is this?` and `What connects to this?`

Use frontend caching and selection debouncing. Indexed object lookup should not require loading full canonical JSON unless requested.

## 19. Source-Code Organization

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
backend/src/llm/prompts/
```

Typed planner and answer schemas belong in:

```text
backend/src/llm/schemas.py
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

