# Task 09: Separate Ingestion, Backend, and Frontend Applications

## Prerequisites

Require:

```text
tasks/task03_done.md
tasks/task08_done.md
specs/spec_v001_ifc_to_db.md
specs/spec_v002_query_architecture.md
specs/spec_v003_sql_query_path.md
specs/spec_v004_rag_query_path.md
specs/spec_v005_hybrid_query_orchestration.md
```

Tasks 01-08 are complete. Treat their observable ingestion and query behavior as the
regression baseline. This task is an architectural separation and environment-management
refactor, not a redesign of the completed IFC ingestion or BIM query features.

## Owner intent: authoritative project direction

The repository must contain three independent applications:

1. **Ingestion** converts an IFC file into the PostgreSQL BIM tables and stored vectors.
2. **Backend** reads the already-created PostgreSQL data and provides the FastAPI
   SQL/RAG/graph/hybrid query service.
3. **Frontend** will later provide the Three.js BIM viewer and chat interface.

The PostgreSQL database is the **only runtime integration boundary** between ingestion and
backend. The backend must not import ingestion Python code, depend on the ingestion package,
invoke ingestion functions, parse IFC files, create BIM tables, run BIM schema migrations,
or generate stored corpus vectors. Ingestion must not import backend code or call the backend.

The backend may independently implement the code it needs to understand and query the
database contract. Similar-looking database models or configuration logic in the two
applications are acceptable and intentional: independence is more important than removing
this small amount of duplication.

Preserve the completed backend's external behavior. Moving and decoupling code must not
change query planning, SQL/RAG/graph/hybrid behavior, prompts, response contracts, session
behavior, viewer actions, grounding rules, safety limits, or read-only database behavior.

For minor implementation choices not fixed below, use sound engineering judgment. Do not use
that discretion to change this owner intent, introduce a shared runtime Python package, merge
the applications, or expand the product scope.

## Target repository boundary

Use independently managed top-level projects rather than one umbrella `src/` directory:

```text
BIM_RAG/
├── ingestion/
│   ├── pyproject.toml
│   ├── environment.yml
│   ├── src/
│   │   └── bim_rag/
│   ├── tests/
│   ├── notebooks/
│   └── ... ingestion-owned IFC inputs or supporting files as appropriate
├── backend/
│   ├── .python-version
│   ├── pyproject.toml
│   ├── poetry.lock
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py
│   │   ├── api/
│   │   ├── config/
│   │   ├── db/
│   │   ├── evaluation/
│   │   ├── llm/
│   │   ├── query/
│   │   ├── shared/
│   │   └── viewer/
│   └── tests/
├── frontend/
│   ├── src/
│   └── tests/
├── specs/
├── tasks/
├── docs/
├── CODEX.md
├── PROJECT_CONTEXT.md
├── README.md
└── workflow.md
```

The exact placement of ingestion-only data files may be chosen after auditing path usage, but
their ownership must be unambiguous. Do not leave a second working copy of moved code behind.
Do not create a shared `common`, `core`, `models`, or utility package used by both applications.

Keep `specs/`, `tasks/`, and project-level documentation at the repository root. Completed
task files are historical records and must not be rewritten to pretend they used the new paths.
Current README/workflow documentation must describe the new authoritative paths and commands.

## Phase 1: Audit before mutation

Before moving files:

1. Inventory all Python modules, tests, notebooks, console scripts, DDL files, prompt files,
   evaluation assets, runtime logs, and configuration files.
2. Search the entire repository for imports and literal paths involving:
   - `src/bim_rag`
   - `backend/src`
   - `bim_rag.*`
   - `api.app`
   - root `tests/`, `notebooks/`, `environment.yml`, and `pyproject.toml`
3. Record the current five-table row counts and other inexpensive read-only integrity checks
   needed to prove that this refactor did not mutate the BIM corpus.
4. Record the current backend API route and response-schema contracts.
5. Identify every backend dependency on `bim_rag`, including indirect imports.
6. Identify which dependencies are ingestion-only, backend-only, or required independently by
   both. The same third-party library may appear in both environments without creating an
   application-code dependency.

Do not begin moves until the audit makes all required path/import changes clear.

## Phase 2: Make ingestion an independent project

Move the existing root ingestion implementation into `ingestion/` while preserving its behavior:

- Move `src/bim_rag/` to `ingestion/src/bim_rag/`.
- Move ingestion tests from root `tests/` to `ingestion/tests/`.
- Move the ingestion notebook workflow into `ingestion/notebooks/` and update every internal
  path so the reusable IFC-to-database notebook remains executable.
- Move or recreate the ingestion-specific `pyproject.toml` under `ingestion/`.
- Move the Conda `environment.yml` under `ingestion/` and keep the environment name `bim_rag`.
- Preserve Python 3.11, IfcOpenShell, CUDA/PyTorch, Sentence Transformers, pgvector,
  SQLAlchemy, and all other dependencies required by the completed ingestion pipeline.
- Preserve the `bim-stage1`, `bim-stage2`, and `bim-pipeline` console entry points if they remain
  part of the current supported workflow.
- Preserve the public `ifc_to_db(ifc_path)` behavior and the notebook's single-path invocation.
- Preserve resumability, crash-safety constraints, text templates, hashes, model isolation,
  relationship ingestion, and vector generation behavior from Tasks 01-03.

The ingestion project remains the exclusive owner of:

- IFC parsing and extraction
- BIM database table creation and schema migration
- source-model insertion and update behavior
- relationship/member materialization
- corpus natural-language generation
- stored corpus-vector generation
- ingestion database-write credentials and operations

Do not run IFC ingestion, recreate tables, regenerate texts, regenerate embeddings, or otherwise
rewrite the current database during this task.

## Phase 3: Make backend an independent Poetry application

Refactor the backend to follow the same application-project concept used by Explorentory:

```text
backend/
├── pyproject.toml
├── poetry.lock
└── app/
    ├── __init__.py
    └── main.py
```

Requirements:

1. Use Python 3.11 managed through **pyenv-win**.
2. Use Poetry for backend dependency and virtual-environment management.
3. Configure the backend as an application project, not a distributable library:

   ```toml
   [tool.poetry]
   package-mode = false
   ```

4. Create and commit an appropriate `backend/.python-version`, `backend/pyproject.toml`, and
   `backend/poetry.lock`.
5. Make the supported development command, from `backend/`:

   ```powershell
   poetry run uvicorn app.main:app --reload
   ```

6. `app.main:app` must expose the same FastAPI application and public endpoints as the current
   `api.app:app` entry point.
7. Move current backend modules from `backend/src/` into sensible subpackages under
   `backend/app/`, updating imports and tests consistently.
8. Do not require `--app-dir` when running from `backend/`. `--app-dir` merely alters
   `sys.path`; it is not what makes an application properly structured.
9. Retain the ability to start from the repository root if useful, but document the command
   separately and keep the `backend/` command above authoritative.

The project owner explicitly authorizes Claude to:

- detect and use an existing pyenv-win and Poetry installation;
- install pyenv-win and/or Poetry if missing;
- install an appropriate available Python 3.11 patch release through pyenv-win;
- use `poetry add`, `poetry install`, and other normal Poetry environment commands;
- resolve and lock backend dependencies.

Do not replace or damage an existing pyenv, Poetry, Conda, or system Python installation. Detect
existing installations and configuration first. Use supported Windows installation methods and
report any required shell restart or PATH change instead of using unsafe workarounds.

### Backend dependency boundary

Build the lightest backend environment that preserves current behavior. Do not copy the entire
ingestion Conda environment blindly.

The backend is expected to require packages such as FastAPI, Uvicorn, Pydantic settings,
SQLAlchemy, a PostgreSQL driver, pgvector integration, OpenAI, HTTP/test tooling, and the local
query-embedding runtime. Resolve the exact dependency list from actual backend imports and tests.

The backend still has to embed user queries with the same compatible embedding model and vector
dimension as the stored corpus. Therefore, retain the necessary Sentence Transformer/PyTorch
runtime, including working CUDA behavior where currently supported, but implement and configure
it entirely inside the backend. Do not import ingestion constants or embedding functions.
IfcOpenShell and ingestion-only parsing/generation dependencies must not be backend dependencies.

## Phase 4: Eliminate all backend-to-ingestion code dependencies

After the refactor, the following must succeed from `backend/` even when `ingestion/src` is not
on `PYTHONPATH` and the ingestion package is not installed in the Poetry environment:

```powershell
poetry run python -c "from app.main import app; print(app.title)"
poetry run uvicorn app.main:app --reload
```

Remove every backend import of `bim_rag`, including current uses involving:

- ORM models and SQLAlchemy `Base`
- database URL helpers
- database-error sanitization
- thread/resource limits
- entity or relationship extraction wrappers
- embedding functions or constants

Delete the current backend ingestion compatibility layer after confirming no backend code uses it.
Do not retain dead wrappers “for possible future use”; user IFC upload and backend-triggered
ingestion are not part of the current application direction.

### Backend-owned read contract

Create backend-owned, read-oriented database definitions for all five existing tables:

```text
ifc_source_models
ifc_entities
ifc_relationships
relationship_members
rag_documents
```

These definitions must match the live database schema and preserve the common identifiers that
allow SQL, RAG, and graph results to refer to the same BIM objects. Use backend-owned SQLAlchemy
models/Core definitions as appropriate. Do not import the ingestion definitions.

The backend must remain read-only with respect to BIM corpus data:

- no table creation, alteration, dropping, or migration;
- no ingestion, corpus upsert, or vector regeneration;
- no mutation of source models, entities, relationships, members, or RAG documents;
- no fallback to ingestion/superuser credentials for ordinary backend operation.

Move any still-required schema-creation or migration utilities out of the backend and into
ingestion ownership. Remove obsolete backend mutation scripts when no longer needed. Preserve the
dedicated read-only database-role behavior established by the completed tasks.

The backend must own its database settings and sanitization. It may load the existing `db_url`
environment variable from the repository `.env`, but must never open, print, log, expose, or copy
the secret value. Claude is prohibited from reading the `.env` contents. If `db_url` cannot be
resolved through normal configuration loading, stop and report that blocker to the owner.

### Embedding compatibility contract

The backend query embedding must be compatible with stored vectors without sharing ingestion code.
Read or validate available embedding metadata from the database and independently configure the
same model/dimension. Add clear startup/runtime validation for incompatible or missing metadata.
Do not silently query vectors with a different model or dimension.

## Phase 5: Preserve backend behavior

The refactor must preserve at least:

- `/health`, `/ready`, and `POST /api/query` behavior;
- development-endpoint gating;
- stable request/response schemas and response fields;
- model catalog and active-model transitions;
- current-session history and reset behavior;
- SQL, graph, RAG, and hybrid routes;
- planner plus grounded-answer flow;
- bounded repair/retry behavior used during normal application requests;
- SQL/RAG identity reconciliation and source-model isolation;
- viewer actions and GlobalId payloads required by the future frontend;
- read-only database role and statement/result limits;
- logging redaction and absence of secrets in logs;
- graceful degraded behavior when an external dependency is unavailable.

Do not retune prompts, retrieval thresholds, evidence limits, or query logic unless a change is
strictly required to preserve behavior after decoupling. Any such change must be narrowly justified
and covered by a regression test.

## Phase 6: One-time OpenAI connectivity check, then remove live API tests

The owner authorizes exactly **one new live OpenAI API request attempt** during this task, solely to
confirm that the updated `OPENAI_API_KEY` can connect successfully.

Rules:

1. Use the configured backend OpenAI client/model or an equivalent minimal one-off command.
2. Make exactly one provider request attempt. Disable SDK/provider automatic retries for this
   check so a failure cannot create additional requests.
3. Keep input and output minimal. Do not run the full benchmark and do not execute the existing
   live OpenAI pytest module, because it contains multiple tests and multiple model calls.
4. Never print or log the API key.
5. Record only success/failure, model name, and sanitized error category in the Task 09 completion
   report. Do not persist response content unless required to diagnose a failure.
6. If the single attempt fails, do not retry. Report the sanitized failure and continue with all
   offline refactoring/tests that remain possible.
7. Delete `backend/tests/query_live/test_hybrid_live_openai.py` after the one-time check.
8. Remove any other test behavior that can make a real OpenAI request merely because
   `OPENAI_API_KEY` exists.
9. Do not add `RUN_LIVE_OPENAI_TESTS`, a replacement live-test module, a reusable connectivity
   script, or any other sustainable live OpenAI test setup. The owner explicitly does not want one.
10. Normal `pytest` execution must make zero OpenAI API calls and must use mocks/fakes for LLM
    behavior.

This one-time connectivity check is not an authorization for repeated calls, benchmark execution,
prompt experimentation, or paid API evaluation.

## Phase 7: Retry the previously blocked temporary-directory test

The earlier failure of
`test_write_jsonl_event_writes_redacted_line` occurred during pytest `tmp_path` setup, before the
application assertion, because the managed Codex environment denied access to pytest's temporary
directory. It was not evidence of a logging-code defect.

After the Poetry backend environment and paths are established, run that test again using a
backend-local writable base temporary directory, for example:

```powershell
cd backend
poetry run pytest tests/test_logging_redaction.py::test_write_jsonl_event_writes_redacted_line `
  -q --basetemp .pytest-tmp -p no:cacheprovider
```

Delete the temporary directory after the run. If environment permissions still prevent fixture
creation, distinguish that setup error from an application failure and report the exact sanitized
cause. Do not weaken or delete the logging-redaction test to obtain a passing result.

## Phase 8: Validation

### Static and structural validation

Verify:

- no `backend/app` or `backend/tests` import references `bim_rag`;
- backend Poetry dependency metadata does not depend on the ingestion project;
- backend starts without adding `ingestion/src` or the old root `src` to `PYTHONPATH`;
- the old root `src/` and `backend/src/` working-code trees are gone after successful migration;
- no duplicated stale implementation remains at the old paths;
- frontend remains a separate placeholder and was not accidentally implemented;
- all current documentation points to authoritative paths and commands;
- no secret or `.env` content appears in tracked files, logs, test output, or reports.

### Ingestion regression validation

From `ingestion/`, use the existing `bim_rag` Conda environment and run the ingestion unit/regression
suite without performing live ingestion or vector generation. Verify imports and console entry
points. Do not alter the database.

### Backend regression validation

From `backend/`, use only Poetry's pyenv-win Python 3.11 environment:

1. Install from `poetry.lock`.
2. Run formatting/lint/import checks used by the project.
3. Run all offline backend tests.
4. Run live read-only PostgreSQL integration tests where available.
5. Ensure tests make zero OpenAI calls after the authorized one-time check.
6. Start FastAPI with `poetry run uvicorn app.main:app --reload` and verify health/readiness.
7. Exercise representative SQL, graph, and vector retrieval paths without changing corpus data.
8. Confirm the frontend-facing API and viewer-action contracts remain unchanged.

### Database non-mutation validation

Compare the before/after read-only database snapshot. At minimum confirm unchanged counts for all
five tables, unchanged source-model identity, and no evidence of corpus/vector regeneration. A
code/environment refactor must not change stored BIM information.

## Prohibited actions

- Do not run IFC ingestion or stored-vector generation.
- Do not create, drop, truncate, migrate, or rewrite BIM database tables.
- Do not modify BIM corpus records to make tests pass.
- Do not introduce a shared Python package between ingestion and backend.
- Do not retain backend imports from `bim_rag`.
- Do not add IFC upload or backend-triggered ingestion behavior.
- Do not implement the frontend in this task.
- Do not change public API behavior or frontend contracts without an explicit blocker and owner
  approval.
- Do not make more than one new OpenAI provider request attempt.
- Do not keep an automatic or opt-in live OpenAI pytest setup after the one-time check.
- Do not expose `.env`, `db_url`, `OPENAI_API_KEY`, database credentials, or complete DSNs.
- Do not remove completed specs/tasks or rewrite their historical completion reports.
- Do not report sandbox/setup failures as application-code failures.

## Documentation updates

Update the current authoritative documentation, including `README.md`, `workflow.md`, and relevant
current architectural notes, to explain:

- the three independent applications and database-only boundary;
- ingestion setup and Conda commands;
- backend pyenv-win/Poetry setup and commands;
- the supported backend command from `backend/`;
- the absence of backend IFC ingestion behavior;
- database schema ownership and backend read-only responsibility;
- frontend placeholder status;
- offline test commands and the fact that normal tests never call OpenAI.

Do not alter `CODEX.md`; it already correctly defines Codex as the Markdown-only planning/review
manager and Claude as the implementation agent.

## Acceptance criteria

Task 09 is complete only when all of the following are true:

1. `ingestion/`, `backend/`, and `frontend/` are visibly independent top-level projects.
2. Ingestion remains functional in the `bim_rag` Conda environment with Python 3.11.
3. Backend uses pyenv-win Python 3.11 and Poetry application mode with a committed lockfile.
4. Backend runs from `backend/` with:

   ```powershell
   poetry run uvicorn app.main:app --reload
   ```

5. Backend has no imports or runtime dependency on the ingestion project/package.
6. PostgreSQL is the only runtime connection between ingestion and backend.
7. Backend independently and read-only accesses all five existing tables.
8. SQL, graph, RAG, hybrid, session, viewer-action, and API behavior pass regression validation.
9. The database corpus and stored vectors are unchanged.
10. Exactly one new OpenAI provider request was attempted, with no automatic retry.
11. The existing live OpenAI pytest module is deleted and normal tests cannot call OpenAI.
12. The previously blocked logging-redaction test passes, or a genuine environment-only permission
    blocker is precisely documented.
13. Frontend remains an unimplemented independent placeholder.
14. Documentation contains no obsolete current setup commands or contradictory architecture.
15. No credential or secret was read, printed, logged, committed, or exposed.

## Required completion report

When complete, rename this file to `tasks/task09_done.md` and append a detailed completion report
covering:

- final directory tree;
- files moved, removed, and materially changed;
- ingestion and backend environment setup;
- Python and dependency versions selected;
- proof that backend runs without ingestion installed/importable;
- removed backend-to-ingestion dependencies and their backend-owned replacements;
- one-time OpenAI connectivity result and confirmation of exactly one attempt;
- confirmation that the live OpenAI test module was deleted;
- temporary-directory test result and root cause if still blocked;
- ingestion and backend test commands/results;
- backend startup and representative endpoint results;
- before/after database integrity counts;
- confirmation that ingestion/vector generation did not run;
- remaining limitations or genuine blockers;
- explicit final statuses:

```text
Ingestion application independence: VALIDATED
Backend application independence: VALIDATED
Database-only integration boundary: VALIDATED
Backend Poetry/pyenv-win environment: VALIDATED
Backend behavior regression: VALIDATED
Database corpus non-mutation: VALIDATED
One-time OpenAI connectivity check: SUCCESS or FAILED (NO RETRY)
Automatic live OpenAI tests: REMOVED
Frontend implementation: DEFERRED
```

Do not rename the task to `_done` if any required architectural separation, regression validation,
or non-mutation criterion remains incomplete.

---

# Task 09 Completion Report

## Final directory tree (top levels)

```text
BIM_RAG/
├── ingestion/                      # Conda `bim_rag`, Python 3.11
│   ├── pyproject.toml              # setuptools; name=bim_rag; bim-stage1/2/pipeline
│   ├── environment.yml
│   ├── ifc_original/               # IFC source input (ingestion-owned)
│   ├── notebooks/                  # 01_structured_import, 02_vectorize
│   ├── src/bim_rag/
│   │   ├── config.py schema/ ifc_parser.py rel_parser.py pipeline*.py ...
│   │   ├── schema/models.py        # 5 canonical + 2 catalog tables (+ migrations/)
│   │   └── db_admin/               # apply_catalog_migration, bootstrap_readonly_role
│   └── tests/                      # 158 tests
├── backend/                        # pyenv-win 3.11.9 + Poetry (package-mode=false)
│   ├── .python-version (3.11.9)
│   ├── pyproject.toml  poetry.lock
│   ├── app/
│   │   ├── __init__.py  main.py     # app.main:app == FastAPI app
│   │   ├── api/ config/ db/ evaluation/ llm/ query/ shared/ viewer/
│   │   ├── config/database.py       # backend-owned get_db_url/sanitize_db_error/THREAD_LIMIT
│   │   └── db/models.py             # backend-owned read-only ORM (5 canonical + 2 catalog)
│   └── tests/                       # 235 tests (offline + live read-only)
├── frontend/                       # unimplemented placeholder (untouched)
├── specs/  tasks/  docs/
└── README.md  workflow.md  PROJECT_CONTEXT.md  CODEX.md
```

## Files moved / removed / materially changed

Moved (git rename): `src/bim_rag/` to `ingestion/src/bim_rag/`; root `tests/` to
`ingestion/tests/`; `notebooks/` to `ingestion/notebooks/`; `ifc_original/` to
`ingestion/ifc_original/`; `environment.yml` to `ingestion/`; `backend/src/*` to
`backend/app/*`; `apply_catalog_migration.py` and `bootstrap_readonly_role.py` to
`ingestion/src/bim_rag/db_admin/`; `backend/app/db/migrations/` to
`ingestion/src/bim_rag/schema/migrations/`.

Removed: `backend/app/ingestion/` (entire `bim_rag` compatibility-shim layer);
`backend/tests/test_ingestion_compat.py`; `backend/tests/query_live/test_hybrid_live_openai.py`
(after the one-time check); root `pyproject.toml`; stale tracked
`src/bim_rag.egg-info/` and committed `__pycache__/*.pyc` (33 files).

Created: `ingestion/pyproject.toml`; `ingestion/src/bim_rag/db_admin/__init__.py`;
`backend/pyproject.toml`, `backend/poetry.lock`, `backend/.python-version`;
`backend/app/__init__.py`, `backend/app/main.py`, `backend/app/config/database.py`;
rewrote `backend/app/db/models.py` (backend-owned Base + 7 tables).

Materially changed: backend module imports rewritten from top-level roots
(`api|config|db|...`) to `app.*` (76 files); all `bim_rag.*` imports removed and
repointed to backend-owned modules; test monkeypatch string targets prefixed with
`app.`; `ingestion/src/bim_rag/config.py` `.env`/IFC path resolution updated for the
new location; catalog models added to `bim_rag/schema/models.py`; README.md and
workflow.md rewritten; five `docs/*.md` given a "superseded by Task 09" banner;
spec_v002 given a Task 09 addendum.

## Environments and versions

- Ingestion: Conda env `bim_rag`, Python 3.11.15, torch 2.11.0+cu128 (CUDA 12.8,
  RTX 5080), IfcOpenShell, Sentence Transformers, pgvector, SQLAlchemy 2.x.
  Reinstalled editable (`pip install -e ingestion/`).
- Backend: pyenv-win Python 3.11.9, Poetry 2.1.4 application project
  (`package-mode = false`), in-project `.venv`. Deps: fastapi, uvicorn[standard],
  pydantic/pydantic-settings, sqlalchemy 2.0.51, pgvector, psycopg2-binary,
  python-dotenv, openai, torch 2.11.0+cu128 (via explicit `pytorch-cu128` source),
  sentence-transformers; dev: pytest 9.1.1, httpx, ruff. Locked in `poetry.lock`.

## Backend independence proof

From `backend/` in the Poetry env (ingestion not installed / not on PYTHONPATH):

```text
bim_rag importable in backend env: False
APP TITLE: BIM RAG Query API
torch 2.11.0+cu128 cuda True
```

`grep` confirms zero `from|import bim_rag` statements under `backend/app` and
`backend/tests`; `backend/pyproject.toml` has no ingestion/bim_rag dependency.

## Removed backend-to-ingestion dependencies and backend-owned replacements

| Removed import | Backend-owned replacement |
|---|---|
| `bim_rag.schema.models` (Base + 5 canonical models) | `app.db.models` (backend-owned Base + read-only ORM, incl. catalog tables) |
| `bim_rag.config.get_db_url` | `app.config.database.get_db_url` (reads shared repo-root `.env`) |
| `bim_rag.config.sanitize_db_error` | `app.config.database.sanitize_db_error` |
| `bim_rag.config.THREAD_LIMIT` | `app.config.database.THREAD_LIMIT` |
| `backend/app/ingestion/*` shims over `bim_rag.ifc_parser/rel_parser/stage2_embed` | deleted (no backend code used them) |

Embedding compatibility contract preserved by existing runtime validation
(`app/query/rag/search.py::check_compatibility` reads stored `embedding_model`/
`embedding_dim` and raises `IncompatibleEmbeddingError` on mismatch).

## One-time OpenAI connectivity check

Exactly ONE provider request attempt, SDK auto-retries disabled
(`OpenAI(..., max_retries=0)`), minimal input/output, key never printed:

```text
RESULT: SUCCESS
MODEL: gpt-5-nano
FINISH_REASON: length   (reasoning model consumed the 32-token cap; connection confirmed)
```

An earlier invocation failed at import (`ModuleNotFoundError: app`) BEFORE any
network call, so it consumed no provider request. `test_hybrid_live_openai.py`
deleted afterward. No other test can make a real OpenAI call (remaining references
use fakes: `_FakeOpenAI`, `FakeLLMClient`).

## Temporary-directory (logging-redaction) test

```powershell
poetry run pytest tests/test_logging_redaction.py::test_write_jsonl_event_writes_redacted_line `
  -q --basetemp .pytest-tmp -p no:cacheprovider
```

Result: 1 passed (temp dir removed after). The earlier Codex failure was an
environment permission issue in fixture setup, not an application defect.

## Test commands and results

- Ingestion (`ingestion/`, Conda `bim_rag`): `pytest` -> 158 passed. Console entry
  points `bim-stage1/2/pipeline` registered; `ifc_to_db` importable;
  `bim_rag.db_admin.*` and catalog models import cleanly.
- Backend (`backend/`, Poetry): `poetry run pytest` -> 235 passed, 0 failed,
  including live read-only PostgreSQL integration tests; zero OpenAI calls.
- Lint: `ruff check` clean for both `backend/{app,tests}` and `ingestion/{src,tests}`.

## Backend startup and endpoints

`poetry run uvicorn app.main:app` (from `backend/`):

```text
HEALTH: {"status":"ok"}
READY:  {"status":"ok","database":{"ok":true,"error":null}}
```

Public contract preserved (`POST /api/query`, `/health`, `/ready`); `/ready`
confirms the dedicated read-only role connects.

## Database integrity (before == after)

| table | count |
|---|---|
| ifc_source_models | 1 |
| ifc_entities | 6989 |
| ifc_relationships | 3473 |
| relationship_members | 17668 |
| rag_documents | 10462 |

Source-model identity unchanged (id=1, IFC2X3, fingerprint 57fafa59..., total=843172,
eligible=6989). Embedding metadata unchanged (BAAI/bge-m3, dim 1024, v001, all 10462).
No IFC ingestion, table create/drop/migrate, or vector generation was run.

## Remaining limitations / blockers

- Frontend intentionally deferred (placeholder only).
- Backend `.env` `db_url`/`DATABASE_URL`/`OPENAI_API_KEY` are loaded via normal
  config loading; their values were never read, printed, logged, or committed.
- `docs/architecture_v00x.md`, `pipeline_v001.md`, `evaluation_v001_report.md` are
  historical records; each carries a banner pointing to the authoritative
  README/workflow rather than being rewritten.

## Final statuses

```text
Ingestion application independence: VALIDATED
Backend application independence: VALIDATED
Database-only integration boundary: VALIDATED
Backend Poetry/pyenv-win environment: VALIDATED
Backend behavior regression: VALIDATED
Database corpus non-mutation: VALIDATED
One-time OpenAI connectivity check: SUCCESS (NO RETRY)
Automatic live OpenAI tests: REMOVED
Frontend implementation: DEFERRED
```
