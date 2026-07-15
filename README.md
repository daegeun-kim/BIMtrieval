# BIM_RAG

LLM-integrated BIM information access and visualization. An IFC building model is
ingested into PostgreSQL (structured facts + pgvector embeddings), and a query
backend answers BIM questions over that data via SQL, graph traversal, semantic
(RAG) retrieval, and a hybrid orchestration of all three.

## Three independent applications

The repository is organized as three independently managed top-level projects.
**PostgreSQL is the only runtime integration boundary between them.**

```text
BIM_RAG/
├── ingestion/   # IFC → PostgreSQL structured tables + stored corpus vectors
├── backend/     # FastAPI SQL/RAG/graph/hybrid query service (read-only on BIM data)
├── frontend/    # React/Three.js (That Open Fragments) BIM viewer + chat UI
├── scripts/     # local one-click dev launcher (Task 12)
├── specs/       # authoritative blueprints (spec_v001 … spec_v006)
├── tasks/       # smaller updates/fixes; merged into specs when done
└── docs/        # architecture and evaluation notes
```

- **Ingestion** owns IFC parsing, BIM table creation/migration, source-model
  insertion, relationship materialization, natural-language corpus generation,
  and stored-vector generation. It is the only application that writes BIM data.
- **Backend** reads the already-created PostgreSQL data. It **does not** import
  ingestion code, parse IFC files, create/migrate BIM tables, or generate stored
  corpus vectors. It owns its own read-oriented database models and configuration.
- **Frontend** (`frontend/`) is an independent React/TypeScript/Vite app. It calls
  only the backend HTTP API and never connects to PostgreSQL or OpenAI directly.

The backend must never write BIM corpus data. It connects through a dedicated
read-only PostgreSQL role and enforces statement/result limits.

## Database schema ownership

The five canonical tables and two catalog-metadata tables are **created and
migrated by ingestion**:

```text
ifc_source_models   ifc_entities   ifc_relationships   relationship_members
rag_documents       model_families   source_model_catalog_entries
```

The backend defines its own backend-owned SQLAlchemy models that mirror this live
schema for **read-only** access (`backend/app/db/models.py`). This small
definitional overlap with the ingestion schema is intentional: the two
applications are independent by design.

## Configuration

A single `.env` at the repository root holds `db_url` (and optionally
`DATABASE_URL` for the read-only backend role, and `OPENAI_API_KEY`). It is
git-ignored and shared as configuration — not as code. Secrets are never printed
or logged.

## Ingestion — setup and commands (Conda)

Ingestion uses the `bim_rag` Conda environment (Python 3.11, IfcOpenShell,
CUDA PyTorch, Sentence Transformers, pgvector, SQLAlchemy).

```powershell
conda activate bim_rag
cd ingestion
pip install -e .

# Run the pipeline (IFC → structured tables + vectors)
bim-pipeline            # or: bim-stage1  /  bim-stage2
# or the reusable notebooks in ingestion/notebooks/
```

`ifc_to_db(ifc_path)` (in `bim_rag.pipeline_structured`) is the public, idempotent
entry point. Database schema/role admin utilities live under
`ingestion/src/bim_rag/db_admin/` and are ingestion-owned:

```powershell
python -m bim_rag.db_admin.apply_catalog_migration     # additive catalog tables
python -m bim_rag.db_admin.bootstrap_readonly_role      # read-only backend role
```

## Backend — setup and commands (pyenv-win + Poetry)

The backend is a Poetry **application project** (`package-mode = false`) on
pyenv-win Python 3.11.

```powershell
cd backend
# Python 3.11 is pinned via backend/.python-version (pyenv-win)
poetry install

# Authoritative dev command (run from backend/):
poetry run uvicorn app.main:app --reload
```

`app.main:app` is the FastAPI application. Public contract: `POST /api/query`
plus `/health` and `/ready`. The backend has **no** dependency on the ingestion
project or the `bim_rag` package.

> Optional: it can also be started from the repository root, but the `backend/`
> command above is authoritative.

## Frontend — setup and commands (npm)

```powershell
cd frontend
npm install
npm run dev            # http://localhost:5173 (expects the backend at :8000)
```

See `frontend/README.md` for build/test/lint scripts and preparing a viewer artifact.

## One-click local launcher (Task 12)

`Start BIM RAG.lnk` in the repository root starts both services and opens the app:

1. Double-click `Start BIM RAG.lnk` (copy or move it to the Desktop if you like —
   it keeps working there).
2. Two visible terminal windows open: **BIM RAG Backend** (`poetry run uvicorn
   app.main:app --reload`) and **BIM RAG Frontend** (`npm run dev`). Leave them
   open; closing a terminal stops that service.
3. Once both are ready, `http://localhost:5173` opens in your default browser
   automatically (opens once, and only after both services respond).
4. Running the shortcut again reuses any already-running BIM RAG backend/frontend
   instead of starting duplicates.

To stop the services the launcher started:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\stop-dev.ps1
```

This only stops processes the launcher itself started (verified by process
identity) — a backend or frontend you started manually is left running.

**First-time setup remains manual** — the launcher never installs anything. If it
reports missing dependencies, run the command it prints (`poetry install` from
`backend/`, or `npm install` from `frontend/`), then re-launch.

**Moving the repository:** the shortcut stores an absolute path. If you move the
`BIM_RAG` folder, regenerate it and re-copy it to the Desktop:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\create-shortcut.ps1
```

**Troubleshooting:**

- *"Port already in use by another application"* — something other than BIM RAG
  is bound to `:8000` or `:5173`. The launcher will not touch it; free the port
  or stop that application yourself, then re-launch.
- *Backend terminal shows a database error* — the launcher still opens the
  frontend (it stays usable in a degraded mode), but check `.env` at the
  repository root and that PostgreSQL is reachable.
- *Frontend never becomes ready* — check the **BIM RAG Frontend** terminal for
  npm/Vite errors; a first `npm install` may be required (see above).
- Launcher-owned process bookkeeping lives in the gitignored
  `.runtime/dev-processes.json` — safe to delete if it ever looks stale; the
  launcher self-heals by re-verifying process identity on every run.

## Testing

Ingestion (from `ingestion/`, Conda `bim_rag` env):

```powershell
pytest        # offline unit/regression suite; does not run live ingestion
```

Backend (from `backend/`, Poetry env):

```powershell
poetry run pytest                 # offline suite — makes ZERO OpenAI API calls
poetry run pytest tests/query_live   # live read-only PostgreSQL integration tests
```

Normal test runs use mocks/fakes for all LLM behavior and never call OpenAI.
There is no automatic or opt-in live-OpenAI test suite.

## Formatting / linting

```powershell
ruff format .
ruff check .
```
