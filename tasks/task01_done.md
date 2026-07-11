# Task 01: Implement the IFC-to-Database Pipeline Without Executing Data Operations

## Governing specification

Implement the codebase described by:

```text
specs/spec_v001_ifc_to_db.md
```

The specification is the architectural and behavioral blueprint. This task controls what Claude is authorized to execute now.

## Objective

Write the complete implementation needed for the v001 IFC-to-PostgreSQL and element-description-vector pipeline, but do not yet execute the long-running or database-mutating data pipeline.

The code must be ready for two later, separately authorized execution stages:

1. Parse and import the IFC structured data into PostgreSQL.
2. Enable/use pgvector, create the vector storage, generate element-description embeddings, and populate the vectors.

After implementing and safely checking the code, stop and wait for explicit user instruction before executing either stage.

## Actions authorized in this task

Claude may:

- Create the persistent Anaconda environment `bim_rag` with Python 3.11.
- Install the dependencies required by `specs/spec_v001_ifc_to_db.md`.
- Download/install the approved local embedding model and CUDA-compatible dependencies if this is part of environment preparation.
- Create or modify source code, tests, dependency declarations, SQL/migration definitions, documentation, and other implementation files required by the specification.
- Inspect the IFC file and repository structure when needed to design and implement the parser.
- Parse small/read-only samples or inspect IFC metadata locally when needed for code development, provided no extracted records are written to PostgreSQL.
- Run formatting, linting, type checking, imports, test discovery, and unit tests that do not connect to or mutate the target PostgreSQL database.
- Run tests using mocks, temporary in-memory data, or isolated non-database fixtures.
- Verify that `bim_rag` uses Python 3.11 and that required libraries import.
- Verify CUDA/PyTorch device detection without generating production embeddings.
- Load `BAAI/bge-m3` only for environment/import readiness if necessary, but do not run the IFC corpus through it or generate/store production element vectors.
- Write commands/scripts for both later execution stages without running those commands.

## Actions prohibited in this task

Claude must not:

- Create, alter, drop, truncate, or populate any table in the PostgreSQL database referenced by `db_url`.
- Run schema migrations against the user's PostgreSQL database.
- execute `CREATE EXTENSION vector` or otherwise enable pgvector in the user's database.
- Import any IFC entity or extracted IFC data into PostgreSQL.
- Generate production element-description embeddings from the specified IFC model.
- Create or populate production vector rows or vector columns in PostgreSQL.
- Run the stage-1 IFC-to-database command.
- Run the stage-2 pgvector/embedding-generation command.
- Perform an end-to-end integration test against the target database.
- Open, inspect, print, copy, log, or expose `.env` or its contents.
- Print or hard-code the resolved `db_url`.
- Create a substitute PostgreSQL database.
- Mark this task complete on the basis of successful database ingestion or vector population, because those operations are intentionally deferred.

If any development command would connect to the target PostgreSQL database or might mutate it, do not run it in this task.

## Required implementation separation

Design the implementation so the later stages can be invoked independently and explicitly.

### Later Stage 1: Structured IFC import

Provide a dedicated command or entry point that will, only when explicitly invoked later:

1. Load lowercase `db_url` from `.env` at runtime without displaying it.
2. Validate and parse the exact source IFC.
3. Create only the non-vector structured schema/tables needed for the IFC import.
4. Extract canonical JSON for every eligible entity defined by the specification.
5. Insert/upsert the source-model and structured entity records idempotently.
6. Perform structured-import reconciliation and reporting.

Stage 1 must not generate embeddings or require vector rows to be populated. If vector-related schema cannot be cleanly deferred, redesign the migrations/schema boundaries so structured ingestion remains independently executable.

### Later Stage 2: Vector setup and population

Provide a separate dedicated command or entry point that will, only when explicitly invoked after Stage 1:

1. Load lowercase `db_url` securely at runtime.
2. Run `CREATE EXTENSION IF NOT EXISTS vector`.
3. Create or migrate the vector-specific table/column and indexes.
4. Generate deterministic v001 element-description text from stored canonical JSON.
5. Generate `BAAI/bge-m3` 1024-dimensional embeddings.
6. Insert/upsert exactly one `element_description` vector for each eligible structured entity.
7. Perform embedding reconciliation, sample similarity queries, and idempotency validation.

Stage 2 must refuse to proceed if the required Stage-1 structured import is absent or incomplete.

## Implementation requirements

Implement all requirements in `specs/spec_v001_ifc_to_db.md`, including:

- finite canonical JSON extraction
- permitted intrinsic/resolved information boundary
- exclusion of `IfcRelationship` entities and relationship graph content
- modular feature-level natural-language templates
- template versioning
- deterministic text generation
- text-length and truncation policy
- fixed `BAAI/bge-m3` model and dimension 1024
- secure runtime `db_url` loading
- normalized database design
- model fingerprinting
- idempotent import/upsert behavior
- transaction and failure behavior
- validation and reconciliation reporting
- CPU fallback reporting when CUDA is unavailable
- no PostGIS or geometry storage

Do not collapse Stage 1 and Stage 2 into a single unavoidable command. A convenience orchestration command may be written only if the two underlying stages remain independently callable, but the convenience command must not be executed in this task.

## Safe testing requirements for Task 01

Write tests that cover the important logic without accessing the target database, including at minimum:

- IFC entity eligibility and `IfcRelationship` exclusion
- canonical JSON finiteness and cycle prevention
- property-set and quantity-set collision avoidance
- value/unit normalization behavior
- feature-template selection and stable ordering
- identical feature types using identical templates across IFC classes
- missing/null feature omission
- prohibited relationship information omission
- deterministic text output
- text deduplication and truncation reporting
- embedding-dimension validation using mocks or synthetic vectors
- import and vector-stage idempotency logic at the unit level
- credential sanitization
- Stage 2 precondition checks

Safe tests may use mocked database sessions or an isolated temporary test mechanism that cannot reach the user database. Do not use `db_url` during Task 01 tests.

## Deliverables

Before stopping, provide:

1. The complete implementation files for the v001 pipeline.
2. Reproducible environment/dependency definitions.
3. A dedicated Stage-1 command for structured IFC import.
4. A dedicated Stage-2 command for pgvector setup and embedding population.
5. Database schema/migration code separated by stage.
6. The canonical JSON extractor.
7. The versioned feature-template module and deterministic text generator.
8. Validation/reporting code for both stages.
9. Safe unit tests and their results.
10. Documentation listing the exact commands that would be run later, clearly labeled as **not executed**.
11. A concise implementation report listing files created/changed, design decisions, checks actually run, and checks intentionally deferred.

## Stop condition

Stop after the code, environment preparation, safe tests, and documentation are complete.

Report explicitly:

```text
Stage 1 structured IFC import: NOT EXECUTED
Stage 2 pgvector and vector generation: NOT EXECUTED
```

Then wait for the user's instruction. Do not begin either execution stage merely because the code is ready or safe tests pass.

## Task acceptance criteria

Task 01 is complete when:

1. The v001 pipeline is fully implemented in code according to the governing specification.
2. `bim_rag` has been created with Python 3.11 and dependencies are reproducibly declared.
3. Stage 1 and Stage 2 have separate explicit commands and migration boundaries.
4. Safe unit/static checks pass or all remaining failures are clearly reported.
5. No target database table, extension, column, row, or vector has been created or modified.
6. No production embedding has been generated from the IFC corpus.
7. `.env` has not been opened or exposed by Claude.
8. Claude has stopped and is waiting for explicit authorization to execute Stage 1 or Stage 2.

