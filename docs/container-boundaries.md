# Container boundaries

What lives in an image, what lives on your disk, and why the line is drawn where
it is. Every rule here is enforced by a test in
`backend/tests/test_deployment_policy.py` — prose drifts, assertions do not.

## Nothing that is yours goes into an image

| Never in an image | Where it lives instead |
| --- | --- |
| **IFC models** | `ifc/` on your disk, mounted **read-only** into the import container |
| **Corpus embeddings** (`rag_documents`) | The `pgdata` volume |
| **Semantic manifests** (`model_semantics/`) | Bind mount from your disk |
| **Viewer artifacts** (`model_assets/*.frag`) | Bind mount, read-only into the backend |
| **Database contents** | The `pgdata` volume |
| **Model weights** (BAAI/bge-m3) | The `hfcache` volume, downloaded on first use |
| **`.env` and every credential** | Read by Compose at runtime for substitution only |

`.dockerignore` excludes `.env`, `ifc/`, `*.ifc`, `model_assets/` and
`model_semantics/` from the build context, so none of it can reach a layer even
by accident. No Dockerfile `COPY`s any of them.

Verified against the built images, not just the config:

```
bimtrieval-backend   0 IFC, 0 artifacts, 0 manifests, no .env
bimtrieval-setup     0 IFC, 0 artifacts, 0 manifests, no .env
bimtrieval-frontend  0 IFC, 0 artifacts, 0 manifests, no .env
```

The only `.ifc` files inside any image are IfcOpenShell's own bundled schema
fixtures (`Pset_IFC4_ADD2.ifc` and similar) in the ingestion image — library
data that ships with the dependency, not building models.

**Why it matters.** An image is pushed, pulled, cached and shared. A building
model baked into one is somebody's property travelling somewhere nobody
intended, a database dump in a layer is a data breach with a version tag, and
embeddings are derived from the model and leak the same information more
quietly. Volumes and bind mounts stay on the machine that owns them.

## Ingestion is explicit, user-triggered, and read-only

The `import` service sits behind the `tools` profile, so `docker compose up`
**never** starts it. Ingestion happens only when you ask:

```bash
docker compose run --rm import "My Building.ifc"
```

The mount is `./ifc:/app/ifc:ro`. The container can read your models and cannot
modify them — no in-place repair, no rewrite, no accidental truncation of a
file you may not have another copy of.

There is no watcher, no auto-import on startup, and no upload endpoint. Parsing
a 170 MB model is expensive and writes to the corpus; it should happen because
someone decided it should, against a file they named.

## Two database roles, and the backend only gets one

PostgreSQL, your IFC data and your OpenAI key all stay local and user-owned.
Inside that local stack, the database is reached through **two separate roles**:

| Role | Held by | Can |
| --- | --- | --- |
| `${POSTGRES_USER}` (writer) | `setup`, `import` | Create schema, import models, write embeddings |
| `bim_rag_query_ro` | `backend` | `SELECT` only |

`setup` creates and grants the read-only role on every `up`, then verifies it
before exiting. The backend's environment carries **only** `DATABASE_URL`
pointing at that role — `db_url` is absent entirely, so no code path can fall
back to a writer connection that is not there.

The password is chosen by Compose (`POSTGRES_RO_PASSWORD`, with a local-only
default) and handed to both services, because there is no `.env` inside a
container for them to agree through — and **the user's `.env` is never read or
written** by any of this. The local, non-container workflow is unchanged: with
no password supplied, `bim-db-init --with-readonly-role` generates one and
persists `DATABASE_URL` to `.env` as before.

Proven from inside the running backend container, on a fresh volume:

```
connected as: bim_rag_query_ro
READ   select : OK
WRITE  CREATE : refused (permission denied)
WRITE  INSERT : refused (permission denied)
WRITE  UPDATE : refused (permission denied)
WRITE  DELETE : refused (permission denied)
```

The production overlay does the same. It previously overrode `DATABASE_URL`
with the writer DSN, silently undoing the boundary in exactly the deployment
that needs it most; it now requires `POSTGRES_RO_PASSWORD` rather than
defaulting it.

## Both loopback origins are allowed

To a browser, `http://localhost:5173` and `http://127.0.0.1:5173` are different
origins. Allowing only one made the app work or fail depending on which URL the
user happened to type, which is a confusing failure to debug. Both are in
`CORS_ALLOW_ORIGINS`; there is no wildcard and no non-loopback origin by
default.

Verified in a real browser against the running stack — both origins load the
page and complete `200 /api/models` with no CORS errors — and an unlisted origin
still receives no `Access-Control-Allow-Origin` header.

## Without an OpenAI key

Tested with an explicitly empty value; no real key is needed to check this.

The stack starts, the catalog and viewer work, and a question returns a normal
response envelope carrying:

> No OpenAI API key is configured, so questions cannot be answered yet. Set
> `OPENAI_API_KEY` in the `.env` file at the repository root and restart the
> backend. Browsing models, the 3D viewer and floor plans work without a key.

A missing key is a distinct error type from a provider outage. They need
opposite advice: retrying never resolves an unset key, and telling a first-time
user to "try again shortly" sends them looking for an outage that does not
exist.

## Three images, three jobs

| Image | Size | Contains | Runs |
| --- | ---: | --- | --- |
| `frontend` | 87 MB | nginx + built assets | Always |
| `setup` | 288 MB | SQLAlchemy models, driver, migrations | Every `up`, briefly |
| `backend` | 3.88 GB | API + **query-embedding runtime** | Always |
| `import` | 2.3 GB | IfcOpenShell + embedding stack | On demand only |

### Why `setup` is separate

Schema setup ran on the ingestion image, so **every `docker compose up` pulled
2.3 GB to execute a handful of DDL statements**. Preparing a schema needs a
database driver and the models; it does not need IfcOpenShell to parse geometry
or torch to embed anything.

`docker/dbinit.Dockerfile` installs the four packages it actually uses and then
the project with `--no-deps`, so the image cannot silently regain the heavy
stack when ingestion's dependency list grows. **2.3 GB → 288 MB.**

This is safe because the import chain is genuinely light: `bim_rag/__init__.py`
is empty, and `db_admin/init_db.py` reaches only `config`, `schema.models` and
`db_admin`. A test asserts that chain imports with `ifcopenshell`, `torch` and
`sentence_transformers` made unimportable, so a future import that quietly
pulls one in fails the offline gate rather than the container build.

### Why `backend` is large, on purpose

3.88 GB is mostly torch and sentence-transformers, and they stay. Semantic
retrieval embeds the user's question with the same model the stored corpus was
embedded with (BAAI/bge-m3, dim 1024); without that runtime in the same process,
RAG does not work — it degrades to reporting that semantic search is
unavailable. A smaller backend image that cannot answer semantic questions
would be a smaller image and a worse product.

The weights themselves are **not** baked in. They download on first use into the
`hfcache` volume, so they survive restarts, stay out of every layer, and are not
redistributed by this repository.

> Local development differs: `poetry install` omits the optional `embedding`
> group so a test run does not pull a multi-gigabyte wheel. Use
> `poetry install --with embedding` when working on RAG locally. The **container
> always has it** — `docker/backend.Dockerfile` installs the CPU build
> explicitly, so a deployed instance is never missing it.

## Validating the container path

Use the tracked **1.6 KB fixture**, not a real building model:

```bash
cp frontend/tests/fixtures/smoke-wall.ifc ifc/
docker compose run --rm import smoke-wall.ifc
```

`smoke-wall.ifc` is a synthetic single-wall IFC written for this project, so it
carries no third-party licence and is safe to keep in the repository. It
exercises the same code path as a real model — parse, structure, manifest,
embed, catalog — and reports `fully_query_ready: true` in seconds instead of an
hour.

Copying it into `ifc/` leaves nothing behind: `ifc/*` is git-ignored.

A full model is the wrong tool for this. Validating with a 21 MB model took over
an hour of CPU embedding to prove exactly what the fixture proves in seconds,
and committing one to make the check convenient would put a licensed building
back in version control — the mistake this repository already made once.

## Task 35 acceptance run

One clean, secret-free integration pass on a disposable stack. Reproducible
verbatim — nothing below reads the user's `.env`, uses a real API key, touches
the host database, or needs a real building model.

### Isolation

```bash
# A throwaway env file. Every value is disposable; the key is empty on purpose.
cat > /tmp/verify.env <<'EOF'
POSTGRES_USER=bimtrieval
POSTGRES_PASSWORD=verify_only_not_a_secret
POSTGRES_DB=bimtrieval
POSTGRES_RO_PASSWORD=verify_only_ro_not_a_secret
OPENAI_API_KEY=
VITE_API_BASE_URL=http://localhost:8000
EOF

# --env-file replaces the default `.env`, so the user's is never read.
# -p gives the run its own project and therefore its own disposable volumes.
DC="docker compose --env-file /tmp/verify.env -p bimtrieval_verify"
$DC config | grep OPENAI_API_KEY        # -> OPENAI_API_KEY: ""
```

### The run

| # | Command | Result |
| --- | --- | --- |
| 1 | `$DC up -d --build` | `db`, `backend`, `frontend` all **healthy**; `setup` exited 0 |
| 2 | `$DC logs setup` | `1 applied: ['0001_…']`; role created, `SELECT` granted on all 7 tables; `Password taken from BIM_RAG_READONLY_PASSWORD; no .env was read or written`; `Verified: bim_rag_query_ro can SELECT, INSERT is rejected` |
| 3 | `$DC exec backend python -c "select current_user"` | **`bim_rag_query_ro`**; writer DSN present in backend env: **False** |
| 4 | `SELECT count(*) FROM ifc_entities` as backend | **OK** |
| 5 | `CREATE` / `INSERT` / `UPDATE` / `DELETE` as backend | **all four DENIED** (`permission denied`) |
| 6 | `$DC exec backend sh -c 'echo ${#OPENAI_API_KEY}'` | **`0`** — empty, value never printed |
| 7 | `$DC run --rm import smoke-wall.ifc` (1.6 KB fixture) | 5 entities, 9 documents, all embedded |
| 8 | `POST /api/query` with a model, no key | HTTP 200, `status: error`, *"No OpenAI API key is configured… Set OPENAI_API_KEY in the .env file… Browsing models, the 3D viewer and floor plans work without a key."* — **no crash** |
| 9 | `POST /api/query` catalog question, no key | `status: success`, *"There is 1 model available: smoke-wall.ifc (id 1) — IFC4"* |
| 10 | CORS preflight, `http://localhost:5173` | `access-control-allow-origin: http://localhost:5173` |
| 11 | CORS preflight, `http://127.0.0.1:5173` | `access-control-allow-origin: http://127.0.0.1:5173` |
| 12 | CORS preflight, `http://evil.example` | **no** `Access-Control-Allow-Origin` — refused |
| 13 | Real Chromium at both origins | `200 /api/models`, **no CORS errors**, no "backend offline" |
| 14 | `$DC down` then `$DC up -d` | `models=1 entities=5 docs=9` before **and** after; role still enforced |
| 15 | `$DC down -v --remove-orphans` | 0 volumes, 0 containers, 0 networks remaining |

### Suites

| Suite | Result |
| --- | --- |
| Backend offline (`poetry run pytest`) | **866 passed**, 239 deselected |
| Backend live (`pytest -m live`) | **235 passed**, 4 skipped |
| Ingestion offline (`pytest`) | **298 passed** |
| Ingestion live (`pytest tests_live`) | **76 passed**, 6 skipped |
| Ruff check + format, both projects | clean |

### One thing worth knowing

`docker compose down -v` does **not** stop containers started by `docker compose
run`. During this pass a leftover import container kept `hfcache` mounted, so
the volume survived the teardown until it was removed. That is documented Docker
behaviour rather than a defect here, but if an import is still running when you
tear down, use `down -v --remove-orphans` or stop it first.

## Full-cycle checks

```bash
docker compose up -d --build                       # build + start
docker compose run --rm import smoke-wall.ifc      # explicit ingestion
docker compose down && docker compose up -d        # data must survive
docker compose down -v                             # delete volumes
```

Last run:

| Check | Result |
| --- | --- |
| Fresh start, empty database | `1 applied: ['0001_...']`, read-only role created and self-verified, all services healthy |
| Backend write attempts | `CREATE`/`INSERT`/`UPDATE`/`DELETE` all refused; `db_url` absent from its environment |
| Browser at both loopback origins | `200 /api/models`, no CORS errors |
| Empty `OPENAI_API_KEY` | Setup guidance returned, no crash |
| Fixture import | exit 0, `fully_query_ready: true`, 0 warnings, 5 entities / 9 embedded documents |
| Persistence across `down`/`up` | 7,585 documents before, 7,585 after; `setup` re-ran idempotently |
| `down -v` | Both volumes and all containers removed |
| Image contents | No IFC, embeddings, artifacts, manifests or `.env` in any image |
