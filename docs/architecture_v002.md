# BIM RAG v002 Query Architecture: Scaffold Commands and Documentation

Governed by `specs/spec_v002_query_architecture.md` (Task 04). This is the
shared backend/frontend foundation for the later SQL (v003), RAG (v004), and
hybrid (v005) query paths — no query path is implemented yet.

## Environment

```bash
conda activate bim_rag
pip install -e ".[query]"   # adds fastapi, uvicorn, pydantic-settings, openai, httpx
```

No new conda environment is created; `query` is an optional extra on the
existing `bim_rag` environment (`pyproject.toml`).

## Running the FastAPI skeleton

```bash
# from the repo root
PYTHONPATH=backend/src uvicorn api.app:app --reload
```

```powershell
# PowerShell equivalent
$env:PYTHONPATH = "backend\src"
python -m uvicorn api.app:app --reload
```

Endpoints:

- `GET /health` — liveness only, no dependency access.
- `GET /ready` — attempts a `SELECT 1` against the configured database
  (sanitized error, never raises); reports `degraded` rather than failing if
  the database is unreachable.
- `POST /api/query` — the only public query endpoint. Currently returns a
  stable stub envelope (`route: "clarify"`, `answer_basis:
  "insufficient_evidence"`) — no SQL/RAG/graph/hybrid execution occurs.

## Running tests

```bash
pytest              # runs tests/ (ingestion, 158 tests) + backend/tests/ (40 tests)
ruff format .
ruff check .
```

`backend/tests/` is reached via the `pythonpath = ["backend/src"]` pytest
ini option (`pyproject.toml`), so backend modules import with plain
top-level names (`config`, `db`, `api`, `llm`, `query`, `viewer`,
`evaluation`, `shared`) — there is no wrapper package name under
`backend/src/`.

## Package layout

```text
backend/src/
├── config/     settings (OPENAI_API_KEY, planner/answer model, limits/timeouts), JSONL logging + redaction
├── db/         catalog metadata ORM (additive, NOT migrated), lazy session/engine, read-only repo interface
├── ingestion/  compatibility shims over src/bim_rag/* — no ingestion code moved (see ingestion/README.md)
├── llm/        QueryPlan schema (spec_v002 Section 8), LLMClient interface, prompts/ locations
├── query/      SessionState + reset(), QueryService (stub), catalog/sql/graph/rag/hybrid package skeletons
├── api/        FastAPI app, routes (health, query), request/response schemas
├── viewer/     ViewerActions schema + stable-shape builder
└── evaluation/ BenchmarkCase schema + loader, precision/recall metrics

backend/tests/  40 tests covering every item in tasks/task04.md "Required verification"
frontend/       directory skeleton only (spec_v002 Section 19); no implementation
```

See `backend/src/ingestion/README.md` for the intended future migration path
(moving `src/bim_rag/*` into `backend/src/ingestion/*` for real, as a
dedicated, regression-tested refactor task — not part of Task 04).

## Catalog migration proposal (NOT EXECUTED)

`backend/src/db/models.py` defines `ModelFamily` and
`SourceModelCatalogEntry` — additive tables referencing `ifc_source_models.id`
by foreign key. The reviewable DDL mirror is
`backend/src/db/migrations/0001_catalog_metadata_proposal.sql`. Neither the
ORM module nor any test calls `create_all` or otherwise applies this
migration; `test_catalog_models.py::test_import_does_not_execute_a_migration`
asserts this explicitly.

## Verification performed

- 198/198 tests pass (158 pre-existing ingestion tests unchanged + 40 new
  backend/tests).
- `ruff format` / `ruff check` clean on all new files.
- Manual smoke check: `uvicorn api.app:app` booted; `GET /health`,
  `GET /ready` (real, read-only `SELECT 1` against the configured database —
  succeeded, nothing written), and `POST /api/query` (stub envelope, no
  OpenAI/SQL/RAG call) all returned the expected shapes.

## Stop condition (tasks/task04.md)

```text
Catalog database migration: NOT EXECUTED
Production OpenAI calls: NOT EXECUTED
SQL path: NOT IMPLEMENTED
RAG query path: NOT IMPLEMENTED
Hybrid orchestration: NOT IMPLEMENTED
```
