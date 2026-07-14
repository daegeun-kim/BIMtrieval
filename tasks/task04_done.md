# Task 04: Build the Shared Query Architecture Foundation

## Governing specification

Implement only the shared foundation defined by:

```text
specs/spec_v002_query_architecture.md
```

The completed IFC ingestion/vector pipeline in Tasks 01–03 is production baseline behavior and must remain functional.

## Objective

Create the backend/frontend project boundaries and shared contracts required by the later SQL, RAG, and hybrid paths. Do not implement the complete paths in this task.

## Required work

1. Create the approved top-level `backend/` and `frontend/` structure.
2. Add backend packages for configuration, database access, LLM contracts, query paths, API, viewer actions, evaluation, and shared types/errors.
3. Add a minimal FastAPI application skeleton and health/readiness behavior.
4. Add configuration for `OPENAI_API_KEY`, planner model, answer model, database URL, limits, and timeouts without reading or exposing secrets during development.
5. Define Pydantic base schemas for:
   - query scope and route
   - session/query request
   - query plan shell
   - evidence shell
   - catalog/model candidates
   - primary/context entity results
   - relationship results
   - viewer actions
   - stable `/api/query` response envelope
6. Create an LLM client interface with a configurable initial model of `gpt-5-nano`, but do not perform production OpenAI calls.
7. Create versioned prompt-file locations under `backend/src/llm/prompts/` without prematurely implementing final path prompts.
8. Define session-only state models and reset semantics.
9. Define model-catalog metadata ORM/migration code, including model families, version metadata, provenance, tags, and viewer source locations, but do not apply the migration in this task.
10. Create JSONL logging/evaluation interfaces and safe redaction helpers.
11. Add compatibility boundaries so existing ingestion code continues working from its current location.
12. Document the intended import/migration path; do not broadly relocate ingestion modules.

## Authorized actions

Claude may create/modify code, tests, dependency declarations, documentation, and non-executed migrations. It may run static checks, unit tests, FastAPI test-client tests, and import checks that do not mutate the target database or call OpenAI.

## Prohibited actions

- Do not apply catalog database migrations.
- Do not modify or repopulate the five completed BIM tables.
- Do not regenerate embeddings.
- Do not perform real OpenAI API calls.
- Do not implement complete SQL, RAG, graph, or hybrid engines.
- Do not implement the actual Three.js frontend.
- Do not move working ingestion code wholesale.
- Do not expose `.env`, `db_url`, or `OPENAI_API_KEY`.

## Required verification

- Existing ingestion/vector tests still pass.
- New packages import cleanly.
- Shared Pydantic schemas accept valid examples and reject invalid scope/route/viewer combinations.
- Reset clears session state but not persistent-data references.
- Viewer action schemas always produce a stable shape.
- FastAPI health tests pass without database or OpenAI access.
- Secret redaction tests pass.
- Proposed catalog schema is additive and reviewable.

## Deliverables

- Shared folder/package structure
- FastAPI skeleton
- configuration system
- base schemas and interfaces
- catalog migration proposal
- viewer-action contract
- session-state contract
- safe JSONL logging foundation
- tests and architecture notes
- a file-change and test report

## Stop condition

Stop after scaffolding and safe tests. Report explicitly:

```text
Catalog database migration: NOT EXECUTED
Production OpenAI calls: NOT EXECUTED
SQL path: NOT IMPLEMENTED
RAG query path: NOT IMPLEMENTED
Hybrid orchestration: NOT IMPLEMENTED
```

Rename to `task04_done.md` only when all criteria pass.

