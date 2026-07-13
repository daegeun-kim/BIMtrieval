# Task 03: Create Unified Entity and Relationship Vectors

## Governing documents and prerequisites

Follow the current architecture established by:

```text
specs/spec_v001_ifc_to_db.md
tasks/task01_done.md
tasks/task02_done.md
tasks/task02-1_done.md
```

Where earlier documents prohibit relationship vectors or require an `element_vectors`-only design, this Task 03 supersedes those outdated requirements.

Do not begin database or embedding execution unless Task 02-1 is complete and validated for the exact source IFC. If `tasks/task02-1_done.md` does not exist, stop and tell the user to complete Task 02-1 first.

## Critical stability incident and mandatory response

The current Task 03 vectorization implementation has caused the laptop to crash twice during CUDA embedding generation. Windows displayed:

```text
Your device ran into a problem and needs to restart.
Stop code: CLOCK_WATCHDOG_TIMEOUT (0x101)
```

Both failures occurred during the vector-generation workload and required a forced shutdown/restart. Treat this as a reproducible system-stability incident, not a random application exception.

The implementation currently uses `BAAI/bge-m3` on CUDA with a GPU batch size of 64 and document text up to 4,000 characters. This sustained workload is considered the immediate trigger. A user-space Python process should normally receive a recoverable CUDA error rather than cause a Windows bugcheck, so the underlying failure may involve the NVIDIA driver, firmware, CPU interrupt handling, laptop power stability, or their interaction under the workload. The code must still be changed to avoid repeating the unsafe load pattern.

Do not rerun the existing vectorization code unchanged. Before any further production embedding attempt, implement and validate all safeguards in the following section.

## Mandatory crash-prevention changes

### Conservative batch size

- Replace the current CUDA batch size of 64.
- Default to a CUDA embedding batch size of 4.
- Permit an explicit configuration up to 8 only after the batch-size-4 staged checks complete without application or system failure.
- Do not automatically increase the batch size based only on available VRAM.
- Keep entity and relationship batch policies consistent unless a documented text-length reason requires a smaller relationship batch.

### Token-aware input limits

- Stop relying only on the 4,000-character limit.
- Measure or tokenize every generated document using the actual `BAAI/bge-m3` tokenizer before encoding.
- Define a conservative maximum token length below or equal to the model-supported limit.
- Apply deterministic feature-priority truncation before calling `encode()`.
- Preserve IFC class, GlobalId, canonical source ID, and essential endpoint roles when truncating.
- Record original token count, encoded token count, and truncation status in generation metadata.
- Never allow a single unexpectedly long relationship document to expand the effective workload silently.

### Explicit device and workload configuration

- Make the embedding device an explicit internal configuration with a safe default for this project run.
- Record the chosen device, batch size, token limit, model version, and PyTorch/CUDA versions in the report.
- Do not choose batch size 64 merely because CUDA is available.
- Limit PyTorch and tokenizer CPU thread counts to conservative documented values so tokenization and GPU inference do not simultaneously saturate all logical CPU cores.
- Disable unnecessary tokenizer parallelism unless explicitly shown to be safe.
- Avoid optional compilation, mixed experimental kernels, or aggressive performance tuning during this recovery run.

### Staged CUDA smoke tests

Before resuming the complete corpus, run these stages in order and stop between stages to inspect the result:

1. Load `BAAI/bge-m3` on CUDA without encoding the corpus.
2. Encode one short synthetic document.
3. Encode one real entity document.
4. Encode one real relationship document.
5. Encode a fixed batch of 4 mixed real documents.
6. Encode a small fixed sample of no more than 32 source records using batches of 4.
7. Validate and store the small sample.
8. Only after every stage succeeds may the resumable full run begin at batch size 4.

If Windows crashes, the process hangs, CUDA reports an error, or the staged result is invalid, do not advance to the next stage and do not retry repeatedly. Report the exact last completed stage.

### Per-batch durability and resume

- Commit each successfully validated embedding batch independently.
- Record deterministic document-text and source-content hashes.
- On restart, skip rows whose source hash, text hash, template version, model, dimension, and stored vector are already valid.
- Resume from missing or invalid records instead of re-embedding the full corpus.
- Do not regenerate the structured IFC tables merely to resume vectorization.
- A failed batch must roll back only that batch, not completed batches.
- Record the last attempted source kind, canonical source ID, and batch offset without exposing database credentials.
- Ensure rerunning `ifc_to_db(ifc_path)` recognizes completed vector batches and continues safely.

### CUDA cleanup and error boundaries

- Release batch-local tensors and references promptly after successful storage.
- Use inference/no-gradient mode.
- Synchronize CUDA at controlled batch boundaries so asynchronous errors are attributed to the correct batch.
- Catch recoverable CUDA exceptions, record the failed batch, clear safe application-level state, and stop instead of immediately continuing under an unstable device state.
- Do not implement an automatic retry loop for a CUDA batch that preceded a system failure.

### Windows crash evidence readiness

Before the staged CUDA tests, document whether Windows is configured to save a kernel or minidump after a bugcheck. Do not change operating-system crash-dump settings without explicit user approval. If another bugcheck occurs and a new dump is produced, stop Task 03 and report the dump timestamp/path for separate analysis rather than continuing vector generation.

## Objective

Implement and execute a unified vectorization pipeline that:

1. Enables pgvector in the user's existing PostgreSQL database.
2. Replaces the outdated entity-only `element_vectors` design with one common `rag_documents` table.
3. Generates deterministic natural-language documents for both IFC entities and IFC relationships.
4. Generates one `BAAI/bge-m3` vector for every eligible entity document and every relationship document.
5. Preserves direct canonical identity links back to `ifc_entities.id` or `ifc_relationships.id`.
6. Keeps every operation and retrieval strictly scoped by `source_model_id`.
7. Makes the entire reusable pipeline executable from a notebook through:

   ```python
   result = ifc_to_db(r"C:\path\to\model.ifc")
   ```

The only required public function parameter is the IFC file path.

## Current expected source counts

For the current Schependomlaan IFC, expect approximately:

| Source kind | Expected rows/documents |
|---|---:|
| Eligible non-relationship entities | 6,989 |
| IFC relationships | 3,473 |
| Total RAG documents/vectors | 10,462 |

These are reconciliation expectations, not permission to hard-code counts. Read actual validated Task 02-1 counts and investigate discrepancies.

## Database access

- Use only the user's existing PostgreSQL database addressed by lowercase `db_url` loaded internally at runtime.
- Claude must not open, inspect, print, copy, log, or expose `.env` or the resolved URL.
- Do not create a replacement database or separate vector database.
- Sanitize connection and extension errors.
- If pgvector server binaries or privileges are unavailable, stop and report the sanitized blocker.

## Required preflight before vector mutation

Before enabling pgvector or creating vector schema:

1. Confirm Task 02-1 completion evidence exists.
2. Fingerprint the requested IFC path.
3. Resolve the exact `ifc_source_models` row by fingerprint, never by selecting the first model row.
4. Confirm the validated entity count for that source model.
5. Confirm the validated relationship count for that source model.
6. Confirm all `ifc_entities.id` and `ifc_relationships.id` values are unique and source-scoped.
7. Confirm relationship members have no cross-source foreign keys.
8. Confirm there are no duplicate source identities that would make vector ownership ambiguous.

If any preflight check fails, stop before vector-related mutation.

## Unified `rag_documents` table

Create one common table named:

```text
rag_documents
```

Do not create separate `element_vectors` and `relationship_vectors` tables.

At minimum, `rag_documents` must contain:

- `id`: primary key
- `source_model_id`: non-null foreign key to `ifc_source_models.id`
- `source_kind`: constrained to `entity` or `relationship`
- `entity_id`: nullable foreign key to `ifc_entities.id`
- `relationship_id`: nullable foreign key to `ifc_relationships.id`
- `document_type`: constrained to the appropriate type
- `document_text`: deterministic generated text
- `text_truncated`: non-null boolean
- `text_template_version`
- `embedding_model`
- `embedding_dim`: fixed at 1024
- `embedding`: `vector(1024)`
- generation/update timestamp
- optional finite metadata JSON for generation provenance and warnings

### Source-reference constraint

Enforce exactly one canonical source reference:

- Entity document: `entity_id IS NOT NULL` and `relationship_id IS NULL`.
- Relationship document: `relationship_id IS NOT NULL` and `entity_id IS NULL`.
- `source_kind` and `document_type` must agree with the selected source reference.
- The referenced source row must belong to the same `source_model_id` as the RAG document.

Use database constraints where feasible and application-level validation in addition. Cross-model references must be impossible or detected before commit.

### Document types

Permit exactly:

```text
entity_description
relationship_description
```

Do not add summary, geometry, adjacency-summary, material-summary, storey-summary, project-summary, or other document types in this task.

### Identity and uniqueness

The canonical identity paths are:

```text
rag_documents.entity_id       -> ifc_entities.id
rag_documents.relationship_id -> ifc_relationships.id
```

Create uniqueness rules that allow exactly one active document/vector for each source record, document type, template version, and embedding model.

Create indexes for:

- `source_model_id`
- `(source_model_id, source_kind)`
- `entity_id`
- `relationship_id`
- document type/model/template filtering
- cosine vector similarity search

SQL filtering and RAG retrieval must combine through these canonical numeric IDs, not names or text parsing.

## Migration from the obsolete design

The current code may still define `element_vectors`. Refactor it to use `rag_documents`.

Requirements:

- Determine whether `element_vectors` exists and whether it contains rows.
- Do not silently drop or overwrite existing populated data.
- Because earlier tasks were supposed to defer vector generation, an empty obsolete table may be removed only through an explicit, documented migration after verifying it is empty.
- If it contains data, stop and report the state before destructive migration.
- Update ORM models, DDL/migrations, queries, reports, tests, CLI, and documentation consistently.
- Remove obsolete runtime paths that could accidentally populate `element_vectors` after migration.

## Entity document generation

Generate one `entity_description` document for every eligible `ifc_entities` row belonging to the selected source model.

Requirements:

- Generate text only from stored canonical entity JSON.
- Preserve the deterministic modular feature-template system.
- Use identical templates for identical feature types across IFC classes.
- Include IFC class and GlobalId in every document.
- Include all permitted direct/intrinsic and previously resolved descriptive facts.
- Do not recursively add relationship records to entity documents.
- Do not add neighboring-object, adjacency, connectivity, or full relationship graph prose to entity documents.
- Deduplicate facts and report deterministic truncation.
- Do not use an LLM to generate text.

## Relationship document generation

Generate one `relationship_description` document for every `ifc_relationships` row belonging to the selected source model.

Include all available direct finite relationship information, including:

- relationship IFC class
- relationship GlobalId
- name and description when present
- direct scalar attributes
- every endpoint role
- every endpoint in aggregate roles
- endpoint order when meaningful
- endpoint STEP ID
- endpoint IFC class
- endpoint GlobalId when available
- endpoint name when available
- canonical entity ID when resolved
- unresolved endpoint status when not resolved

Use modular deterministic templates per relationship feature/role. Identical relationship features must use identical wording across relationship classes.

Do not:

- recursively insert full endpoint canonical JSON
- recursively traverse endpoint relationships
- duplicate all entity properties inside relationship text
- invent relationship meaning with an LLM
- silently omit endpoints to shorten text

If a relationship document exceeds the model input policy, use deterministic priority/chunk/truncation behavior defined in code and record it. Because this task requires one vector per relationship, do not silently split one relationship into multiple production vectors.

## Embedding requirements

Use only:

```text
Model: BAAI/bge-m3
Dimension: 1024
Distance metric: cosine
Storage normalization: L2 normalized
```

Use the RTX 5080 Laptop GPU when CUDA is available. Report the actual CUDA device. CPU fallback is allowed only when explicitly reported.

Requirements:

- Use CUDA batch size 4 for the recovery run; batch size 64 is prohibited.
- Enforce the token-aware input policy and conservative CPU-thread limits defined above.
- Complete every staged CUDA smoke test before full-corpus embedding.
- Batch processing must be restartable/idempotent.
- Persist each successful batch so the full run resumes rather than restarts after interruption.
- Validate every vector dimension.
- Reject NaN, infinity, empty text, or invalid vectors.
- Do not mark a source model fully vectorized if any required document/vector failed.
- Record template and model versions with every row.
- Avoid regenerating unchanged valid vectors when the source JSON, generated text, template version, and embedding model have not changed. Use deterministic hashes if needed.

## Public reusable pipeline

Expose one public function:

```python
result = ifc_to_db(r"C:\path\to\model.ifc")
```

The only required argument is `ifc_path`.

After Task 03, this function must run the complete pipeline for that file:

1. Validate and fingerprint the IFC.
2. Create or reuse the source-model record.
3. Import/upsert entities.
4. Import/upsert relationships.
5. Import/upsert relationship members.
6. Validate the structured import.
7. Ensure pgvector and unified RAG schema exist.
8. Generate entity and relationship documents.
9. Generate/store vectors.
10. Validate counts, identity, isolation, and similarity retrieval.
11. Return a structured result/report.

Database configuration remains internal through runtime `db_url`. Do not add database credentials as a function argument.

### Multi-IFC isolation

For every additional IFC file:

- use the same shared tables
- create a distinct source model for a distinct fingerprint
- reuse the existing source model for an identical fingerprint
- scope structured rows, RAG rows, validation, and search by `source_model_id`
- never mix vector candidates across models unless a future caller explicitly requests cross-model search
- never derive SQL table names from filenames

The default RAG search API must require or internally carry a `source_model_id` filter.

## Notebook requirement

Update or create the reusable Jupyter notebook so the user changes only the path and runs the pipeline:

```python
from bim_rag import ifc_to_db

result = ifc_to_db(r"C:\path\to\model.ifc")
result
```

The notebook must:

- call tested Python modules instead of duplicating implementation
- show stage progress and elapsed time
- display the returned `source_model_id`
- display entity, relationship, member, entity-document, and relationship-document counts
- display failures, warnings, truncations, unresolved endpoints, and execution device
- display the configured batch size, token limit, thread limits, smoke-test status, and resume/skipped counts
- display final validation status
- include example source-scoped entity and relationship vector searches
- never expose `db_url` or `.env`
- be reusable for another IFC by changing only the file path

## Authorized actions

Claude may:

- Refactor code, ORM models, DDL/migrations, templates, reports, tests, CLI, documentation, and notebook.
- Enable pgvector in the existing target database.
- Create and populate `rag_documents`.
- Remove an obsolete empty `element_vectors` table through an explicit migration after proving it is empty.
- Generate entity and relationship production documents and embeddings.
- Run the full path-parameterized pipeline for the current IFC.
- Run an unchanged second pass to validate idempotency.
- Run read-only source-scoped similarity and SQL/RAG fusion tests.

## Prohibited actions

Claude must not:

- Proceed before Task 02-1 completion.
- Rerun the existing batch-size-64 vector implementation.
- Begin full-corpus embedding before all staged CUDA smoke tests pass.
- automatically retry after a system crash or CUDA instability.
- Drop a populated obsolete vector table without explicit user approval.
- Change canonical `ifc_entities.id` or `ifc_relationships.id` values.
- Mix records from different source models.
- Generate vectors for low-level IFC primitives that are not represented in the structured entity/relationship tables.
- Add PostGIS or geometry storage.
- Use hosted embeddings, an LLM for document generation, or a separate vector database.
- Add UI, chatbot, FastAPI, LangChain, or LlamaIndex features.
- Delete unrelated database contents.

## Required tests before production execution

Test at minimum:

- `rag_documents` XOR source-reference constraint
- source-kind/document-type agreement
- same-model source-reference validation
- entity and relationship document uniqueness
- entity template determinism
- relationship template determinism
- preservation of every endpoint role/member in relationship text
- no recursive endpoint expansion
- deterministic truncation reporting
- tokenizer-based length enforcement and essential-field preservation
- CUDA batch-size configuration defaults to 4 and rejects 64
- conservative thread-limit configuration
- staged smoke-test gating prevents premature full-corpus execution
- dimension/NaN/infinity validation
- source-model-scoped similarity search
- no cross-model results under default search
- idempotent vector upsert
- per-batch commit, rollback isolation, source/text hashes, completed-row skipping, and resume behavior
- controlled CUDA synchronization/error-stop behavior using mocks
- obsolete `element_vectors` migration safety
- `ifc_to_db(ifc_path)` complete orchestration
- notebook import and path-only call
- credential sanitization

## Execution procedure

1. Verify Task 02-1 completion and inspect its actual schema/report.
2. Review current vector code and obsolete schema state.
3. Review the two `0x101` incidents and confirm the current unsafe batch-size-64 path cannot be invoked accidentally.
4. Implement the unified RAG schema, templates, conservative embedding pipeline, source-scoped search, full public orchestration, and notebook.
5. Implement token-aware limits, conservative thread limits, per-batch hashes/checkpoints, completed-row skipping, resume behavior, and controlled CUDA error boundaries.
6. Run safe unit/static tests.
7. Run all structured-data preflight checks against the exact source fingerprint.
8. Document Windows crash-dump readiness without changing OS settings.
9. Enable pgvector.
10. Apply the additive/safe `rag_documents` migration.
11. Run the staged CUDA smoke tests in order using batch size 4.
12. Stop immediately if any smoke stage fails or system instability recurs.
13. After all smoke tests pass, generate and store entity documents/vectors in resumable batches of 4.
14. Generate and store relationship documents/vectors in resumable batches of 4.
15. Validate all counts, identities, constraints, vector values, hashes, and resume state.
16. Run source-scoped similarity examples for both document types.
17. Demonstrate SQL/RAG fusion through canonical IDs.
18. Run the complete unchanged pipeline a second time and verify completed vectors are skipped rather than recomputed.
19. Confirm no duplicates or canonical-ID changes.

## Required reconciliation

For the selected source model, validate:

```text
ifc_entities count
= entity_description document count
= valid entity embedding count

ifc_relationships count
= relationship_description document count
= valid relationship embedding count

total required sources
= total rag_documents
= total valid embeddings
```

Also report:

- pgvector extension status
- actual execution device
- configured CUDA batch size, which must be 4 for this recovery run
- tokenizer/model input limit and truncation counts
- configured PyTorch/tokenizer thread limits
- result of each staged CUDA smoke test
- number of newly embedded, resumed, skipped-valid, failed, and rolled-back batches/rows
- last successful and last attempted batch identifiers
- model and template versions
- entity and relationship counts by IFC class
- total and per-kind generated documents
- text truncations per kind
- embedding failures per kind
- missing documents/vectors
- duplicate active documents
- orphaned entity/relationship references
- source-kind/type mismatches
- cross-source references and search results, which must be zero
- invalid vector dimensions or values
- unresolved relationship endpoint statistics

Do not claim completion if required counts do not reconcile.

## SQL and RAG common-identity validation

Demonstrate that future tools can combine structured and semantic retrieval:

1. Run an SQL entity filter returning `ifc_entities.id`.
2. Run entity vector search returning `rag_documents.entity_id`.
3. Join/intersect/union them through `ifc_entities.id` only.
4. Run an SQL relationship filter returning `ifc_relationships.id`.
5. Run relationship vector search returning `rag_documents.relationship_id`.
6. Join them through `ifc_relationships.id` only.
7. Traverse a retrieved relationship through `relationship_members.entity_id` to its endpoint entities.
8. Confirm all results remain within the selected `source_model_id`.

Do not use names, parsed prose, or approximate matching as identity keys.

## Idempotency validation

On the unchanged second complete run:

- no duplicate source model is created
- no duplicate entity, relationship, member, or RAG document is created
- canonical structured IDs remain unchanged
- RAG row counts remain unchanged
- unchanged embeddings are not unnecessarily duplicated
- all uniqueness and source-isolation constraints remain satisfied

## Completion report

Report:

1. Files and architecture changed.
2. Exact commands and notebook execution performed.
3. Task 02-1 preflight evidence.
4. Migration behavior, including obsolete `element_vectors` handling.
5. CUDA device, model, batch counts, and elapsed times.
6. The `0x101` mitigation changes, smoke-test results, tokenizer limit, thread limits, and resumability evidence.
7. Complete entity/relationship/document/vector reconciliation.
8. Sample source-scoped similarity results for both document kinds.
9. SQL/RAG canonical-identity integration results.
10. Multi-IFC isolation guarantees.
11. Idempotency and completed-vector skipping results.
12. Warnings, truncations, unresolved endpoints, or blockers.
13. Explicit confirmation:

   ```text
   Structured entities and relationships: VALIDATED
   Unified rag_documents table: CREATED AND VALIDATED
   Entity vectors: GENERATED AND VALIDATED
   Relationship vectors: GENERATED AND VALIDATED
   Canonical SQL/RAG identities: VALIDATED
   Path-only notebook pipeline: EXECUTED AND VALIDATED
   CLOCK_WATCHDOG_TIMEOUT mitigations: IMPLEMENTED AND VALIDATED
   CUDA recovery batch size: 4
   ```

Rename this file to `tasks/task03_done.md` only after every acceptance criterion passes. If blocked or incomplete, leave it as `tasks/task03.md`.

## Acceptance criteria

Task 03 is complete only when:

1. Task 02-1 is complete for the exact current source model.
2. pgvector is enabled in the existing database.
3. One common `rag_documents` table stores both document kinds with enforced canonical source references.
4. Every eligible entity has exactly one active entity-description vector for the current versions.
5. Every IFC relationship has exactly one active relationship-description vector for the current versions.
6. All embeddings are valid, normalized, and 1024-dimensional.
7. The batch-size-64 path is removed or rejected, and the recovery run uses batches of 4.
8. Token-aware limits, conservative thread limits, staged CUDA smoke tests, per-batch commits, hashes, skipping, and resume behavior are implemented and validated.
9. All document/vector counts reconcile with structured source counts.
10. SQL and RAG results combine through canonical entity and relationship IDs.
11. Every default query and vector search is isolated by `source_model_id`.
12. The complete pipeline runs from `ifc_to_db(ifc_path)` and the reusable notebook by changing only the IFC path.
13. The unchanged second run produces no duplicates or canonical-ID changes and skips already-valid vectors.
14. No further system instability occurs during the staged and full recovery run; if it does, the task remains incomplete and execution stops.
15. Credentials and `.env` contents remain protected.
