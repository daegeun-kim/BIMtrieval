# BIM RAG v001 Pipeline: Commands and Documentation

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

### Stage 1 — Structured IFC Import (NOT EXECUTED)

```bash
conda activate bim_rag
bim-stage1
# or: python -m bim_rag.stage1_import
```

Stage 1 will:
1. Load `db_url` from `.env` at runtime (never displayed)
2. Compute SHA-256 fingerprint of the source IFC file
3. Scan IFC model and report entity counts
4. Create `ifc_source_models` and `ifc_entities` tables in PostgreSQL
5. Extract canonical JSON for every eligible entity (IfcRoot with GlobalId, not IfcRelationship)
6. Upsert entity records idempotently (keyed by `source_model_id + global_id`)
7. Print a Stage 1 reconciliation report

### Stage 2 — pgvector Setup and Embedding Generation (NOT EXECUTED)

```bash
conda activate bim_rag
bim-stage2
# or: python -m bim_rag.stage2_embed
```

Stage 2 will (requires Stage 1 to be complete):
1. Load `db_url` from `.env` at runtime
2. Execute `CREATE EXTENSION IF NOT EXISTS vector` in the database
3. Create `element_vectors` table with `vector(1024)` column and HNSW cosine index
4. Verify Stage 1 data is present (refuses if absent)
5. Detect CUDA; use RTX 5080 GPU if available, CPU otherwise (reported explicitly)
6. Load `BAAI/bge-m3` model
7. Generate v001 element-description text from each entity's canonical JSON
8. Embed text in batches of 32; L2-normalize embeddings before storage
9. Upsert `element_vectors` rows idempotently
10. Print a Stage 2 reconciliation report

### Convenience: Both Stages in Sequence (NOT EXECUTED)

```bash
bim-pipeline
# or: python -m bim_rag.pipeline
```

Runs Stage 1 then Stage 2. Both stages remain independently callable.

## Database Schema

### Stage 1 Tables

**`ifc_source_models`**

| Column | Type | Notes |
|--------|------|-------|
| id | SERIAL PK | |
| file_path | TEXT | Absolute path to IFC file |
| file_name | TEXT | Filename only |
| file_fingerprint | TEXT UNIQUE | SHA-256 of IFC file bytes |
| ifc_schema | TEXT | e.g. "IFC2X3", "IFC4" |
| import_timestamp | TIMESTAMPTZ | |
| total_entity_count | INTEGER | |
| eligible_entity_count | INTEGER | |
| excluded_relationship_count | INTEGER | |
| extraction_metadata | JSONB | class_counts, extraction_version |

**`ifc_entities`**

| Column | Type | Notes |
|--------|------|-------|
| id | SERIAL PK | |
| source_model_id | INTEGER FK | → ifc_source_models |
| global_id | TEXT | IFC GlobalId |
| step_id | INTEGER | STEP entity #id |
| ifc_class | TEXT | e.g. "IfcWall" |
| canonical_json | JSONB | Full canonical representation |
| import_timestamp | TIMESTAMPTZ | |
| extraction_warnings | JSONB | Per-entity extraction warnings |

Unique constraint: `(source_model_id, global_id)`

### Stage 2 Table

**`element_vectors`**

| Column | Type | Notes |
|--------|------|-------|
| id | SERIAL PK | |
| entity_id | INTEGER FK | → ifc_entities |
| document_type | TEXT | Always "element_description" |
| document_text | TEXT | Generated natural-language text |
| text_truncated | BOOLEAN | True if text was priority-truncated |
| text_template_version | TEXT | "v001" |
| embedding_model | TEXT | "BAAI/bge-m3" |
| embedding_dim | INTEGER | 1024 |
| embedding | vector(1024) | L2-normalised; cosine HNSW index |
| generation_timestamp | TIMESTAMPTZ | |

Unique constraint: `(entity_id, document_type, text_template_version, embedding_model)`

## Template System

File: `src/bim_rag/templates.py`
Version: `v001` (`TEMPLATE_VERSION = "v001"`)

Templates are modular per semantic feature. Same template is used for the same
feature across all IFC classes. Priority ordering for truncation (highest first):
identity → name → global_id → predefined_type → object_type → tag → ... → properties → quantities.

Max text length: 4000 characters. Truncation is flagged (`text_truncated=True`); never silent.

## Idempotency Behavior

- **Source model**: keyed by SHA-256 fingerprint. Re-running same file skips model insertion, updates counts.
- **Entities**: keyed by `(source_model_id, global_id)`. Existing entities are updated with current canonical JSON.
- **Vectors**: keyed by `(entity_id, document_type, text_template_version, embedding_model)`. Existing vectors are updated with current text/embedding.
- Re-running unchanged source with same extraction/template/model versions is safe and idempotent.

## Embedding Distance Metric

BGE-M3 produces cosine-similarity-optimal embeddings. Embeddings are L2-normalised
before storage (`normalize_embeddings=True` in SentenceTransformer.encode). The HNSW
index uses `vector_cosine_ops`. Similarity search uses cosine distance (`<=>` operator).

## CUDA / CPU Behavior

Stage 2 automatically detects CUDA at runtime via `torch.cuda.is_available()`.
- If CUDA is available: uses RTX 5080 Laptop GPU (CUDA 12.8, torch 2.11.0+cu128)
- If CUDA is unavailable: falls back to CPU and reports this explicitly in output and report

## Credential Safety

- `db_url` is loaded from `.env` at runtime via `python-dotenv`
- Never printed, logged, or hard-coded
- All database error messages are sanitized by `sanitize_db_error()` before display
- If connection fails, the sanitized error is reported and execution stops

## Source IFC

```
ifc_original/IFC Schependomlaan incl planningsdata.ifc
```

File is never modified. SHA-256 fingerprint is computed and stored as model identity.

## Stage DDL Files

- `src/bim_rag/schema/stage1_ddl.sql` — Stage 1 tables (no vector)
- `src/bim_rag/schema/stage2_ddl.sql` — pgvector extension + element_vectors table
