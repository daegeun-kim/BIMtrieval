# Task 02: Create and Populate the Structured IFC Tables

## Governing documents

Follow:

```text
specs/spec_v001_ifc_to_db.md
tasks/task01_done.md
```

Task 01 implemented the pipeline. This task authorizes execution of Stage 1 only.

## Objective

Create the structured PostgreSQL tables in the user's existing database and import the canonical object information from the specified IFC file.

This task establishes `ifc_entities.id` as the permanent canonical database object ID. Future SQL retrieval and vector/RAG retrieval must use this same identity so their results can be combined without heuristic matching.

## Source IFC

Use only:

```text
C:\Users\kdgki\Desktop\MSCDP\Projects\BIM_RAG\ifc_original\IFC Schependomlaan incl planningsdata.ifc
```

Do not modify, repair, move, rename, or rewrite the source IFC.

## Database access

- Use the user's existing PostgreSQL database addressed by lowercase `db_url` in `.env`.
- Claude must not open, inspect, print, copy, log, or expose `.env` or the resolved database URL.
- The application may load `db_url` from `.env` at runtime.
- Do not create or substitute another database.
- Sanitize errors so credentials cannot be exposed.
- If connection or permissions fail, stop and report the sanitized failure.

## Authorized actions

Claude may:

- Activate the existing `bim_rag` Anaconda environment.
- Correct implementation defects that prevent safe and specification-compliant Stage 1 execution.
- Connect to the target database through runtime `db_url`.
- Create the Stage 1 structured tables and indexes.
- Parse the complete IFC model.
- Insert or idempotently update the source-model and eligible IFC entity records.
- Run Stage 1 validation, reconciliation, and one unchanged rerun for idempotency.
- Make narrowly scoped code, SQL, test, and documentation corrections required by verified Stage 1 failures.

## Prohibited actions

Claude must not:

- Enable or install the PostgreSQL `vector` extension.
- Create, alter, or populate `element_vectors` or any other vector table/column.
- Load `BAAI/bge-m3` for production processing.
- Generate production natural-language element documents or embeddings.
- Execute `bim-stage2` or `bim-pipeline`.
- Add PostGIS or geometry storage.
- Delete or alter unrelated database objects or rows.
- Vectorize IFC relationships or implement relationship-aware retrieval.

## Required schema and shared object identity

Create/populate the structured tables implemented by Stage 1, including:

### `ifc_source_models`

Stores the source-model identity, file fingerprint, schema, counts, extraction version, and import metadata.

### `ifc_entities`

Stores one record for every eligible entity under the governing specification.

Identity requirements:

- `ifc_entities.id` is the canonical PostgreSQL object ID and primary key.
- `(source_model_id, global_id)` must be unique.
- `global_id` remains the authoritative IFC identity within its source model.
- `id` values must remain stable across idempotent unchanged reruns.
- Existing objects must be updated in place rather than deleted and recreated.
- Stage 1 must not create vector-specific data.

Create and verify indexes supporting source-model lookup, IFC class filtering, GlobalId lookup, and the unique `(source_model_id, global_id)` identity.

## Execution procedure

1. Review the actual Stage 1 implementation and DDL against this task and the governing specification.
2. Confirm the environment, imports, source IFC path, and Stage 1 command without exposing secrets.
3. Ensure Stage 1 cannot accidentally invoke Stage 2.
4. Execute only the dedicated Stage 1 command:

   ```text
   bim-stage1
   ```

   or its documented equivalent inside `bim_rag`.
5. If execution fails, diagnose it and make only the minimum in-scope correction.
6. Re-run Stage 1 until it either succeeds or reaches a clear external blocker.
7. Validate the database contents using sanitized SQL queries.
8. Execute Stage 1 once more against the unchanged IFC to prove idempotency.
9. Stop without starting Stage 2.

## Required validation

Report and reconcile at minimum:

- IFC schema/version and source fingerprint prefix
- total IFC entity count
- entities with GlobalIds
- eligible non-relationship entity count
- excluded relationship count
- duplicate or invalid GlobalIds
- imported `ifc_source_models` count for this fingerprint
- imported `ifc_entities` count for this source model
- database counts by IFC class versus extraction counts by IFC class
- null or empty GlobalIds in imported eligible records
- duplicate `(source_model_id, global_id)` rows
- extraction failure and warning counts
- representative canonical JSON samples from several entity classes
- confirmation that canonical JSON is finite and contains no prohibited relationship graph data
- confirmation that `ifc_entities.id` is present, unique, indexed as a primary key, and stable across the unchanged rerun
- confirmation that `element_vectors` was neither created nor populated by this task

The structured entity count must equal the eligible extracted entity count. If it does not, do not claim completion; diagnose and either correct the import or report the blocker.

## Idempotency requirements

On the second unchanged run:

- no duplicate source model may be created
- no duplicate entity may be created
- row counts must remain unchanged
- each `(source_model_id, global_id)` must retain the same `ifc_entities.id`
- unrelated rows must remain untouched

Capture enough before/after identity evidence to demonstrate stable canonical IDs without dumping the entire database.

## Completion report

Report:

1. Exact commands executed.
2. Files changed, if any, and why.
3. Tables and indexes created.
4. Reconciliation and validation results.
5. Idempotency results.
6. Any warnings or unresolved limitations.
7. Explicit confirmation:

   ```text
   Stage 1 structured IFC import: EXECUTED AND VALIDATED
   Stage 2 pgvector and vector generation: NOT EXECUTED
   ```

Rename this file to `tasks/task02_done.md` only after every acceptance criterion is satisfied. If blocked or incomplete, leave it as `tasks/task02.md`.

## Acceptance criteria

Task 02 is complete only when:

1. Stage 1 has successfully created the structured tables in the existing target database.
2. Every eligible IFC entity has exactly one `ifc_entities` record.
3. Every structured object has a stable canonical `ifc_entities.id`.
4. Source and database counts reconcile, including counts by IFC class.
5. Representative canonical JSON has been inspected and validated.
6. The unchanged second run creates no duplicates and preserves canonical IDs.
7. No pgvector extension, vector table, vector column, production text, or embedding has been created by this task.
8. Credentials and `.env` contents have not been exposed.

