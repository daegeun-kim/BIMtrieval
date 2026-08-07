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
| Fresh start, empty database | `1 applied: ['0001_catalog_metadata_proposal']`, all services healthy |
| Fixture import | exit 0, `fully_query_ready: true`, 0 warnings, 5 entities / 9 embedded documents |
| Persistence across `down`/`up` | 7,585 documents before, 7,585 after; `setup` re-ran idempotently |
| `down -v` | Both volumes and all containers removed |
| Image contents | No IFC, embeddings, artifacts, manifests or `.env` in any image |
