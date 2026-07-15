# Specification v001: IFC to PostgreSQL with Element-Description Vectors

## Current architecture amendment (Task 09 and frontend planning)

This specification remains authoritative for the ingestion application's behavior. After
Task 09, all active ingestion code and assets are owned by the independent `ingestion/`
project:

```text
ingestion/
├── environment.yml
├── pyproject.toml
├── ifc_original/
├── notebooks/
├── src/bim_rag/
└── tests/
```

Any later examples using root `src/bim_rag/`, `tests/`, `notebooks/`, `ifc_original/`,
`environment.yml`, or `pyproject.toml` must be read using the corresponding path under
`ingestion/`. Those old paths document the original implementation milestone; they are not
active project locations.

The ingestion application is independent from `backend/` and `frontend/`. It may write the
five BIM data tables and stored vectors, but it must not import or invoke backend/frontend
code. The backend reads the database and never imports `bim_rag`.

PostGIS geometry extraction remains deferred to a separate future specification. It is not
part of v001 or the frontend MVP. Browser rendering uses an optimized viewer artifact rather
than reconstructing the model directly from PostGIS. Viewer-asset preparation is governed by
`spec_v006_frontend_application.md` and does not change the v001 database/vector pipeline.

## 1. Purpose

Implement the first isolated data-ingestion milestone for the BIM RAG project:

1. Create and use a persistent Anaconda environment named `bim_rag`.
2. Parse the specified IFC model with IfcOpenShell.
3. Store structured, object-intrinsic IFC data in the user's existing PostgreSQL database.
4. Enable and use pgvector in that existing database.
5. Generate exactly one embedding feature: an element-description vector.
6. Validate the source IFC, structured import, text generation, and vector import.

This specification covers IFC ingestion and vector storage only. It does not include an API, user interface, chatbot, LLM routing, PostGIS geometry, spatial analysis, or relationship-aware retrieval.

## 2. Authoritative Inputs

### 2.1 Source IFC

Use this exact file:

```text
C:\Users\kdgki\Desktop\MSCDP\Projects\BIM_RAG\ingestion\ifc_original\IFC Schependomlaan incl planningsdata.ifc
```

The source IFC is authoritative and must never be edited, rewritten, repaired in place, renamed, or moved.

### 2.2 Database connection

The user has already created the target PostgreSQL database. Do not create another database.

The connection address is stored under the lowercase variable `db_url` in the repository `.env` file. Claude must not open, inspect, print, copy, log, or expose the `.env` contents. Programs created for this project may load `db_url` from `.env` at runtime.

Requirements:

- Never hard-code the database URL or credentials.
- Never print the resolved URL.
- Sanitize database errors so credentials cannot appear in logs or reports.
- Create the required extension, schema objects, and tables inside the database referenced by `db_url`.
- Do not create a local replacement database or silently use another connection when access fails.
- If `db_url` is unavailable, the connection fails, or required database privileges are missing, stop and report the failure to the user.

## 3. Environment

Create a new persistent Anaconda environment named `bim_rag` using Python 3.11. This environment does not exist yet and is intended to be reused throughout later project development.

Install all required dependencies into this environment, including at minimum:

- IfcOpenShell
- PostgreSQL Python driver
- SQL/database migration support if used
- pgvector Python integration if used
- `python-dotenv` or an equivalent runtime `.env` loader
- PyTorch with CUDA support compatible with the installed RTX 5080 Laptop GPU and driver
- Sentence Transformers
- `BAAI/bge-m3`

Use reproducible dependency declarations appropriate for the repository. Do not recreate or delete the environment on normal subsequent runs. Setup must detect an existing `bim_rag` environment and reuse it.

Before embedding, verify CUDA from within `bim_rag`. Use the RTX 5080 Laptop GPU when CUDA is available. A CPU fallback is allowed, but it must be explicit in the run output and validation report. If CUDA installation or detection fails, report the exact sanitized condition rather than claiming GPU execution.

## 4. Embedding Definition

Use the fixed local Sentence Transformers model:

```text
BAAI/bge-m3
```

The embedding dimension is 1024. Store embeddings in a pgvector column compatible with:

```sql
vector(1024)
```

Record the embedding model name, dimension, text-template version, and generation time with every vector record or in normalized metadata that unambiguously applies to it.

Exactly one vector-document type is permitted in this version:

```text
element_description
```

Do not generate relationship, adjacency, space-summary, storey-summary, material-summary, project-summary, or other embedding types.

## 5. Entity Inclusion Rules

Create one structured entity record and one element-description vector for every non-relationship IFC entity that:

1. Is an `IfcRoot` or subtype with a valid `GlobalId`.
2. Is not an `IfcRelationship` or subtype.

This deliberately includes more than physical `IfcElement` objects. It includes eligible entities such as spatial objects, storeys, types, systems, property definitions, and other non-relationship IFC-rooted entities with GlobalIds.

Exclude:

- Every `IfcRelationship` subtype, even when it has a GlobalId.
- IFC entities without a GlobalId.
- Anonymous low-level representation entities such as points, directions, placements, profiles, and representation items that are not independently eligible under the rule above.

Do not silently discard an otherwise eligible entity because it lacks optional fields. Preserve it with null/empty optional data and report extraction limitations.

## 6. Information Boundary

The vector must describe the entity itself, not its relationships with other entities. Apply the following counterfactual test:

> Include information that still describes the entity if it were placed in an otherwise empty model with no neighboring or connected entities.

### 6.1 Include

Extract and preserve all practical scalar, intrinsic, and resolved descriptive information available for an eligible entity, including where applicable:

- STEP/entity ID for traceability within this source file
- GlobalId
- exact IFC class
- predefined type
- name
- description
- object type
- tag and identification fields
- long name or composition type
- intrinsic IFC attributes
- property sets and their values
- element quantities and their values
- type designation and type-defined specifications
- assigned material names and material specifications
- resolved storey/floor name when applicable
- placement and elevation values that intrinsically locate the object
- nominal dimensions
- derived dimensions when they can be deterministically calculated from the object's own representation
- units and normalized units
- classifications or codes that describe the entity
- representation metadata useful for describing the entity without serializing full geometry

Resolved storey, type, material, property, and quantity facts may be included even when IFC relationship traversal is technically required to obtain them. Store only the resolved descriptive fact in the entity JSON and text; do not embed the relationship record or relationship graph.

### 6.2 Exclude

Do not include:

- adjacency or neighboring elements
- connected elements
- spaces served, bounded, or connected by the entity
- doors connecting two spaces
- element-to-element containment or aggregation lists
- parent/child element lists
- systems containing other objects
- relationship entity IDs or GlobalIds
- relationship descriptions
- graph paths
- full recursive serialization of referenced IFC entities
- full meshes, vertex arrays, face arrays, or binary geometry
- PostGIS geometry

Storey/floor may be included as a resolved descriptive attribute. Do not include broader containment paths or lists of contained objects.

## 7. Canonical JSON Representation

Each eligible entity must have a canonical JSON-compatible representation stored in PostgreSQL as `jsonb`. The representation must be deterministic, finite, non-recursive, and safe to serialize.

Design a documented schema that supports heterogeneous IFC classes without discarding source information. At minimum, distinguish:

- identity and IFC classification
- common scalar attributes
- location/placement values
- dimensions
- type specifications
- materials
- property sets
- quantities
- classifications
- representation metadata
- source and extraction metadata

Requirements:

- Preserve the original value and unit when available.
- Also store a normalized numeric value and normalized unit where reliable conversion is possible.
- Preserve booleans, numbers, strings, lists, nulls, and structured values with their correct types.
- Use stable ordering for keys and generated feature traversal.
- Do not flatten different property sets into colliding keys.
- Preserve property-set and quantity-set names.
- Detect unsupported IFC value types, serialize them safely when possible, and report them.
- Prevent cycles and uncontrolled recursive expansion.
- Do not claim that derived dimensions came directly from IFC attributes; label provenance such as `attribute`, `property`, `quantity`, or `derived`.

The complete canonical JSON is the loss-minimizing structured record. The generated natural-language text may be selective to prevent noisy or excessively long embeddings, but it must be generated only from the canonical JSON.

## 8. Natural-Language Template System

Create a separate, maintainable template module/file dedicated to converting canonical entity JSON into natural-language text.

Use modular feature templates, not one hard-coded paragraph and not a separate full template for every IFC class. The same semantic feature must use the same wording pattern across all entity classes.

Examples of feature-level behavior:

```text
identity: "This entity is an {ifc_class} named {name}."
width: "The width of {entity_reference} is {value} {unit}."
height: "The height of {entity_reference} is {value} {unit}."
material: "The material of {entity_reference} is {material}."
property: "Its {property_name} property in {property_set} is {value}."
quantity: "Its {quantity_name} quantity in {quantity_set} is {value} {unit}."
global_id: "Its IFC GlobalId is {global_id}."
```

The examples communicate intent, not mandatory exact prose. Define a stable template for each supported feature category and ensure identical features use identical templates regardless of IFC class.

Template requirements:

- Version the template set, beginning with a clear v001 identifier.
- Make templates directly testable.
- Omit sentences for missing values rather than emitting `None`, `null`, or empty prose.
- Render values deterministically and consistently.
- Always include IFC class and GlobalId.
- Include name when present.
- Use normalized units in prose where available and retain unambiguous unit labels.
- Use stable feature ordering.
- Deduplicate repeated equivalent facts.
- Do not invent, infer, summarize, or classify facts using an LLM.
- Do not insert relationship information prohibited by Section 6.
- Escape or normalize unusual whitespace/control characters without changing meaning.
- Apply a documented maximum input length compatible with `BAAI/bge-m3`.
- If complete text exceeds the selected limit, use a deterministic priority/truncation policy and record that truncation occurred. Never silently truncate.

The text generator must be ordinary deterministic Python. Do not call an LLM to convert JSON into prose.

## 9. PostgreSQL and pgvector

Use the existing database referenced by `db_url`.

Attempt:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

If the PostgreSQL server lacks pgvector binaries or the connected role lacks permission, stop and tell the user. Do not attempt operating-system-level PostgreSQL modification, do not create another database, and do not substitute a different vector database.

Design the minimum normalized schema needed to preserve source-model identity, eligible IFC entities, canonical JSON, generated text, and embeddings. Multiple tables are expected where they improve integrity. At minimum, the design must unambiguously represent:

- imported IFC source/model metadata and source fingerprint
- eligible IFC entity identity
- canonical entity JSON
- element-description document text
- `vector(1024)` embedding
- embedding model and template version
- extraction/import timestamps and status

Use database constraints and indexes appropriate for:

- model identity
- source GlobalId uniqueness within a model
- IFC class filtering
- document-type enforcement
- foreign-key integrity
- vector similarity search

Select and document the pgvector distance metric appropriate for `BAAI/bge-m3`, normalize embeddings if required by that choice, and use the same policy during storage and search validation.

Do not add PostGIS or spatial geometry in this version.

## 10. Idempotency and Transactions

The import must be safely repeatable without duplicate entities or vectors.

Requirements:

- Identify the source file using a deterministic cryptographic fingerprint in addition to its path/name.
- Enforce uniqueness of an entity by source model plus GlobalId.
- Re-running an unchanged source with the same extraction, template, and model versions must not create duplicate records.
- Changed JSON must regenerate text and its embedding.
- Changed template version or embedding model must regenerate affected text/embeddings as appropriate.
- Use transactions so a failed import does not leave a falsely successful partial run.
- Preserve useful failure diagnostics without exposing secrets.
- Do not delete unrelated database contents.
- Scope replacement/update operations strictly to this imported source model.

Document the chosen upsert/reconciliation behavior clearly.

## 11. Source IFC Validation

Treat “clean IFC” as validation and transparent reporting, not mutation of the IFC.

Before or during import, detect and report at minimum:

- IFC schema/version
- file fingerprint
- total IFC entity count
- count of entities with GlobalIds
- count of eligible non-relationship entities
- count of excluded relationship entities with GlobalIds
- count by IFC class
- missing or invalid GlobalIds
- duplicate GlobalIds within the file
- malformed or unreadable values
- property/quantity extraction failures
- entities that fail canonical JSON generation
- unsupported values or dimensions
- missing or inconsistent units
- natural-language truncations
- embedding failures

Do not silently “repair” or discard questionable data. Fail the overall import for conditions that compromise identity, referential integrity, deterministic output, or complete eligible-entity coverage. Warnings may be used for absent optional data.

## 12. Required Verification

Claude must execute and document verification, not merely write implementation code.

### 12.1 Environment verification

- `bim_rag` exists and uses Python 3.11.
- Required packages import successfully.
- IfcOpenShell reports its version.
- PyTorch reports CUDA availability, device name, and execution device without exposing unrelated system information.
- Sentence Transformers can load `BAAI/bge-m3`.

### 12.2 IFC-to-database reconciliation

- Eligible IFC count equals stored entity count for this source model.
- Eligible IFC count equals `element_description` document count.
- Eligible IFC count equals non-null embedding count.
- Counts by IFC class reconcile between IFC extraction and PostgreSQL.
- No duplicate `(source_model, global_id)` records exist.
- No eligible `IfcRelationship` vectors exist.
- No prohibited relationship content appears in audited sample documents.

### 12.3 Structured-data samples

Inspect representative canonical JSON and generated text for several different classes, including when present:

- a physical building element
- a door or window
- a storey or other spatial object
- a type object
- another non-physical eligible entity

Confirm properties, quantities, units, provenance, null handling, and deterministic ordering.

### 12.4 Embedding verification

- Every stored embedding has dimension 1024.
- No embedding contains invalid numeric values.
- Re-embedding identical text produces acceptably deterministic results under the documented runtime policy.
- Run several sample vector similarity queries and report the query text, returned GlobalIds/classes/names, and distances/scores.
- Similarity validation must be read-only and must not add additional document types.

### 12.5 Idempotency verification

Run the import a second time against the unchanged source and verify:

- no duplicate entities or documents are created
- counts remain unchanged
- unchanged rows are not unnecessarily regenerated, where supported by the implementation
- the run completes successfully

## 13. Execution Outputs and Documentation

Provide enough documentation for the user or Claude to repeat the process later using the persistent `bim_rag` environment.

Document:

- environment creation and activation commands
- dependency installation/reproduction
- ingestion command
- validation command
- schema/migration command if separate
- template file location and template-version policy
- database tables and important columns
- idempotency behavior
- CUDA/CPU selection behavior
- sanitized failure recovery guidance

Generate a concise machine-readable or Markdown validation report containing reconciliation counts, warnings, failures, execution device, model/version information, and sample search results. Do not include database credentials or the resolved database URL.

## 14. Explicit Non-Goals

Do not implement any of the following under this specification:

- PostGIS or geometry columns
- mesh storage or spatial queries
- relationship vectors
- adjacency, connectivity, or space-boundary retrieval
- multiple vector features or document types
- hosted embedding APIs
- OpenAI embeddings
- LLM-generated descriptions
- arbitrary SQL generation by an LLM
- FastAPI
- Streamlit
- chatbot or question-answering interface
- LangChain or LlamaIndex orchestration
- a separate vector database
- creation of a new PostgreSQL database
- modification or repair of the source IFC

## 15. Acceptance Criteria

This specification is complete only when all of the following are true:

1. The persistent `bim_rag` environment exists with Python 3.11 and reproducible dependencies.
2. The exact source IFC opens successfully without being modified.
3. The program connects only to the existing database addressed by runtime `db_url`.
4. The `vector` extension is enabled in that database.
5. Every eligible non-relationship IFC entity with a GlobalId has exactly one structured database record.
6. Every such record has canonical finite JSON containing the available permitted intrinsic/resolved data.
7. Every such record has deterministic v001 natural-language text generated through reusable feature templates.
8. Every such text has exactly one `BAAI/bge-m3` 1024-dimensional `element_description` vector.
9. No `IfcRelationship` entity is vectorized and no prohibited relationship graph content is embedded.
10. IFC, database, document, and embedding counts reconcile, including counts by IFC class.
11. Representative JSON/text records and similarity searches are validated and reported.
12. A second unchanged run produces no duplicates and preserves counts.
13. CUDA usage is verified or CPU fallback is clearly reported.
14. Failures are surfaced without leaking `.env` contents or database credentials.
15. No out-of-scope API, UI, LLM routing, PostGIS, or additional vector feature is introduced.

## 16. Implementation Notes (Task 01)

Task 01 implemented the full v001 pipeline code without executing database operations.

### Environment

- Conda env `bim_rag` created with Python 3.11.15
- torch 2.11.0+cu128 (CUDA 12.8), RTX 5080 Laptop GPU confirmed
- sentence-transformers 5.6.0, ifcopenshell 0.8.5, sqlalchemy 2.0.51

### Files Created

| File | Purpose |
|------|---------|
| `environment.yml` | Reproducible conda environment definition |
| `pyproject.toml` | Package build + entry points |
| `src/bim_rag/config.py` | db_url loading + credential sanitization |
| `src/bim_rag/ifc_parser.py` | Eligibility, canonical JSON, model scanning |
| `src/bim_rag/templates.py` | v001 feature templates + text generator |
| `src/bim_rag/schema/models.py` | SQLAlchemy ORM models (Stage 1 + 2) |
| `src/bim_rag/schema/stage1_ddl.sql` | Stage 1 DDL (no vector) |
| `src/bim_rag/schema/stage2_ddl.sql` | Stage 2 DDL (pgvector + element_vectors) |
| `src/bim_rag/stage1_import.py` | Stage 1 entry point (`bim-stage1`) |
| `src/bim_rag/stage2_embed.py` | Stage 2 entry point (`bim-stage2`) |
| `src/bim_rag/pipeline.py` | Convenience orchestrator (`bim-pipeline`) |
| `src/bim_rag/reporting.py` | Reconciliation reports for both stages |
| `tests/` | 59 unit tests, 0 DB connections |
| `docs/pipeline_v001.md` | Command reference and schema documentation |

### Test Results

59/59 tests pass. Coverage includes eligibility, canonical JSON, template system,
idempotency logic, credential sanitization, and Stage 2 precondition checks.

### Deferred

- Stage 1 structured IFC import: **NOT EXECUTED**
- Stage 2 pgvector and vector generation: **NOT EXECUTED**

## 17. Execution Notes (Task 02)

Stage 1 executed and validated on 2026-07-11.

### Results

| Metric | Value |
|--------|-------|
| IFC schema | IFC2X3 |
| File fingerprint prefix | 57fafa59f03b18c0... |
| Total IFC entity count | 843,172 |
| Entities with GlobalIds | — |
| Eligible (non-relationship) | 6,989 |
| Excluded relationships | 3,473 |
| Duplicate GlobalIds | 0 |
| Imported (new) | 6,989 |
| Extraction failures | 0 |
| Extraction warnings | 0 |

### Entity Class Breakdown

| Class | Count |
|-------|-------|
| IfcPropertySet | 3,228 |
| IfcCovering | 1,214 |
| IfcWall | 648 |
| IfcSlab | 279 |
| IfcBuildingElementPart | 277 |
| IfcWindow | 259 |
| IfcWallStandardCase | 232 |
| IfcDoor | 205 |
| IfcBeam | 174 |
| IfcScheduleTimeControl | 125 |
| IfcTask | 125 |
| IfcRailing | 90 |
| IfcBuildingElementProxy | 86 |
| IfcColumn | 23 |
| IfcStair | 9 |
| IfcMember | 9 |
| IfcWorkPlan | 1 |
| IfcProject | 1 |
| IfcWorkSchedule | 1 |
| IfcSite | 1 |
| IfcBuildingStorey | 1 |
| IfcBuilding | 1 |
| **Total** | **6,989** |

### Validation Results

- Null/empty global_id rows: 0
- Duplicate (source_model_id, global_id): 0
- id uniqueness: 6989/6989 distinct
- element_vectors table exists: False
- pgvector extension installed: False
- IfcRel content in any sampled JSON: False
- All class counts reconcile between extraction and DB: True

### Idempotency Results (Second Run)

- ifc_source_models rows: 1 (no duplicate)
- ifc_entities rows: 6989 (no duplicate)
- Entities imported new: 0, updated: 6989
- All canonical ifc_entities.id values stable: True
- Duplicate (source_model_id, global_id): 0

### Status

```
Stage 1 structured IFC import: EXECUTED AND VALIDATED
Stage 2 pgvector and vector generation: NOT EXECUTED
```

---

## §18. Task 02-1 Execution Notes: Relationship Import

**Executed:** 2026-07-11

### Architecture additions

- `src/bim_rag/rel_parser.py` — relationship canonical JSON + member-row extraction
- `src/bim_rag/pipeline_structured.py` — public `ifc_to_db(ifc_path)` API (entities + relationships, no vectors)
- `src/bim_rag/schema/models.py` — `DbIfcRelationship` and `RelationshipMember` ORM classes added
- `src/bim_rag/schema/stage1_rel_ddl.sql` — additive migration for `ifc_relationships` and `relationship_members`
- `src/bim_rag/stage1_import.py` — rewritten as thin CLI wrapper calling `ifc_to_db()`; `--ifc-path` argument
- `src/bim_rag/reporting.py` — `build_structured_report()` added
- `notebooks/01_structured_import.ipynb` — executable notebook calling `ifc_to_db()`, no embedded logic

### Database migration

New tables created via `Base.metadata.create_all()` (additive, no existing tables dropped):
- `ifc_relationships` — UNIQUE(source_model_id, global_id)
- `relationship_members` — UNIQUE NULLS NOT DISTINCT (relationship_id, role, member_order, endpoint_step_id)

### Import results (first run)

| Metric | Value |
|---|---:|
| Source model id | 1 |
| SHA-256 prefix | 57fafa59f03b18c0 |
| IFC schema | IFC2X3 |
| Total IFC entity count | 843,172 |
| Eligible entities (non-rel) | 6,989 |
| IFC relationships with GlobalIds | 3,473 |
| `ifc_entities` rows | 6,989 (0 new, 6,989 updated) |
| `ifc_relationships` rows | 3,473 (3,473 new, 0 updated) |
| `relationship_members` rows | 17,668 |
| Resolved members | 17,668 (100%) |
| Unresolved members | 0 |
| Entity extraction failures | 0 |
| Relationship extraction failures | 0 |
| Extraction warnings | 0 |

### Relationship class breakdown

| IFC class | Count |
|---|---:|
| IfcRelDefinesByProperties | 3,228 |
| IfcRelAssignsTasks | 125 |
| IfcRelAssignsToProcess | 73 |
| IfcRelSequence | 42 |
| IfcRelAggregates | 4 |
| IfcRelContainedInSpatialStructure | 1 |
| **Total** | **3,473** |

### Validation results

- Orphaned relationship_members (no parent relationship): 0
- Members with invalid entity_id FK: 0
- Null global_id in ifc_relationships: 0
- Duplicate (source_model_id, global_id) in ifc_relationships: 0
- ifc_source_models count: 1
- element_vectors table created: False
- Entity baseline ifc_entities.id 1–15 match pre-change audit: True

### Idempotency results (second run)

- ifc_relationships rows: 3,473 (0 new, 3,473 updated)
- relationship_members rows: 17,668 (same)
- Resolved members: 17,668 (same)
- ifc_entities count: 6,989 (unchanged)
- No new source_model row created

### Test coverage

86/86 tests pass (59 existing + 27 new relationship tests in `tests/test_relationships.py`).

### Status

```
Existing IFC entities: PRESERVED AND VALIDATED
IFC relationships: IMPORTED AND VALIDATED
Relationship members: IMPORTED AND VALIDATED
Vector generation: NOT EXECUTED
Current tasks/task03.md: OUTDATED AND NOT EXECUTED
```

---

## §19. Task 03 Execution Notes: Unified rag_documents Vectorization + Crash Recovery

**Executed:** 2026-07-11 (recovery run, after two 0x101 CLOCK_WATCHDOG_TIMEOUT crashes on the
original batch-size-64 implementation). Supersedes §§ prior "relationship vectors prohibited" /
`element_vectors`-only language.

### Crash-dump investigation (read-only; no OS settings changed)

`CrashDumpEnabled=3` (automatic memory dump), minidumps enabled. Event log showed two unclean
reboots the same day (5:05 PM, 5:27 PM) with no bugcheck event or dump — more severe than the
four prior recorded crashes, which were all bugcheck `0x116` (VIDEO_TDR_FAILURE — GPU driver
timeout/reset) except one `0x139` on an earlier date. Consistent with sustained GPU workload
destabilizing the driver.

### Architecture additions

- `src/bim_rag/text_limits.py` — shared token-budget enforcement (`MAX_TOKENS=2000`) against the
  real `BAAI/bge-m3` tokenizer, used only when a tokenizer is supplied.
- `src/bim_rag/config.py` — `THREAD_LIMIT=4`, `CUDA_BATCH_SIZE`, `MAX_CUDA_BATCH_SIZE=8`,
  `validate_batch_size()` (rejects 64), thread-limiting env vars set at import time.
- `src/bim_rag/templates.py` / `rel_templates.py` — `generate_text()` / `generate_rel_text()`
  accept an optional `tokenizer` param; token-budget truncation layered on top of the existing
  char budget when supplied (legacy 2-tuple return preserved when omitted).
- `src/bim_rag/schema/models.py` — `RagDocument` gains `source_hash`, `text_hash`,
  `original_token_count`, `encoded_token_count` columns.
- `src/bim_rag/stage2_embed.py` — rewritten: hash-based skip/resume, `_encode_batch()` with
  `torch.inference_mode()` + per-batch `torch.cuda.synchronize()` + stop-on-device-error (no
  retry), shared `_upsert_rag_document()` helper, additive `_add_rag_document_hash_columns()`
  migration.
- `src/bim_rag/smoke_test.py` — staged CUDA smoke tests 1–6 from `tasks/task03.md`, independently
  invocable (`python -m bim_rag.smoke_test --stage N`).
- `notebooks/02_vectorize.ipynb` — reusable full-pipeline notebook (executed, real outputs),
  supersedes `01_structured_import.ipynb` as the primary entry point.
- `tests/test_crash_recovery.py` — 31 new tests covering batch-size guard, thread limits,
  token-aware truncation, hash-based skip logic, CUDA error-stop behavior, migration idempotency.

### Migration

`rag_documents` already existed with 448 rows from the interrupted pre-crash run; `pgvector`
0.8.0 was already enabled; `element_vectors` did not exist. Additive `ALTER TABLE ... ADD COLUMN
IF NOT EXISTS` applied the four new columns without touching existing rows or requiring
`element_vectors` migration.

### Staged CUDA smoke tests (batch size 4)

All six stages passed cleanly: model load (7.0s, no encode), synthetic doc, one real entity doc
(62/62 tokens), one real relationship doc (902/902 tokens — confirmed the 2000-token ceiling has
real headroom), a batch of 4 mixed real docs, and 32 real docs in 8 batches of 4 (stored, folding
in stage 7's validate+store). No instability at any stage.

### Batch size 4 → 8

After batch-4 staged smoke tests and a chunk of production embedding completed without failure,
batch size was raised to the permitted ceiling of 8 (still never 64) per explicit user
instruction, observing available VRAM headroom. Config and tests updated accordingly
(`CUDA_BATCH_SIZE=8`, `MAX_CUDA_BATCH_SIZE=8`).

### Full-corpus embedding run

| Metric | Value |
|---|---:|
| Execution device | CUDA (NVIDIA GeForce RTX 5080 Laptop GPU), CUDA 12.8, torch 2.11.0+cu128 |
| CUDA batch size | 8 |
| Thread limit | 4 |
| Token limit | 2000 |
| Entity docs | new=4,889, skipped_valid=2,100, truncated=1,567, failures=0 |
| Relationship docs | new=3,457, skipped_valid=16, truncated=28, failures=0 |
| Total `rag_documents` | 10,462 (6,989 entity + 3,473 relationship) |
| Elapsed (full run) | 718.0s |
| Elapsed (idempotent rerun) | 70.7s |
| GPU thermal | 83–88°C sustained, 100% utilization at peaks, fluctuating clocks (975–1815 MHz of 3090 MHz max) — no errors, no instability, no further crashes |

During the run, two apparent "stalls" (frozen row counts across direct DB checks) were
investigated and resolved: isolated timing tests of the exact stalled batch, the full
6,989-entity text-generation/hashing loop (with and without the real tokenizer), and the
structured re-import phase all completed in seconds with zero slow items — the process was
never actually hung. Re-launching with `PYTHONUNBUFFERED=1` confirmed continuous real progress;
the earlier appearance of a stall was an artifact of block-buffered stdout under a redirected
background process, not a functional defect.

### Reconciliation (post-run)

```
ifc_entities = 6,989 = entity_description docs = valid entity embeddings (dim=1024, no NaN/Inf)
ifc_relationships = 3,473 = relationship_description docs = valid relationship embeddings
total rag_documents = 10,462, all source_hash/text_hash populated
duplicate active entity documents: 0        duplicate active relationship documents: 0
XOR / kind-type constraint violations: 0    orphaned entity/relationship references: 0
cross-source-model rows: 0                  element_vectors table exists: False
distinct source_model_id values: {1}
```

### Similarity search and SQL/RAG fusion (source-scoped, canonical IDs only)

- Entity similarity: seed `IfcTask` "Dakpannen" → nearest neighbors all `IfcTask`, cosine
  distance 0–0.12.
- Relationship similarity: seed `IfcRelAssignsToProcess` → nearest neighbors same class,
  distance 0–0.03.
- SQL/RAG fusion: SQL filter `IfcWall` (648 `ifc_entities.id`) ∩ vector top-50 nearest a wall →
  17 entities via canonical id join.
- Relationship traversal: `IfcRelContainedInSpatialStructure` relationship →
  `relationship_members.entity_id` → 5 resolved endpoint entities with class/GlobalId.
- Cross-model isolation: 0 rows outside `source_model_id=1` (only one model currently exists).

### Idempotency (second unchanged run)

`entity_docs_new=0, entity_docs_updated=0, entity_docs_skipped_valid=6,989`;
`rel_docs_new=0, rel_docs_updated=0, rel_docs_skipped_valid=3,473`; `total_rag_docs=10,462`
unchanged; 0 warnings; completed in 70.7s (vs 718.0s first run). Re-run reconciliation query
confirmed identical counts with zero duplicates.

### Test coverage

158/158 tests pass (127 existing + 31 new in `tests/test_crash_recovery.py`). `ruff format` /
`ruff check` clean.

### Status

```
Structured entities and relationships: VALIDATED
Unified rag_documents table: CREATED AND VALIDATED
Entity vectors: GENERATED AND VALIDATED
Relationship vectors: GENERATED AND VALIDATED
Canonical SQL/RAG identities: VALIDATED
Path-only notebook pipeline: EXECUTED AND VALIDATED
CLOCK_WATCHDOG_TIMEOUT mitigations: IMPLEMENTED AND VALIDATED
CUDA recovery batch size: 4 (staged validation) -> 8 (production, within the permitted ceiling)
```
