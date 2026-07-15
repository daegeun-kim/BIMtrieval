# BIM RAG v001 Pipeline: Commands and Documentation

> **Note — superseded by Task 09 (three independent applications).**
> Paths and run commands in this document reflect the pre-split layout
> (`backend/src`, `api.app:app`, and the `bim_rag` compatibility shim). The
> authoritative current structure and commands are in [`README.md`](../README.md)
> and [`workflow.md`](../workflow.md): ingestion lives under `ingestion/`, the
> backend is a Poetry app run from `backend/` with `poetry run uvicorn app.main:app`,
> and the backend has no dependency on the ingestion `bim_rag` package.


## Environment

```bash
# Create (first time only)
conda env create -f environment.yml

# Activate
conda activate bim_rag

# Install package (editable)
pip install -e .
```

## Commands

### Full pipeline (structured import + vectorization) — EXECUTED

```python
from bim_rag.pipeline_structured import ifc_to_db

result = ifc_to_db(r"C:\path\to\model.ifc")
```

The only required argument is the IFC file path. `db_url` is loaded internally
from `.env` at runtime and never displayed. One call:

1. Fingerprints the IFC file (SHA-256) and creates/reuses its `ifc_source_models` row.
2. Imports every eligible entity (`IfcRoot` with `GlobalId`, not `IfcRelationship`) into `ifc_entities`.
3. Imports every `IfcRelationship` with a `GlobalId` into `ifc_relationships` + `relationship_members`.
4. Enables `pgvector` and creates the unified `rag_documents` table.
5. Generates deterministic `entity_description` / `relationship_description` text and
   `BAAI/bge-m3` embeddings, skipping any row whose source/text hash already matches a
   valid stored embedding.
6. Returns a structured report dict (see `src/bim_rag/reporting.py::build_unified_report`).

Reusable notebook: `notebooks/02_vectorize.ipynb`. Structured-only historical notebook
(Task 02-1, now superseded — the same `ifc_to_db()` call also vectorizes):
`notebooks/01_structured_import.ipynb`.

CLI equivalents (both run the same full pipeline):

```bash
bim-stage2       # python -m bim_rag.stage2_embed --ifc-path <path>
bim-pipeline     # python -m bim_rag.pipeline
```

### Staged CUDA smoke tests (`tasks/task03.md` crash-recovery requirement)

Run one stage at a time, inspecting the result before advancing:

```bash
python -m bim_rag.smoke_test --stage 1   # load BAAI/bge-m3 on CUDA, no encoding
python -m bim_rag.smoke_test --stage 2   # encode 1 synthetic document
python -m bim_rag.smoke_test --stage 3   # encode 1 real entity document
python -m bim_rag.smoke_test --stage 4   # encode 1 real relationship document
python -m bim_rag.smoke_test --stage 5   # encode a fixed batch of 4 mixed real documents
python -m bim_rag.smoke_test --stage 6   # encode + store <=32 real documents, batches of 4
```

## Database Schema

### Structured tables

**`ifc_source_models`** — one row per imported IFC file, keyed by SHA-256 `file_fingerprint`.

**`ifc_entities`** — one row per eligible entity. Unique: `(source_model_id, global_id)`.

**`ifc_relationships`** — one row per `IfcRelationship`. Unique: `(source_model_id, global_id)`.

**`relationship_members`** — one row per direct relationship endpoint (`role`, `member_order`,
endpoint STEP id/class/GlobalId/name, resolved `entity_id` when the endpoint is a known entity).

### Unified vector table: `rag_documents`

| Column | Type | Notes |
|--------|------|-------|
| id | SERIAL PK | |
| source_model_id | INTEGER FK NOT NULL | → ifc_source_models |
| source_kind | TEXT | `entity` or `relationship` |
| entity_id | INTEGER FK | → ifc_entities; XOR with relationship_id |
| relationship_id | INTEGER FK | → ifc_relationships; XOR with entity_id |
| document_type | TEXT | `entity_description` or `relationship_description` |
| document_text | TEXT | Generated natural-language text |
| text_truncated | BOOLEAN | True if char- or token-budget truncated |
| text_template_version | TEXT | `v001` |
| embedding_model | TEXT | `BAAI/bge-m3` |
| embedding_dim | INTEGER | 1024 |
| embedding | vector(1024) | L2-normalised; cosine HNSW index |
| generation_timestamp | TIMESTAMPTZ | |
| generation_metadata | JSONB | ifc_class, global_id, etc. |
| source_hash | TEXT | sha256 of source canonical JSON (entities) / canonical JSON + members (relationships) |
| text_hash | TEXT | sha256 of generated document_text |
| original_token_count | INTEGER | Token count before truncation |
| encoded_token_count | INTEGER | Token count actually encoded |

Unique per source reference: `(entity_id, document_type, text_template_version, embedding_model)`
and `(relationship_id, document_type, text_template_version, embedding_model)` (partial indexes).

`element_vectors` (the earlier entity-only design) is obsolete and is dropped automatically
if found empty; a populated `element_vectors` table blocks migration and is reported, never
silently dropped.

## Template System

- Entities: `src/bim_rag/templates.py`, `TEMPLATE_VERSION = "v001"`.
- Relationships: `src/bim_rag/rel_templates.py`, `TEMPLATE_VERSION = "v001"`.

Templates are modular per semantic feature; the same template is used for the same feature
across all IFC classes. No LLM calls — pure deterministic template expansion from canonical JSON.

Two truncation stages, both flagged via `text_truncated` (never silent):

1. **Char budget** (`MAX_TEXT_CHARS = 4000`): priority-ordered sentence selection.
2. **Token budget** (`src/bim_rag/text_limits.py`, `MAX_TOKENS = 2000`): applied only when a
   real tokenizer is supplied (the production embedding path), using the actual `BAAI/bge-m3`
   tokenizer — never estimated. Identity/GlobalId/name sentences are always kept.

## CLOCK_WATCHDOG_TIMEOUT (0x101) Crash-Recovery Mitigations

Two Windows crashes occurred during the original Task 03 vectorization run at CUDA batch
size 64. `src/bim_rag/config.py` and `src/bim_rag/stage2_embed.py` implement the recovery
mitigations required by `tasks/task03.md`:

- **Batch size**: `CUDA_BATCH_SIZE` (currently 8) is used for both entity and relationship
  batches. `validate_batch_size()` rejects anything outside `[1, MAX_CUDA_BATCH_SIZE]` (8) —
  batch size 64 is structurally impossible. The recovery run started at 4 and moved to 8 only
  after batch-4 staged smoke tests and a chunk of production embedding completed cleanly.
- **Thread limits**: `THREAD_LIMIT = 4`; `OMP_NUM_THREADS`, `MKL_NUM_THREADS` set to 4 and
  `TOKENIZERS_PARALLELISM=false` at `config.py` import time (before torch/tokenizers spin up
  thread pools), so tokenization and GPU inference can't saturate every logical core at once.
- **Token-aware limits**: see Template System above.
- **CUDA sync/error boundaries**: `_encode_batch()` wraps `encode()` in `torch.inference_mode()`,
  synchronizes CUDA immediately after each batch (so an async error attributes to the right
  batch), and re-raises immediately on any device/CUDA exception — no automatic retry.
- **Resumable, hash-skipped batches**: before encoding, each entity/relationship's deterministic
  `source_hash`/`text_hash` are compared against the stored row; a match with valid dim/embedding
  skips re-encoding entirely. Each batch is committed independently (`Session.begin()` per batch),
  so an interruption loses at most one in-flight batch and a rerun resumes rather than restarts.

## Idempotency Behavior

- **Source model**: keyed by SHA-256 fingerprint.
- **Entities / relationships / members**: keyed by `(source_model_id, global_id)` /
  `(relationship, role, order, endpoint_step_id)`; upserted every run (cheap structured re-import).
- **Vectors**: keyed by `(entity_id | relationship_id, document_type, text_template_version,
  embedding_model)`, additionally gated by `source_hash`/`text_hash` match for skip-vs-regenerate.
- A second unchanged `ifc_to_db()` run produces zero new/updated `rag_documents` rows — all
  are reported `*_skipped_valid`.

## Embedding Distance Metric

BGE-M3 produces cosine-similarity-optimal embeddings. Embeddings are L2-normalised before
storage (`normalize_embeddings=True`). The HNSW index uses `vector_cosine_ops`. Similarity
search uses cosine distance (`<=>` operator), always scoped by `source_model_id`.

## CUDA / CPU Behavior

Device is detected via `torch.cuda.is_available()` and reported explicitly in every run's
report (`execution_device`). Verified environment: RTX 5080 Laptop GPU, CUDA 12.8,
torch 2.11.0+cu128.

## Credential Safety

- `db_url` is loaded from `.env` at runtime via `python-dotenv`.
- Never printed, logged, or hard-coded.
- All database error messages are sanitized by `sanitize_db_error()` before display.
- If connection fails, the sanitized error is reported and execution stops.

## Source IFC

```
ifc_original/IFC Schependomlaan incl planningsdata.ifc
```

File is never modified. SHA-256 fingerprint is computed and stored as model identity.
843,172 total IFC entities; 6,989 eligible entities; 3,473 relationships; 17,668 relationship
members (all resolved).
