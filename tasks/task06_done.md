# Task 06: Implement and Validate the RAG Query Path

## Prerequisites

Require:

```text
tasks/task05_done.md
specs/spec_v002_query_architecture.md
specs/spec_v004_rag_query_path.md
```

If Task 05 is incomplete, stop.

## Objective

Implement source-scoped semantic search over existing `rag_documents`, independently of OpenAI orchestration, using direct typed RAG plans.

## Required work

1. Implement the lazy persistent `BAAI/bge-m3` query-embedding service.
2. Validate model, dimension, normalization, and stored-vector compatibility.
3. Use batch size one and conservative token/thread/device controls; never invoke corpus vectorization.
4. Implement typed RAG plans with entity/relationship kind selection, top-k, visible limit, threshold profile, and endpoint expansion.
5. Implement source-model-scoped pgvector cosine search.
6. Search entity and relationship descriptions separately.
7. Implement configurable threshold profiles and exclude below-threshold records from factual evidence.
8. Implement reciprocal-rank fusion with initial configurable constant 60.
9. Hydrate accepted documents from structured tables.
10. Expand every direct endpoint of accepted relationships, retaining unresolved endpoints and primary/context roles.
11. Support up to five selected-object summaries.
12. Preserve SQL availability when the embedding service is unavailable.
13. Create a calibration/evaluation dataset and report threshold alternatives, precision, and recall.

## Authorized execution

Claude may load BGE-M3, generate ephemeral query vectors, perform read-only pgvector and structured hydration queries, and run calibration searches. It may update code/tests/evaluation files.

## Prohibited actions

- Do not regenerate, update, or delete stored document embeddings.
- Do not store query vectors.
- Do not perform corpus embedding.
- Do not call OpenAI.
- Do not implement hybrid orchestration or frontend.
- Do not run unscoped cross-model RAG.
- Do not silently lower thresholds or substitute embedding models.

## Required validation

- lazy service lifecycle and degraded state
- batch-one normalized 1024-dimensional query embeddings
- query vectors remain memory-only
- strict source-model isolation
- entity-only, relationship-only, and combined retrieval
- relationship search disabled when not requested
- top-k/visible limits and threshold exclusion
- RRF correctness and score preservation
- endpoint hydration and primary/context classification
- incompatible-vector rejection
- selected-object limit
- no-result/weak-result behavior
- SQL path remains usable during simulated RAG failure

Run representative live semantic questions and record canonical results without claiming semantic retrieval is exhaustive.

## Completion report

Report files, model/device configuration, searches, threshold calibration, precision/recall, endpoint expansion, degraded-mode checks, and explicit confirmation:

```text
RAG query path: IMPLEMENTED AND VALIDATED
Stored corpus vectors: UNCHANGED
Query vectors persisted: NO
OpenAI orchestration: NOT EXECUTED
Hybrid path: NOT IMPLEMENTED
```

Rename to `task06_done.md` only when all criteria pass.

