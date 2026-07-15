# Workflow

Authoritative, current development workflow for the three independent
applications. `specs/` are the project blueprints; `tasks/` are smaller
updates/fixes merged into the relevant spec when done.

## Architecture boundary

```text
ingestion  ──writes──►  PostgreSQL  ◄──reads (read-only)──  backend  ──►  frontend (future)
```

PostgreSQL is the only runtime integration boundary. The backend never imports
ingestion code and never writes BIM corpus data.

## Ingestion (Conda `bim_rag`, Python 3.11)

```powershell
conda activate bim_rag
cd ingestion
pip install -e .          # editable install from ingestion/
pytest                    # offline unit/regression suite
```

- Public entry point: `ifc_to_db(ifc_path)` (`bim_rag.pipeline_structured`).
- Console scripts: `bim-stage1`, `bim-stage2`, `bim-pipeline`.
- Notebooks: `ingestion/notebooks/01_structured_import.ipynb`,
  `02_vectorize.ipynb` (single-path `ifc_to_db` invocation).
- Schema/role admin (ingestion-owned): `bim_rag.db_admin.apply_catalog_migration`,
  `bim_rag.db_admin.bootstrap_readonly_role`.
- Do not commit experiment outputs (logs, generated vectors) unless approved.

## Backend (pyenv-win Python 3.11 + Poetry)

```powershell
cd backend
poetry install
poetry run uvicorn app.main:app --reload      # authoritative dev command
poetry run pytest                             # offline; zero OpenAI calls
poetry run pytest tests/query_live            # live read-only PostgreSQL tests
```

- Application layout: `backend/app/{api,config,db,evaluation,llm,query,shared,viewer}`.
- `app.main:app` == the FastAPI app (same public endpoints as before Task 09).
- Backend owns its DB models (`app/db/models.py`, read-only) and DB config
  (`app/config/database.py`). No `bim_rag` imports.
- Query embedding uses BAAI/bge-m3 (dim 1024) and is validated against the stored
  corpus vectors at query time (`app/query/rag/search.py::check_compatibility`).

## Frontend

Unimplemented placeholder (`frontend/`). Not built in the current task.

## Conventions

- Work one spec version at a time; do not implement beyond the active spec.
- Plan before coding; run tests after coding.
- After a task in `tasks/` is performed, merge its content into the appropriate
  spec and rename the task file `<name>_done.md`.
- All GitHub actions are performed manually by the user.
