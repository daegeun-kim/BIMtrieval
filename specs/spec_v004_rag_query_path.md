# Specification v004: RAG and Vector Query Path

## Current architecture amendment (Task 09 and frontend planning)

The active backend is the independent Poetry application under `backend/app/`. Read every
`backend/src/...` path later in this document as `backend/app/...`.

The query embedding service is fully backend-owned. It may use the same third-party model and
compatible settings as ingestion, but it must not import `bim_rag`, ingestion constants, or the
corpus-vectorization implementation. Compatibility is validated from stored database metadata.

Frontend selections arrive as IFC GlobalIds scoped by `source_model_id` and are resolved through
a deterministic read-only backend contract before selected-object RAG filtering. This resolution
does not consume an LLM call. PostGIS is deferred and is not required for semantic retrieval or
frontend rendering.

## 1. Purpose

Define semantic retrieval over `rag_documents` under `spec_v002_query_architecture.md`.

This path retrieves semantically relevant entity and relationship documents. It does not provide exhaustive counts or replace deterministic SQL.

This is a blueprint only. Implementation and execution require later task files.

## 2. Code Organization

```text
backend/app/query/rag/
├── schemas.py
├── embedding_service.py
├── search.py
├── thresholds.py
├── fusion.py
├── hydration.py
├── relationship_expansion.py
└── errors.py
```

Do not mix query-time embedding code with ingestion vector generation or API route handlers.

## 3. Embedding Compatibility

Query vectors must use the same representation as stored documents:

```text
model = BAAI/bge-m3
dimension = 1024
normalization = L2
distance = cosine
```

Validate stored model/template metadata before search. Do not silently compare embeddings from incompatible models or dimensions.

Query vectors are ephemeral and must never be inserted into `rag_documents`.

## 4. Persistent Embedding Service

Maintain one backend embedding service instance. Load the model lazily on the first RAG request and expose readiness/failure state.

If loading fails:

- SQL and graph paths remain usable.
- RAG reports unavailable.
- hybrid planning may degrade only through explicit controlled behavior.
- do not substitute another embedding model automatically.

Query embedding uses batch size one and the conservative token/thread/device controls established after the earlier CUDA stability incident. A single query must not invoke the corpus vectorization pipeline.

A new question replaces only the ephemeral query vector. Chat reset does not unload or delete the persistent model or stored embeddings.

## 5. RAG Plan Schema

Support a schema equivalent to:

```json
{
  "source_model_id": 1,
  "semantic_query": "components related to fire separation",
  "search_entity_documents": true,
  "search_relationship_documents": true,
  "top_k_per_kind": 30,
  "visible_limit": 10,
  "minimum_similarity_profile": "default_v001",
  "expand_relationship_endpoints": true
}
```

Require one active source model. Cross-model RAG is deferred.

At least one document kind must be enabled. Relationship search runs only when requested by the planner.

## 6. Source-Scoped Search

Every vector query must filter:

```text
rag_documents.source_model_id = active source model
```

Also filter compatible:

- source kind
- document type
- embedding model
- dimension
- active template/version policy
- non-null valid vector

Use parameterized pgvector queries and the cosine HNSW index where applicable.

No default query may return another model's documents.

## 7. Entity and Relationship Retrieval

Search separately:

```text
entity_description
relationship_description
```

Do not assume their raw similarity distributions are interchangeable.

Defaults:

```text
internal candidates per enabled kind = up to 30
visible primary results = up to 10
```

Preserve for every candidate:

- cosine distance/similarity
- per-kind rank
- RAG document ID
- canonical entity or relationship ID
- source model
- document/model/template metadata
- generated text excerpt

Scores remain internal/debug metadata and are not shown in normal chat.

## 8. Similarity Thresholds

A minimum threshold is required, but no universal BGE-M3 threshold may be asserted without calibration.

Implement named, configurable threshold profiles and produce a calibration report using representative BIM questions with known relevant records.

Weak candidates below the active threshold:

- are excluded from factual answer evidence
- may remain in safe debug/evaluation logs
- must not be presented as relevant merely because they are top-k

If no candidate passes threshold, return `insufficient_evidence` rather than lowering the threshold silently.

## 9. Rank Fusion

When both kinds are searched, fuse their ranked lists using a documented method such as reciprocal rank fusion.

Use a configurable initial RRF constant of 60.

Preserve original per-kind similarities and ranks after fusion. Do not present the fused score as probability.

SQL exact matches in later hybrid processing are constraints/evidence, not vector scores and must not be blended into cosine similarity.

## 10. Relationship Expansion

When a relationship candidate passes threshold and expansion is requested:

1. Retrieve the canonical `ifc_relationships` row.
2. Retrieve all direct `relationship_members` in deterministic role/order.
3. Hydrate all resolved endpoint entities.
4. Preserve unresolved endpoint metadata.
5. Mark the relationship as primary semantic evidence.
6. Mark endpoints as context unless later SQL constraints promote them to primary results.

Endpoint expansion is scoped to retrieved relationships and the active model, making it acceptable for the current relationship counts.

Do not recursively traverse beyond direct endpoints in the raw RAG path. Deeper traversal belongs to graph/hybrid execution with explicit depth controls.

## 11. Evidence Hydration

Vector text is retrieval evidence, not the final authoritative object payload.

Hydrate each accepted candidate from structured tables and return compact fields:

- canonical ID
- GlobalId
- IFC class
- name/description summary
- matched document kind
- relevant structured facts
- relationship endpoint roles where applicable
- primary/context status
- rank/similarity in internal metadata

Do not send full canonical JSON to the frontend or answer LLM by default.

## 12. Semantic Answer Boundary

RAG answers questions such as:

- which components relate to fire separation
- what elements appear associated with circulation
- which relationships describe spatial containment
- find objects semantically similar to a selected object description

RAG does not establish exhaustive counts. Phrase results as retrieved candidates unless SQL establishes completeness.

Never report `top_k` as the total number of relevant BIM objects.

## 13. Selected-Object Context

Support up to five viewer-selected canonical entity IDs.

For selected-object semantic questions, construct the query from:

- user wording
- compact selected-object identity/class/name
- bounded relevant descriptive facts

Do not inject full object JSON or stored embeddings into the prompt.

## 14. Failure and Degraded Behavior

Return structured states for:

- embedding service loading
- incompatible stored embeddings
- no candidate above threshold
- vector database timeout
- invalid active model
- missing entity/relationship source rows
- relationship endpoint hydration warnings

RAG failure must not corrupt chat/session state or stored vectors.

## 15. Tests and Calibration

Test:

- lazy persistent service lifecycle
- batch-one query embedding and dimension/normalization
- no query-vector persistence
- active-model isolation
- entity-only, relationship-only, and combined search
- relationship search disabled when not requested
- top-k and visible limits
- threshold exclusion
- no-result behavior
- RRF with configurable constant 60
- score/rank preservation
- direct endpoint expansion and unresolved endpoints
- primary/context classification
- incompatible model/dimension rejection
- selected-object context limit
- SQL availability when RAG is unavailable

Build a small versioned calibration set with questions, relevant canonical IDs, and relevance judgments. Report precision/recall at candidate limits and threshold alternatives. This evaluates retrieval; it does not train a model.

## 16. Acceptance Criteria

The RAG path is acceptable when:

1. Query embeddings are compatible with stored BGE-M3 vectors.
2. The persistent service loads lazily and fails without disabling SQL.
3. Every search is restricted to one active source model.
4. Entity and relationship searches run separately and only when requested.
5. Configurable calibrated thresholds exclude weak evidence.
6. Combined searches use documented rank fusion rather than raw-score averaging.
7. Retrieved relationships hydrate all direct endpoint entities.
8. Results retain canonical IDs for SQL/hybrid/viewer use.
9. RAG results are never described as exhaustive counts without SQL evidence.
10. Tests and calibration reports demonstrate retrieval behavior and isolation.

## 17. Task 06 Implementation Notes

Task 06 (`tasks/task06_done.md`) implemented this specification against the
live database and the real BGE-M3 embedding service:
`backend/app/query/rag/{schemas,embedding_service,search,thresholds,fusion,
hydration,relationship_expansion,errors}.py`. Full command reference,
per-question calibration detail, and two documented negative findings
(doors/windows are not well-separated by this embedding model on this
project's template text; a single-specific-entity target is not guaranteed
to outrank a closely related record) are in `docs/architecture_v004.md`.

Threshold profiles were calibrated empirically against this project's real
`rag_documents` and an 8-question set
(`backend/app/evaluation/rag_calibration_v001.jsonl`), not asserted:
`default_v001 = 0.50`, `high_precision_v001 = 0.55` (documented alternative).

`rag_documents` was read-only throughout — verified unchanged (10,462 rows:
6,989 entity + 3,473 relationship, identical to the Task 03 baseline) — and
every RAG query executes through the `bim_rag_query_ro` read-only role
(Task 05), which cannot write regardless of application code. Query vectors
are plain Python lists, never persisted; a forced embedding-service failure
was verified not to affect the SQL/graph paths in the same session.

351/351 tests pass (300 pre-existing + 51 new: `backend/tests/query_rag`
plus 6 new files under `backend/tests/query_live`). `ruff format`/`ruff
check` clean.

```text
RAG query path: IMPLEMENTED AND VALIDATED
Stored corpus vectors: UNCHANGED
Query vectors persisted: NO
OpenAI orchestration: NOT EXECUTED
Hybrid path: NOT IMPLEMENTED
```

---

## Task 16 amendment — Threshold-free candidate retrieval

Task 16 removes the hard similarity threshold as an **acceptance gate** for the universal hybrid
pipeline. Where this conflicts with v004 §8 threshold behavior for the new probe path, this governs.

- Every enabled semantic/RAG probe returns a bounded **top-k** set; no candidate is discarded for
  being below `default_v001`/`high_precision_v001`. Similarity and per-kind rank remain **internal**
  (ordering, diagnostics, evaluation, trace) and are never surfaced to the user.
- `passed_threshold`/`sufficient_evidence` no longer control evidence inclusion in the probe path.
  Evidence uses candidate/relevance concepts instead: `retrieved_candidate`, `rank`,
  `candidate_evidence`, `accepted_by_answerer`, `rejected_by_answerer`. The old fields and
  `thresholds.py` remain only for backward-compatible tests/diagnostics.
- The answerer may reject every retrieved candidate and state that no relevant model evidence exists.
- Embedding failure still degrades truthfully and leaves exact SQL usable; query/profile vectors are
  never persisted.

---

## Task 17 amendment — RAG as bounded per-facet candidate groups

Task 17 runs entity/relationship RAG per conceptual facet only when the query-only policy requested
it (never because Stage-3 candidates are weak/strong). RAG enriches an exact class group with ranked
representative examples, or forms a bounded `entity_id_set` RAG-only group (coverage=bounded) — never
an exact total. SQL remains authoritative when both refer to the same canonical group (§4 dedup).

## Task 23 amendment — RAG runs inside the resolved structured scope

When a facet resolved a constrained (compound) result, its semantic search is restricted to the
entities inside that scope. "Doors on the second floor that appear suitable for emergency egress"
first resolves the door-and-floor scope, then ranks only those entities for semantic relevance.

- The scope comes from `select_scope_entity_ids`, i.e. the same compiled predicate that produced the
  exact count and the viewer identities — RAG can never rank an entity outside the answer's scope.
- An empty scoped result stays empty. It never broadens to whole-model RAG; the group records that
  nothing semantically relevant was found within the requested scope.
- RAG remains bounded semantic evidence and never becomes an exact count. Scoping changes which
  candidates are eligible, not their authority.
- Facets with no conditions are unchanged: whole-model semantic search as in Task 17.
