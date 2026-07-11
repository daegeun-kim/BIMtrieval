# Task 02-1: Add IFC Relationships to the Structured Database Import

## Purpose and superseding decision

Task 02 successfully imported 6,989 non-relationship IFC entities. The user now revokes the earlier decision to retain only standalone object features in the structured database.

Update the codebase and existing database import so the structured layer also preserves every `IfcRelationship` entity in the source IFC, including its complete direct, finite attributes and endpoint membership.

This task supersedes the relationship-exclusion rules in these earlier documents where they conflict:

```text
specs/spec_v001_ifc_to_db.md
tasks/task01_done.md
tasks/task02_done.md
```

Do not delete or rewrite those historical Markdown files. Implement the new decision through this task. A later specification version may consolidate the revised architecture.

## Current validated baseline

The existing Stage 1 import reported:

| Check | Result |
|---|---:|
| IFC schema | IFC2X3 |
| Total IFC entities | 843,172 |
| Eligible non-relationship entities | 6,989 |
| IFC relationships with GlobalIds | 3,473 |
| Existing `ifc_entities` rows | 6,989 |
| Null GlobalIds | 0 |
| Duplicate `(source_model_id, GlobalId)` | 0 |
| Distinct canonical entity IDs | 6,989 |

Preserve this validated object import and its canonical IDs while adding relationships.

## Objective

1. Change the reusable IFC-to-database implementation to import both eligible non-relationship entities and all IFC relationships with GlobalIds.
2. Add normalized relationship and relationship-member tables.
3. Store all direct finite information available on each relationship.
4. Resolve relationship endpoints to canonical `ifc_entities.id` values wherever possible.
5. Preserve unresolved endpoints using stable source-model and STEP-reference information.
6. Re-run the structured import against the existing source model idempotently.
7. Validate relationship and endpoint completeness.
8. Prepare the code for future IFC files using the same shared database schema, scoped by source model.
9. Do not create vectors in this task.

## Source IFC

For this execution, use:

```text
C:\Users\kdgki\Desktop\MSCDP\Projects\BIM_RAG\ifc_original\IFC Schependomlaan incl planningsdata.ifc
```

Do not modify, repair, move, rename, or rewrite it.

## Meaning of “include everything”

For each `IfcRelationship` with a valid GlobalId, preserve all direct information that can be serialized finitely and deterministically, including:

- relationship STEP ID
- relationship GlobalId
- exact IFC relationship class
- name and description when present
- OwnerHistory or other direct metadata in a safe finite representation
- every direct scalar IFC attribute
- every relating endpoint
- every related endpoint
- endpoint attribute/role name
- endpoint list position when the role contains an ordered or aggregate collection
- endpoint STEP ID
- endpoint IFC class
- endpoint GlobalId when available
- endpoint name when available
- canonical `ifc_entities.id` when the endpoint corresponds to an imported eligible entity
- extraction warnings and unsupported-value information
- source/extraction version metadata

“Include everything” does not authorize:

- recursively expanding each endpoint's full attributes or canonical JSON inside the relationship JSON
- recursively following relationships from endpoints
- importing all 843,172 IFC primitives as independent analytical rows
- duplicating complete endpoint objects in relationship records
- storing full meshes, vertex arrays, faces, or PostGIS geometry
- generating vectors during this task

The original IFC remains authoritative for the complete raw graph.

## Required database architecture

Retain the existing shared tables:

```text
ifc_source_models
ifc_entities
```

Add:

```text
ifc_relationships
relationship_members
```

Do not create separate physical tables for this IFC file. All current and future IFC files must use the same schema and remain logically isolated through `source_model_id`.

### `ifc_relationships`

At minimum, include:

- `id`: canonical PostgreSQL relationship primary key
- `source_model_id`: non-null foreign key to `ifc_source_models.id`
- `global_id`: relationship IFC GlobalId
- `step_id`: relationship STEP entity ID
- `ifc_class`: exact relationship class
- `name` and `description` when appropriate
- `canonical_json`: complete finite direct relationship JSON
- extraction version/timestamp
- extraction warnings

Required identity:

```text
UNIQUE (source_model_id, global_id)
```

The canonical `ifc_relationships.id` must remain stable across unchanged idempotent reruns.

### `relationship_members`

Use one row per direct endpoint membership. At minimum, include:

- its own primary key
- `relationship_id`: non-null foreign key to `ifc_relationships.id`
- `source_model_id`: either directly stored and constrained consistently, or unambiguously derivable through the relationship
- `role`: exact IFC attribute role such as `RelatingObject`, `RelatedObjects`, `RelatingStructure`, or `RelatedElements`
- `member_order`: deterministic position for aggregate endpoints, nullable for scalar roles if appropriate
- `endpoint_step_id`
- `endpoint_ifc_class`
- `endpoint_global_id` when available
- `endpoint_name` when available
- `entity_id`: nullable foreign key to `ifc_entities.id`
- finite endpoint-reference metadata if needed

Required identity must prevent duplicate endpoint rows on rerun. Use a deterministic uniqueness definition based on relationship, role, order, and endpoint source identity.

## Shared canonical identity

The structured graph must support:

```text
ifc_entities.id
    <- relationship_members.entity_id
    -> future rag_documents.entity_id

ifc_relationships.id
    <- relationship_members.relationship_id
    -> future rag_documents.relationship_id
```

Requirements:

- Preserve every existing `ifc_entities.id` from Task 02.
- Resolve `relationship_members.entity_id` whenever the endpoint is present in `ifc_entities` for the same source model.
- Never resolve endpoints by name.
- Resolve by source-scoped IFC identity, using `(source_model_id, GlobalId)` when available.
- Use source-scoped STEP identity for traceability where no GlobalId/canonical entity row exists.
- Never link an endpoint to an entity belonging to another source model.
- Keep unresolved endpoints rather than silently dropping them.

## Reusable multi-IFC pipeline requirement

Refactor the public structured-import API so it accepts an IFC path rather than relying exclusively on a hard-coded source path.

The intended public call is:

```python
result = ifc_to_db(r"C:\path\to\model.ifc")
```

For this structured task, `ifc_to_db(ifc_path)` must import the source-model record, entities, relationships, and relationship members. Vector generation remains disabled/deferred.

The only required public function parameter is the IFC file path. Database configuration must continue to load lowercase `db_url` internally at runtime without exposing it.

Requirements for additional IFC files:

- Compute a cryptographic fingerprint for each file.
- Reuse the same shared database tables.
- Create a distinct `ifc_source_models` row for a distinct fingerprint.
- Scope every entity, relationship, member, validation query, and future RAG document to the correct source model.
- Reuse an existing source-model record for an identical fingerprint and import idempotently.
- Never mix endpoints, IDs, counts, or retrieval results across source models.
- Do not derive SQL table names from uploaded filenames.

Retain or adapt the Stage 1 CLI so a file path can be supplied explicitly while preserving a documented default only if useful for development.

## Notebook requirement

Create a clean executable Jupyter notebook that orchestrates the tested Python modules rather than duplicating the extraction and database logic in notebook cells.

The notebook must:

1. Import the public `ifc_to_db` function.
2. Define or accept an IFC file path.
3. Call:

   ```python
   result = ifc_to_db(r"filepath")
   ```

4. Display the returned source-model ID, fingerprint prefix, entity count, relationship count, member count, unresolved-member count, warnings, and validation status.
5. Clearly state that vectors are not generated by this structured-import call in Task 02-1.
6. Avoid embedding credentials, absolute developer-only database details, or duplicated pipeline implementation.
7. Be reusable by changing only the IFC path argument.

The notebook itself may be executed in this task to validate the structured pipeline against the specified IFC, but it must not invoke any vector-generation code.

## Database access and safety

- Use the existing database referenced by lowercase `db_url` at runtime.
- Claude must not open, inspect, print, copy, log, or expose `.env` or the resolved URL.
- Do not create another database.
- Sanitize errors.
- Use migrations or narrowly scoped idempotent DDL to add the relationship tables and constraints.
- Do not drop, truncate, or rebuild the validated `ifc_entities` table.
- Do not delete unrelated data.
- Perform updates in transactions and avoid claiming success after partial relationship import.

## Implementation work authorized

Claude may:

- Modify the parser, schema models, DDL/migrations, Stage 1 code, reports, tests, CLI, documentation, and notebook.
- Add relationship extraction and endpoint-resolution modules.
- Create and populate `ifc_relationships` and `relationship_members`.
- Re-run the structured import for the existing source IFC.
- Run a second unchanged import to validate idempotency.
- Make narrowly scoped corrections required by observed failures.

## Prohibited actions

Claude must not:

- Enable pgvector if it is not already enabled.
- Create or populate `element_vectors`, `relationship_vectors`, `rag_documents`, or any embedding column/table.
- Generate entity or relationship natural-language documents for production vectorization.
- Load the embedding model for production processing.
- Execute the current `bim-stage2` or combined vector pipeline.
- Run the existing Task 03 as currently written; it is outdated because it prohibits relationship vectors and assumes `element_vectors` rather than the newly selected common RAG table.
- Change existing canonical `ifc_entities.id` values.
- Import all low-level IFC primitives as independent analytical entities.
- Add PostGIS or geometry storage.

## Required code corrections and tests

Update tests to cover at minimum:

- all `IfcRelationship` subtypes with valid GlobalIds are included
- relationship attributes serialize finitely without recursion
- scalar and aggregate endpoint roles are both extracted
- endpoint role names and member order are deterministic
- endpoint resolution to `ifc_entities.id`
- unresolved endpoints remain preserved
- cross-source endpoint linking is impossible
- relationship/member uniqueness and idempotent upserts
- stable `ifc_relationships.id` values across reruns
- stable existing `ifc_entities.id` values across migration/rerun
- duplicate endpoint prevention
- multi-file source-model isolation
- public `ifc_to_db(ifc_path)` path handling
- safe credential behavior
- notebook calls modules rather than duplicating implementation

## Execution and migration procedure

1. Review the completed Task 02 database and current code.
2. Capture the existing source-model ID and a deterministic audit sample mapping `(GlobalId -> ifc_entities.id)` before changes.
3. Implement the relationship schema, extraction, endpoint mapping, multi-file path parameter, reporting, and notebook.
4. Run safe unit/static tests.
5. Apply only the additive relationship migration to the existing target database.
6. Execute the structured import for the specified IFC through the new public function or its thin CLI wrapper.
7. Validate all relationship counts, endpoints, foreign keys, and source scoping.
8. Compare the entity identity audit sample and total entity count to the pre-change baseline.
9. Run the unchanged structured import again.
10. Confirm counts and canonical IDs remain stable.
11. Stop before all vector work.

## Required validation report

Report at minimum:

- source model ID and fingerprint prefix
- IFC schema
- total IFC entity count
- non-relationship entity count
- stored `ifc_entities` count
- IFC relationship count with GlobalIds
- stored `ifc_relationships` count
- relationship count by IFC class in IFC versus database
- total direct endpoint memberships extracted
- stored `relationship_members` count
- resolved member count
- unresolved member count grouped by reason/class
- relationships with zero extracted members
- duplicate relationship identities
- duplicate member identities
- null/invalid relationship GlobalIds
- orphaned member foreign keys
- cross-source links, which must be zero
- relationship extraction failures/warnings
- representative relationship JSON for multiple relationship classes
- representative scalar and aggregate endpoint memberships
- proof that the original 6,989 entity rows and audited `ifc_entities.id` values remain stable
- proof that the second unchanged run creates no duplicates
- confirmation that no vector table was created or populated by this task

Expected relationship count for the current file is 3,473. If the implemented eligibility definition produces a different number, investigate and explain it rather than silently accepting the mismatch.

## Completion report

Report:

1. Files changed and architectural changes made.
2. Exact commands and notebook cells executed.
3. Database migration applied.
4. Entity, relationship, member, and unresolved-member reconciliation.
5. Stable-ID and idempotency evidence.
6. Multi-IFC isolation behavior.
7. Warnings or blockers.
8. Explicit confirmation:

   ```text
   Existing IFC entities: PRESERVED AND VALIDATED
   IFC relationships: IMPORTED AND VALIDATED
   Relationship members: IMPORTED AND VALIDATED
   Vector generation: NOT EXECUTED
   Current tasks/task03.md: OUTDATED AND NOT EXECUTED
   ```

Rename this file to `tasks/task02-1_done.md` only after all acceptance criteria pass. The descriptive filename is explicitly requested by the user as an exception to the normal `taskNN.md` naming convention.

## Acceptance criteria

Task 02-1 is complete only when:

1. All 3,473 expected IFC relationships are represented exactly once for the current source model, or any verified source discrepancy is explicitly resolved.
2. All direct endpoint roles/members are stored without recursive expansion.
3. Resolvable endpoints reference the correct same-model `ifc_entities.id` values.
4. Unresolved endpoints remain traceable by source-scoped STEP/class/GlobalId data.
5. Existing 6,989 entity rows and their canonical IDs remain stable.
6. Relationship and member rows are idempotent across an unchanged rerun.
7. The public `ifc_to_db(ifc_path)` structured-import function supports additional IFC paths with shared tables and strict source-model isolation.
8. The reusable notebook successfully orchestrates the structured import by changing only the IFC path.
9. No production vector document, embedding, or vector table is created or populated.
10. Credentials and `.env` contents remain protected.

