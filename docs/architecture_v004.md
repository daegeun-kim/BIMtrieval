# BIM RAG v004 RAG Query Path: Commands and Documentation

Governed by `specs/spec_v004_rag_query_path.md` (Task 06). Implements
source-scoped semantic search over the existing `rag_documents` table
(10,462 rows, unchanged since Task 03), independent of OpenAI orchestration.
Validated by supplying typed RAG plans directly.

## Package layout

```text
backend/src/query/rag/
├── schemas.py                RagSearchPlan, RagCandidate, FusedCandidate, RagSearchResult
├── embedding_service.py       lazy persistent BGE-M3 singleton (state machine, batch-1, no persistence)
├── search.py                   compatibility check + parameterized pgvector search + run_rag_search()
├── thresholds.py                named profiles: default_v001=0.50, high_precision_v001=0.55
├── fusion.py                     reciprocal_rank_fusion(), k=60 default
├── hydration.py                   RagSearchResult -> evidence + selected-object summaries
├── relationship_expansion.py      direct endpoint expansion (bounded, no recursion)
└── errors.py                       EmbeddingServiceUnavailableError, IncompatibleEmbeddingError

backend/src/evaluation/
└── rag_calibration_v001.jsonl   8-question calibration set (real classes/IDs from this model)

backend/tests/query_rag/        schema + RRF + threshold unit tests (no DB, no model load) — 16 tests
backend/tests/query_live/       + 6 new RAG test files — 51 tests (embedding service loads once
                                  per session via a session-scoped fixture in conftest.py)
```

## Running tests

```bash
pytest    # 351 tests total: 300 pre-existing + 51 new. First query_live run pays a
          # one-time ~13s BGE-M3 GPU load; subsequent tests reuse the loaded model.
```

## Embedding service

Lazy, persistent, process-wide singleton (`query.rag.embedding_service.get_embedding_service()`).
Verified live on this machine (RTX 5080 Laptop, CUDA):

- Load time: ~13s (first call only).
- Single-query encode: ~0.8s cold, ~0.01s once warm.
- Output: 1024-dim, L2 norm = 1.0 exactly (confirms `normalize_embeddings=True` matches the
  stored corpus's normalization).
- A bad model name fails permanently (`EmbeddingServiceState.FAILED`, no auto-retry, no silent
  substitution) and raises `EmbeddingServiceUnavailableError` — verified that
  `query.sql.entities.count_entities` (and by extension the whole SQL/graph path) keeps working
  in the same process/session immediately afterward.

Batch size is always 1 — a categorically lighter workload than the batch-8 corpus embedding that
caused the Task 03 `CLOCK_WATCHDOG_TIMEOUT` crashes. The same conservative controls
(`bim_rag.config.THREAD_LIMIT`, `torch.inference_mode()`, explicit CUDA synchronize, no automatic
retry) are reapplied here, reimplemented locally rather than importing `bim_rag.stage2_embed`'s
private helpers across a package boundary. No crash or instability occurred during this task's
GPU work.

## Calibration

`backend/src/evaluation/rag_calibration_v001.jsonl` — 8 questions with class-/ID-grounded
relevance judgments, all verified against real live data (exact SQL counts, not invented). Full
precision/recall sweep at 8 threshold candidates (0.30–0.65), computed once against the real
embedding service and live `rag_documents`:

| threshold | avg precision | avg recall@top-50 | questions with ≥1 passed |
|---|---|---|---|
| 0.30–0.45 | 0.40 | 0.271 | 8/8 |
| 0.50 | 0.44 | 0.271 | 8/8 |
| 0.55 | 0.80 | 0.194 | 5/8 |
| 0.60 | 1.00 | 0.050 | 1/8 |
| 0.65 | — (no candidates) | 0.000 | 0/8 |

Per-question detail (kind, similarity range of relevant hits):

- **"Show me all doors"** (entity, 205 relevant): precision 1.0 at every threshold up to 0.55;
  all 50 top-k candidates were `IfcDoor` at similarity ~0.50–0.56.
- **"Property definition relationship"** (relationship, 3228 relevant): precision 1.0 up to 0.55.
- **"Task assignment schedule relationship"** (relationship, 125 relevant): precision 1.0 up to
  0.60.
- **"Building storey containment relationship"** (relationship, 1 relevant — the single real
  `IfcRelContainedInSpatialStructure` row): correctly ranked #1 at similarity 0.576; precision
  1.0 exactly at threshold 0.55 (only 1 candidate passes).
- **"Spatial aggregation relationship"** (relationship, 4 relevant): only reaches similarity
  ~0.50–0.52; precision drops to 0 by 0.55 (this small class has genuinely lower peak similarity).
- **"Show me load bearing walls"** (entity, 880 relevant): peak similarity only ~0.50; the
  IfcWall class is not as tightly clustered as IfcDoor in this embedding space, given each wall's
  document text is dominated by dozens of ArchiCAD property key/value pairs rather than identity
  text.
- **"Show me all windows"** (entity, 259 relevant) — **documented negative finding**: this query's
  top-15 nearest neighbors are almost entirely `IfcDoor` entities (similarity ~0.50–0.51), not
  `IfcWindow`. BGE-M3 + this project's deterministic template text does not reliably separate
  doors from windows as retrieval targets; a targeted SQL filter (`ifc_class = 'IfcWindow'`, Task
  05) remains authoritative for this kind of question, and hybrid orchestration (v005) should
  prefer SQL filtering over RAG when the user names an exact IFC class.
- **"Roof tiles task"** (entity, 1 relevant — the specific `IfcTask` named "Dakpannen",
  entity_id=1) — **documented negative finding**: the top result was a different, semantically
  related task ("Dakbedekking platte daken" = "roof covering flat roofs", similarity 0.543) —
  cross-lingual matching (English query, Dutch task names) works in principle, but a
  single-specific-entity target is not guaranteed to outrank a closely related but distinct
  record. RAG retrieval is candidate-based, not a guaranteed exact match (spec_v004 §12).

**Chosen profiles**: `default_v001 = 0.50` (keeps full observed recall at each question's peak
similarity band while excluding the long weak tail below it) and `high_precision_v001 = 0.55`
(documented alternative — trades recall for precision; loses the walls/aggregation/windows
classes entirely at this threshold, so only appropriate when false positives are especially
costly).

## Verification performed

- 351/351 tests pass (300 pre-existing + 51 new: 16 `query_rag` no-DB unit tests, 51 `query_live`
  RAG tests spanning embedding-service lifecycle, search, fusion via unit tests, relationship
  expansion, selected-object context, degraded mode, and calibration). `ruff format`/`ruff check`
  clean.
- `rag_documents` row count confirmed unchanged: 10,462 (6,989 entity + 3,473 relationship),
  identical to the Task 03 baseline; an aggregate `text_hash` digest was recorded as a stability
  fingerprint.
- No code path in `query/rag/*` contains an `INSERT`/`UPDATE` against `rag_documents` — verified
  by direct source inspection (`test_query_vector_is_a_plain_list_not_persisted_anywhere`) and by
  the fact that every query in this task's package runs through the `bim_rag_query_ro` read-only
  role (Task 05), which cannot write regardless.
- Degraded-mode guarantee verified directly: forcing `EmbeddingService` to fail (bad model name)
  raises cleanly, and `query.sql.entities.count_entities` immediately succeeds afterward in the
  same session — SQL/graph paths are unaffected by a RAG failure.

## Stop condition (tasks/task06.md)

```text
RAG query path: IMPLEMENTED AND VALIDATED
Stored corpus vectors: UNCHANGED
Query vectors persisted: NO
OpenAI orchestration: NOT EXECUTED
Hybrid path: NOT IMPLEMENTED
```
