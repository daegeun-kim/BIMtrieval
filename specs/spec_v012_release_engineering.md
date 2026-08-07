# spec_v012 — Release engineering and portfolio hardening

## Purpose

BIMtrieval's product architecture is specified by `spec_v001`–`spec_v011`. This
specification covers everything *around* it: the test contract, continuous
integration, portable configuration, containerised delivery, published
evaluation evidence, and the public presentation of the repository.

It exists because a working local result is not a finished system. The
architecture was already sound; what was missing was the evidence that it runs
anywhere other than the author's machine, and that its tests actually gate
anything.

Tasks 32–41 implement this specification and are merged into it as they
complete.

## Shared constraints (Tasks 32–41)

- The established ingestion / read-only backend / SQL-graph-RAG-hybrid query /
  frontend architecture is preserved. Changes here are narrow and justified.
- The repository's `.env` is never read, printed, copied, or inspected. All work
  proceeds from documented configuration names and `.env.example` placeholders.
  No real credential appears in any file, image, log, test, or command output.
- Every user supplies their own `OPENAI_API_KEY` through a local `.env`. There is
  no shared-key demo, and the frontend never collects an API key.
- IFC import is a local workflow. IFC files are large; there is no browser upload
  and no public upload API.
- Default automated validation never calls OpenAI. Database, embedding-model,
  browser, and live-LLM checks are separately named.
- GitHub-side actions (push, release, settings, branch protection) remain manual
  owner steps and are documented rather than performed.

---

## 1. Test contract (Task 32)

### 1.1 The rule

Each project has exactly one **default command** that is its fast offline gate,
and any check needing a database, an embedding model, a browser, or a network is
**separately named**. A database-dependent check must never enter the default
path silently — not even to probe connectivity during collection.

| Project | Offline gate | Separately named |
| --- | --- | --- |
| `ingestion/` | `pytest` (`testpaths = ["tests"]`) | `pytest tests_live` |
| `backend/` | `poetry run pytest` (`addopts` carry `-m 'not live'`) | `poetry run pytest -m live` |
| `frontend/` | `npm test`, `npm run typecheck`, `npm run lint`, `npm run build` | `npx playwright test` |

Two different mechanisms, chosen by what each suite does at import time:

- The backend's live package hardcodes its model ids, so it is import-clean. A
  `live` marker applied by `tests/query_live/conftest.py` and deselected in
  `pyproject.toml` is enough, and the connectivity probe moved from a collection
  hook into a session fixture so a default run opens no connection at all.
- The ingestion live module resolves the imported source models *at import time*
  to parametrise over them. No marker can prevent that, because collection
  imports the module. It therefore lives in a separate `tests_live/` root that
  `testpaths` never reaches.

Both live suites skip green when the database is unreachable, so an explicit live
run in an environment without PostgreSQL is honest rather than red.

### 1.2 Portable installation

The ingestion package must install and test from the current repository path.
The Conda environment carried an editable install pointing at the repository's
former `BIM_RAG` location, so `import bim_rag` resolved to a directory that no
longer existed. Reinstated with `pip install -e ingestion/` from the real path.

### 1.3 Failures resolved

No tolerated red baseline. Every deterministic failure was classified as either a
stale expectation or incorrect behaviour, and the product contract was preserved
when correcting it.

**Stale expectations** (the code was right; the test had not followed it):

- `tests/test_settings.py` asserted a `planner_model` attribute removed when
  task25 split the LLM into three configurable roles. Rewritten against the
  `get_*_model()` accessors, which is what the client actually calls.
- `tests/query_hybrid/test_llm_retry.py` faked `chat.completions.parse`. The
  pipeline moved to the Responses API; the fake now models `responses.parse`
  and a response carrying `output_parsed`/`usage`.
- `tests/test_openai_usage_output.py` sliced the whole captured log from the
  `[OpenAI usage]` marker to the end, so it broke when task25 §6.1 added a
  separate `[OpenAI cost]` record beside it. Scoped to the one log record whose
  content it is actually about.
- `tests/binding/test_validate.py` asserted `modifier_silently_dropped` and
  `unaccounted_question_terms`, both retired by task25 §3.2 in favour of the
  typed constraint ledger. The two sections were removed; the contract they
  protected — a required modifier is never silently dropped, and the "parking
  spaces" fabrication in particular — is asserted in `tests/binding/test_ledger.py`.
- `tests/query_live/test_binding_pipeline_live.py` built its plans against Task
  24's lexical `build_slate` (`s1`, `s2`, …). task25 replaced it with a universe
  loaded from the semantic manifest and ranked by `build_recommendations`, which
  identifies candidates by manifest semantic id (`cls:IfcWall`), and made ledger
  coverage a hard gate. Every plan cited ids from the wrong slate and declared no
  ledger dispositions, so all sixteen refused before reaching the answer call.
  Fixtures now resolve candidates exactly as `run_pipeline` does and build
  dispositions from the real ledger.
- The same module's binder-boundary test forbade the literal string `global_id`
  in the binder context. The semantic manifest legitimately addresses each storey
  by GlobalId — that is model structure, and it is how a floor scope is named at
  all. Rewritten to forbid what actually matters: retrieved rows, executed SQL,
  vectors, and the identities the query resolved.
- `frontend/e2e/critical-path.spec.ts` asserted the inline `.ev-toggle` evidence
  disclosure, which the Query Explanation card (task26) replaced. The stub now
  returns `answer_explanation` and the test asserts the card. A second selector
  in the same file, `.explanation-panel`, never matched anything (the class is
  `.explain-panel`) and so proved nothing; corrected.
- `frontend/tests/viewer-plan-mode.test.ts` asserted the non-wall plan contour is
  "not black", contradicting task28 §4.2, which makes it the darkest ink among
  the projected layers on purpose. Re-anchored to the theme constants, which is
  the property the test was reaching for: the black wall layer must not bleed
  into the base layer.

**Incorrect behaviour** (a real defect the test was right to catch):

> `rag_documents` carries one global HNSW index across every imported model —
> 261,943 rows — while every RAG query filters to one model + kind + document
> type, about 2.7% of the table. With pgvector's `hnsw.iterative_scan` off, the
> index scan collects `ef_search` neighbours **globally** and only then applies
> the `WHERE` clause. A filtered search therefore returned **zero** candidates
> for `top_k < 10` against 6,989 matching documents, while the same query at
> `top_k = 10` was correct only because the planner happened to choose a
> sequential scan.

Retrieving nothing reads downstream as "the model contains no such objects",
which is the worst available failure for this pipeline: silent, confident, and
wrong. Fixed in `app/db/session.py` by applying `hnsw.iterative_scan =
strict_order`, `hnsw.ef_search = 400`, and `hnsw.max_scan_tuples = 1000000` to
every connection. `strict_order` preserves exact distance ordering, which
`per_kind_rank` and the similarity thresholds both depend on; `max_scan_tuples`
keeps the scan bounded. Measured recall against an exact scan went from 0/3 to
3/3 at `top_k = 3`, with no regression at `top_k = 10` (10/10 both ways).

The settings are committed in the `connect` handler because a plain `SET` is
transactional: without the commit, the connection's first `ROLLBACK` silently
reverts them and the defect returns for the rest of that connection's life.
`tests/query_live/test_rag_search.py` gained a regression test asserting the true
nearest neighbours at small `top_k`, not merely a row count.

### 1.4 Recorded baseline

Reproduced with the commands in §1.1 on Windows 11, Conda `bim_rag` (Python
3.11.15) for ingestion and pyenv-win + Poetry (Python 3.11.9) for the backend.

| Check | Result |
| --- | --- |
| Ingestion offline `pytest` | **280 passed** |
| Ingestion `ruff check .` / `ruff format --check .` | clean / 43 files formatted |
| Backend offline `pytest` | **805 passed, 239 deselected** |
| Backend `ruff check .` / `ruff format --check .` | clean / 196 files formatted |
| Frontend `npm test` | **478 passed** (27 files) |
| Frontend `typecheck` / `lint` / `build` | clean / clean / built |
| Playwright critical path | **3 passed** |
| Backend `pytest -m live` | **235 passed, 4 skipped** |
| Ingestion `pytest tests_live` | **76 passed, 6 skipped** |

The live skips are honest: three cases need an absent result-kind concept or an
`IfcSpace` candidate that the manifest universe does not offer for those models,
and the ingestion skips are per-model capability gaps the suite already reports.

No live OpenAI benchmark was run.

### 1.5 Carried forward

Recorded here rather than fixed, because they belong to a later task in this
session:

- `frontend/src/chat/EvidenceDisclosure.tsx` is rendered nowhere. It is dead
  production code kept alive only by its own unit tests, and it is what the
  stale e2e selector was pointing at.
- `app/query/binding/validate.py` still carries the retired
  `_validate_modifier_coverage`, `_validate_question_coverage`, and
  `_UNREMARKABLE_TOKENS` machinery. Nothing calls it except
  `app/api/routes/dev.py`, which reports `silently_dropped_modifiers` — now
  permanently empty, and therefore misleading.
- The frontend production bundle is 6.37 MB (1.18 MB gzipped) in one chunk.
- `frontend/tsconfig.app.tsbuildinfo` and `tsconfig.node.tsbuildinfo` are
  tracked build artifacts.

---

## 2. Continuous integration (Task 33)

### 2.1 The gate

`.github/workflows/ci.yml` runs on pull requests to `main` and pushes to `main`,
with `workflow_dispatch` for manual runs. Four jobs, all Ubuntu:

| Job | Runs |
| --- | --- |
| `ingestion` | `ruff check`, `ruff format --check`, `pytest` (Python 3.11) |
| `backend` | `poetry check --lock`, `ruff check`, `ruff format --check`, `pytest` (Python 3.11) |
| `frontend` | `npm test`, `npm run typecheck`, `npm run lint`, `npm run build` (Node 22) |
| `e2e` | `npx playwright test` (Chromium) |

Superseded runs are cancelled via a `concurrency` group on the ref. The token is
scoped to `contents: read`. The Poetry virtualenv is cached on `poetry.lock`, npm
on `package-lock.json`, pip on `pyproject.toml`. A failed e2e run uploads its
Playwright report as an artifact.

### 2.2 Secret-free by construction

The required gate uses no `.env`, no `OPENAI_API_KEY`, no database, and no
downloaded embedding model. That is precisely why the two live suites are absent
from it rather than being made conditional: a gate that skips itself when a
secret is missing is not a gate. They stay owner-run commands documented in
`README.md`.

The `e2e` job is browser-level but still secret-free — the spec stubs every
backend response and loads the small tracked fixture artifact, so it exercises
the real Fragments worker and WebGL without PostgreSQL or OpenAI.

### 2.3 Two dependency defects this exposed

Building a clean install from scratch, rather than assuming the developer
machine's environment, surfaced two real problems:

- **`numpy` was undeclared.** `app/query/semantic/ontology/loader.py` loads the
  pre-generated IFC ontology vectors with `np.load`, but numpy appeared in the
  environment only as a transitive dependency of torch. A backend install
  without torch could not even *collect* the test suite. Now an explicit
  dependency.
- **A CUDA wheel gated the test suite.** `torch = "2.11.0+cu128"` was a core
  dependency, so every install — CI, container, or a reviewer's laptop —
  downloaded a multi-gigabyte hardware-specific build to run tests that never
  load a model. Moved to an optional `embedding` group. The backend starts,
  serves SQL and graph answers, and passes its full offline suite without it;
  the RAG path reports its existing degraded mode instead of crashing.

Both are the same class of problem: a dependency set that only worked because of
what happened to already be installed.

### 2.4 Validation

The workflow was not pushed. It was validated by parsing the YAML and by running
each job's exact commands locally against **clean, from-scratch installs** that
reproduce the CI environment rather than the developer's:

| Environment | Result |
| --- | --- |
| Fresh venv, backend deps **without** torch (`pip install fastapi … numpy pytest httpx ruff`) | `pytest` **805 passed, 239 deselected**; `ruff check` clean |
| Fresh venv, CPU torch from the PyTorch CPU index + `pip install -e ingestion/` | `pytest` **280 passed**; `ruff check` clean; `ruff format --check` clean (43 files) |
| `poetry check --lock` after regenerating the lock | passes |
| Frontend `npm test` / `typecheck` / `lint` / `build` | 478 passed / clean / clean / built |
| `npx playwright test` | 3 passed |

`ifcopenshell` 0.8.5 and `torch 2.11.0+cpu` were both confirmed installable from
their public indexes, so neither job depends on the owner's Conda channel setup.

The status badge in `README.md` points at this workflow on `main`, where it will
stay accurate.

### 2.5 Manual owner actions

Not performed — they are GitHub-side:

1. Push the branch and open a pull request so the workflow registers.
2. Settings → Branches → protect `main`: require the `Ingestion`, `Backend`,
   `Frontend`, and `Critical path` checks to pass before merging.

---

## 3. Configuration, database setup, and local IFC import (Task 34)

### 3.1 `.env.example`

A root `.env.example` declares exactly three names and explains what each is
*for*, because the interesting part is not the syntax but the boundary:

| Name | Used by | Role |
| --- | --- | --- |
| `db_url` | ingestion | The write account: creates the schema, imports models. The only connection that ever writes BIM data. |
| `DATABASE_URL` | backend | The dedicated read-only role, so the API structurally cannot modify the corpus. Optional, falling back to `db_url` — which gives up the guarantee, and the file says so. |
| `OPENAI_API_KEY` | backend | The user's own key. Never shipped, proxied, or requested in the browser. |

Every value is an obvious placeholder (`CHANGE_ME`, `sk-your-own-key-here`), and
a test asserts both the exact name set and that no usable credential is present.

### 3.2 One obvious place for IFC files

`ingestion/ifc_original/` — an internal folder inside one of three sibling
projects — became **`ifc/`** at the repository root, with a README that explains
what to put there and why there is no upload button.

`bim-import` accepts either form, so nobody has to learn the convention:

```
bim-import "My Building.ifc"       # a filename, resolved in ifc/
bim-import D:\models\tower.ifc     # or any path on disk
```

A missing file names *both* places it looked, so the error tells the user what to
do rather than only that something failed. `ifc_dir` in `.env` repoints the
folder entirely, for models that live outside the repository.

### 3.3 A 63 MB model was tracked in Git

`ingestion/ifc_original/IFC Schependomlaan incl planningsdata.ifc` was committed.
`.git` is 342 MB, so cloning this repository to read three README files
downloaded a building model. Untracked, and `ifc/*` is now ignored except its
README. The other three local models (170 MB, 109 MB, 21 MB) were already
ignored and remain so.

Tests need no real model: `frontend/tests/fixtures/smoke-wall.ifc` is 1.6 KB, and
every database-backed suite skips cleanly when nothing has been imported. The
largest tracked file is now the 1.2 MB generated IFC ontology vector set, which
is a genuine runtime artifact.

Two tracked build artifacts — `frontend/tsconfig.app.tsbuildinfo` and
`tsconfig.node.tsbuildinfo` — were untracked at the same time, along with new
ignore rules for `frontend/dist/`, `playwright-report/`, and `test-results/`.

> The file remains in Git *history*, so a clone is still 342 MB. Removing it
> requires rewriting history and a force-push, which is a manual owner action —
> recorded in §3.6, not performed here.

### 3.4 `bim-db-init` — versioned and repeatable

Setting up a database previously meant knowing that `create_all()` happens
implicitly during import, that `apply_catalog_migration` exists, and that
`bootstrap_readonly_role` is separate. One command now does all of it, and is
safe to run any number of times:

1. `CREATE EXTENSION IF NOT EXISTS vector`
2. create every canonical table from the SQLAlchemy models
3. apply pending SQL migrations
4. seed catalog metadata for any imported model lacking it
5. `--with-readonly-role`: create the backend's read-only role and write its
   `DATABASE_URL` into `.env`, without ever printing the credential

Migrations gained a real ledger (`bim_rag/db_admin/migrations.py`):
`schema_migrations(version, checksum, applied_at)`, with `.sql` files applied in
filename order, each in its own transaction. Applied versions are skipped.

A file that **changed after being applied** is an error, not a silent skip — the
database no longer matches the file that claims to describe it, and continuing
would hide a real divergence. `0001_catalog_metadata_proposal.sql` was headed
"PROPOSAL — NOT EXECUTED", which had become false; it is now a real, executed,
checksum-verified migration.

### 3.5 A broken entry point, shipped

`bim-pipeline` was a documented console script in `pyproject.toml` and in
`docs/pipeline_v001.md`. It imported `run_stage1` and `run_stage2`, which no
longer exist — so it had been failing with `ImportError` on every invocation.
Removed; `bim-import` runs the same complete workflow. A test now imports every
declared console script's target and asserts it is callable, so a dead entry
point cannot ship again.

### 3.6 Validation

- `bim-db-init` run twice against the real database: first run applied
  `0001_catalog_metadata_proposal` and skipped four already-seeded catalog
  entries; second run reported `0 applied: none pending`. Additive only — no
  existing row counts changed.
- `bim-import --help` and `bim-db-init --help` resolve, and the epilog prints the
  resolved `ifc/` directory.
- Ingestion offline suite: **295 passed** (15 new in
  `tests/test_setup_entrypoints.py`), `ruff check` and `ruff format --check`
  clean.
- `git ls-files` audited: the largest tracked file is 1.2 MB.
- No `.env` was read at any point. The live database was reached only through the
  documented `db_url` the ingestion tooling loads itself.

Manual owner action, deferred (requires a force-push):

> Purge the 63 MB IFC from history with `git filter-repo --path "ingestion/ifc_original/IFC Schependomlaan incl planningsdata.ifc" --invert-paths`
> (or BFG), then force-push. Until then a clone stays ~342 MB.

---

## 4. Container environment (Task 35)

### 4.1 Shape

`docker compose up --build` brings up four services from `compose.yaml`:

| Service | Role |
| --- | --- |
| `db` | `pgvector/pgvector:pg17`, named `pgdata` volume, `pg_isready` healthcheck, **not** published |
| `setup` | Runs `bim-db-init` once and exits. The backend waits on `service_completed_successfully` |
| `backend` | uvicorn, `/health` healthcheck, published on `127.0.0.1:8000` |
| `frontend` | Vite build served by nginx, published on `127.0.0.1:5173` |
| `import` | `tools` profile — never starts with `up`. `docker compose run --rm import <file>` |

Three Dockerfiles under `docker/`, each multi-stage so compilers and Poetry stay
out of the runtime image, each running as a non-root uid 10001.

**The default path is CPU-only.** `pyproject.toml`'s optional `embedding` group
pins the owner's CUDA build; the images install `torch==2.11.0` from the PyTorch
CPU index instead, so the stack runs on any x86-64 host with no GPU and no
drivers.

### 4.2 Secrets and data

`.env` is read by Compose at runtime for variable substitution only — never
mounted, never copied, never baked into a layer. `.dockerignore` excludes `.env`,
`ifc/`, `*.ifc`, and both generated-artifact roots.

The container DSN is constructed in `compose.yaml` rather than taken from `.env`,
because the user's `db_url` points at *their host* Postgres, not this stack's
database. Environment variables outrank `.env` in both applications' settings
loaders, so the container value always wins.

Degraded states are supported, not crashes: an absent `OPENAI_API_KEY` still
starts the stack with a working viewer and catalog, and question answering says
what is missing. No IFC is committed to make the default stack look populated.

### 4.3 Two packaging defects this exposed

Building a real image, rather than trusting the developer install, found two
problems that could not surface locally:

- **The wheel shipped no SQL.** `ingestion/pyproject.toml` declared no
  package-data, so `pip install ./ingestion` produced a wheel containing zero
  `.sql` files. `bim-db-init` in the container would have read an empty
  migrations directory and reported "none pending" against a database with no
  schema — a silent no-op that looks like success. The editable install used
  everywhere locally hid it completely, because it points at the source tree.
  Fixed with `[tool.setuptools.package-data]`, and a test now asserts that every
  non-Python file under the package is matched by an install pattern.
- **`.dockerignore` `*.md` was ambiguous.** `backend/app/llm/prompts/` is a
  directory of `.md` files loaded at runtime. Docker's matching would not in fact
  have excluded them, but the intent has to be unmistakable in a file whose
  mistakes are invisible until a container misbehaves. Anchored to `/*.md`.

A speculative `Cross-Origin-Embedder-Policy: require-corp` header was also
removed from the nginx config before it shipped: the Vite dev server sets no such
header and the viewer works there, so requiring it could only have broken
cross-origin loads.

### 4.4 The `.lnk` is gone

`Start BIM RAG.lnk` — a Windows shortcut binary, committed to Git, storing an
absolute path, documented as the way to start the system — is deleted, along
with `scripts/create-shortcut.ps1` which generated it. Docker Compose is the
documented entry point. `scripts/start-dev.ps1` remains as an explicitly
secondary, optional Windows helper for a developer who has already done the
manual setup.

### 4.5 Validation — run against Docker 29.6.2 / Compose v5.3.1

| Check | Result |
| --- | --- |
| `docker compose build` | All three images built |
| `docker compose up -d` | `db`, `backend`, `frontend` all **healthy**; `setup` ran once and exited 0 |
| Schema setup on an empty database | `1 applied: ['0001_catalog_metadata_proposal']` |
| `GET /health` | `{"status":"ok"}` |
| `GET /ready` | `{"status":"ok","database":{"ok":true,"error":null}}` |
| `GET /api/models` on an empty corpus | `{"models":[]}` — a clean empty state, not an error |
| Frontend | HTTP 200 |
| Production overlay without credentials | Refuses: *"required variable POSTGRES_USER is missing a value"* |
| `import` with a missing file | Names both places it looked, exits non-zero |
| `import` with a real 21 MB model | Structured import 4,705 entities, then CPU embedding |

Two findings worth recording.

**The wheel-packaging fix is confirmed by the container, not just by
inspection.** `1 applied: ['0001_catalog_metadata_proposal']` was printed by
`bim-db-init` running from a non-editable install inside the image. Before the
`package-data` fix that line would have read `0 applied: none pending` against a
database with no schema.

**A healthcheck defect only a real run could find.** The frontend reported
`unhealthy` while serving HTTP 200 correctly. nginx listens on IPv4 only, and
Alpine's resolver tries `::1` first, so `wget --spider http://localhost/` was
refused on IPv6 against a perfectly healthy container. Both healthchecks now
probe `127.0.0.1` explicitly. Static validation could not have caught this —
the config was valid and the service worked; only the probe was wrong.

### 4.6 Data boundaries and the split setup image

Enforced by tests and written up in `docs/container-boundaries.md`.

**Nothing user-owned enters an image.** IFC models, corpus embeddings, viewer
artifacts, semantic manifests, database contents and `.env` live on disk or in
volumes. Verified against the *built* images, not just the config: zero hits for
each in all three. The only `.ifc` files present are IfcOpenShell's own bundled
schema fixtures -- library data, not building models. Model weights download at
runtime into the `hfcache` volume rather than being baked into a layer.

**Ingestion stays explicit.** The `import` service sits behind the `tools`
profile, so `docker compose up` never triggers it, and `./ifc` is mounted `:ro`
-- a container can read a model and cannot alter it. No watcher, no auto-import,
no upload endpoint.

**Schema setup was moved off the ingestion image.** It runs on every `up`, and
it was pulling 2.3 GB to execute a handful of DDL statements. `bim-db-init`
needs a driver and the models -- not IfcOpenShell to parse geometry or torch to
embed. `docker/dbinit.Dockerfile` installs four packages explicitly and the
project with `--no-deps`, so it cannot silently regain the heavy stack when
ingestion's dependencies grow: **2.3 GB -> 288 MB**. A test imports
`db_admin.init_db` with `ifcopenshell`, `torch` and `sentence_transformers` made
unimportable, so a future heavy import fails the offline gate rather than the
container build.

**The backend keeps its embedding runtime.** 3.88 GB, mostly torch and
sentence-transformers, and they stay: semantic retrieval must embed the question
with the same model the corpus used, and a smaller backend that cannot answer
semantic questions would be a worse product. Only the local `poetry install`
omits them, for test speed; the container always installs the CPU build.

**Container validation uses the 1.6 KB `smoke-wall.ifc` fixture**, which is
synthetic and carries no third-party licence. It exercises the same path --
parse, structure, manifest, embed, catalog -- and reports `fully_query_ready:
true` in seconds. Validating with a real 21 MB model took over an hour of CPU
embedding to prove the same thing, and committing one for convenience would put
a licensed building back in version control.

### 4.7 Full-cycle results

| Check | Result |
| --- | --- |
| Fresh `up` on an empty database (65 MB setup image) | `1 applied: ['0001_...']`, all services healthy |
| Fixture import via `run --rm import` | exit 0, `fully_query_ready: true`, 0 warnings |
| Persistence across `down` / `up` | 7,585 documents before and after; `setup` re-ran idempotently |
| `down -v` | Both volumes and all containers removed |
| Image content audit | No IFC, embeddings, artifacts, manifests or `.env` in any image |

Task 35 is complete. The only unvalidated container path left is the production
overlay under sustained load, which is a deployment concern rather than a build
one.

---

## 5. Published benchmark (Task 36)

### 5.1 Canonical structure

| Part | Location |
| --- | --- |
| Versioned cases | `backend/app/evaluation/benchmark_v00{1,2,3}_*.jsonl` |
| Runner + configuration | `backend/app/evaluation/` |
| Machine-readable results | `evaluation/results/benchmark_v003.json` |
| Human-readable report | `evaluation/benchmark_v003.md` |
| Index + reproduction commands | `evaluation/README.md` |

Cases and runner stay with the backend, which is the code that imports them.
Results and the report moved to a root-level `evaluation/`, because published
evidence a reviewer is meant to read should not be four directories deep inside
an application package.

### 5.2 What is published

Per-route accuracy and cost (`sql` 18/19, `rag` 3/3, `graph` 1/1, `clarify` 2/2,
`explain_general` 2/2), latency and token distribution as min/p50/p90/max rather
than a single average, coverage by query category, the corpus-isolation
snapshot, and the honest failure in full.

The README carries the headline — 26/27, 0 grounding failures, 24.6 s and 9,357
tokens median — with its caveats attached rather than deferred to a link.

### 5.3 What is deliberately NOT published

- **No cost in dollars.** The results file records tokens, not prices, and the
  run predates the versioned pricing registry. Multiplying old token counts by
  today's prices produces a number that looks precise and means nothing.
- **No run date.** It was never written into the results file. Stated as "not
  recorded" rather than reconstructed from a commit date.
- **No claim about the current pipeline.** Task 25 replaced the planner with a
  binder plus constraint ledger, and the model roster moved off `gpt-5-nano`.
  The report says plainly that these numbers describe the pipeline as it was.
- **No baseline comparison.** There is no vector-only or SQL-only arm, so this
  shows the hybrid pipeline works — not that it beats a simpler approach. Named
  in the report as the single most valuable missing measurement.

The one failing case (`rag-01`: a semantic question answered with a lexical name
filter, returning an honest zero) is published with its analysis and left
failing. Fixing it by adding "fire safety" to a prompt would fix the number and
nothing else.

### 5.4 Traceability is enforced

`backend/tests/test_published_benchmark.py` (17 tests, offline) recomputes every
published figure from `evaluation/results/benchmark_v003.json` and asserts it
appears in the report and the README: headline counts, per-route rows, medians,
percentiles, and token totals. It also asserts the *disclosures* — that every
failing case is named, that repaired and general-knowledge cases are listed, that
the unrecorded run date is stated as unknown, that no dollar cost is published,
and that the README does not overstate the result.

A published table that drifts from the results file now fails the offline gate.

### 5.5 Historical results preserved

`docs/evaluation_v001_report.md` keeps its original text — including the six
defects found and fixed during that run, which is its most useful content — under
a header stating what has since changed and why it is not corrected in place.
`specs/test_query_v1`–`v3-1` and the RAG calibration/failure-case datasets are
listed in the report as historical, not restated under current scoring.

### 5.6 Validation

- Backend offline gate: **822 passed, 239 deselected** (17 new). Ruff clean.
- No OpenAI call was made and no `.env` was read during this task.

---

## 6. Reliability and performance (Task 37)

### 6.1 The audit: most of this already existed

Against the production-readiness gaps `update_plan.md` names, the existing
implementation covers more than the review credits it with:

| Concern | State |
| --- | --- |
| Retry boundaries | One bounded application retry; SDK retries disabled so the two cannot multiply; a full timeout is deliberately not retried |
| Timeouts | `openai_timeout_s` 120 s, `db_statement_timeout_ms` 5,000, `path_timeout_s` 20 s |
| Degraded modes | Typed errors and degraded paths for embeddings, RAG, hybrid, semantic resolution, health |
| Result / query limits | Nineteen documented caps: list, graph depth, evidence, viewer identities, probes, evidence groups |
| Read-only enforcement | Dedicated `bim_rag_query_ro` role; corpus-unchanged assertions; `tests/query_live/test_security_limits.py` |
| Structured logging + redaction | `config/logging.py`, with `test_logging_redaction.py` |
| Request tracing | `request_id` propagated through a `ContextVar` |
| Prompt versioning | Version in the filename, logged with every call, traceable from a stored answer |
| Cost / latency measurement | Per-stage `stage_latency_ms`, mutually-exclusive token buckets, versioned pricing registry |

The gap was not the machinery. It was that none of it had a **stated budget**, and
that three pieces of dead code were still reporting.

### 6.2 Budgets

`evaluation/README.md` now states correctness, latency, and cost budgets *with
the v003 run scored against each*, and `test_published_benchmark.py` checks the
thresholds against the results file rather than trusting the prose.

The asymmetry is deliberate and documented: route accuracy may be wrong 10% of
the time, because several cases have more than one defensible route. Grounding
may be wrong **never**, because a confident fabrication about a building is the
one failure this system exists to prevent.

Latency is the number that looks bad and is not dressed up. A 24.6 s median is
far too slow for interactive use and the docs say so; execution is 0.4 s of it,
so the lever is the model roster and manifest size, not the database.

### 6.3 A diagnostic that could only ever be empty

`GET /dev/binding` returned `dropped_modifiers`, read from
`BindingValidation.silently_dropped_modifiers`. Task 25 moved that contract to
the constraint ledger and `validate_binding` stopped populating the field — so
the endpoint reported an empty list on every request, which reads as "nothing was
dropped" rather than "this is no longer measured here".

Removed, along with the 320 lines of retired machinery behind it
(`_validate_modifier_coverage`, `_validate_question_coverage`,
`_qualifying_unaccounted_tokens`, `_unaccounted_tokens`, `_span_is_covered`,
`_UNREMARKABLE_TOKENS`). `validate.py` went from 883 to 587 lines with no
behaviour change — every one of its 32 tests still passes, because none of that
code had run since Task 25.

### 6.4 Frontend overhead

- **`EvidenceDisclosure.tsx` removed.** Rendered by nothing since the Query
  Explanation card replaced it, but still compiled into the bundle and kept
  alive by its own unit tests. It is also what the stale e2e selector fixed in
  Task 32 was pointing at.
- **Vendor chunk split.** The production bundle was one 6,370 kB file, so
  changing a button invalidated every cached byte. Split into app (**320 kB**),
  `three` (607 kB), and `bim` (5,431 kB).

  This is a caching improvement, **not** a size reduction, and the config says
  so: the viewer is on the first screen, so a cold load still fetches
  everything. Genuinely deferring the engine means lazy-loading the viewer,
  which changes startup behaviour and was not attempted without a way to verify
  it beyond the critical-path suite.

### 6.5 Validation

| Check | Result |
| --- | --- |
| Backend offline | **827 passed, 239 deselected** (5 new) |
| Backend `-m live` | **235 passed, 4 skipped** |
| Backend ruff check / format | clean |
| Frontend unit | **476 passed** (2 removed with the dead component) |
| Frontend typecheck / lint / build | clean / clean / built |
| Playwright critical path | **3 passed** |

No benchmark documentation was updated from anything but the recorded results
file. No live comparison was run; that remains an owner-run step.

---

## 7. Self-hosted release package (Task 38)

### 7.1 A profile, not a second stack

`compose.prod.yaml` is an overlay applied on top of `compose.yaml`:

```bash
docker compose -f compose.yaml -f compose.prod.yaml up -d --build
```

It introduces **no new services** — a test asserts that — because a parallel
production stack drifts from the one people actually run. It changes five things:

| | Default | Production |
| --- | --- | --- |
| Database credentials | Local dev default | `${VAR:?}` — startup fails without them |
| Restart policy | `unless-stopped` | `always` |
| Root filesystem | Writable | Read-only, tmpfs for `/tmp` and logs |
| Capabilities / privileges | Default | `cap_drop: ALL`, `no-new-privileges` |
| Memory / CPU | Unbounded | Bounded per service |
| Dev endpoints and tracing | Off by default | Explicitly off |

The mandatory-credentials change is the one that matters most: a `:-` default
would mean a production database could come up on a password published in a
public Git repository.

### 7.2 The boundary, stated

`docs/self-hosting.md` is provider-neutral and draws the line the review's
"nothing runs" criticism invites people to blur:

> **There is no hosted demo, and this is a decision rather than an omission.**
> A public endpoint answering BIM questions would spend the author's OpenAI
> tokens on every visitor's query, with no cap that survives contact with a
> crawler. The alternative — asking visitors to paste their own key into a web
> page — trains people to hand API keys to strangers' websites.

The repository is evidence (source, specs, benchmark, screenshots); a running
instance is the reader's own, with their key and their models.

The document also says plainly that BIMtrieval has **no authentication** and
must not be published on `0.0.0.0`, since `POST /api/query` costs money to call,
and points at a reverse proxy or a private network instead.

### 7.3 Data locality

- Database: the `pgdata` volume on the host, never in an image.
- IFC files: `ifc/`, git-ignored, mounted **read-only** into the import
  container — which therefore cannot modify a source model.
- Generated artifacts and model weights: host volumes.

Nothing but the question text and the retrieved evidence leaves the machine, and
only to OpenAI, called by the backend. Idle cost is zero; startup, the viewer,
floor plans, and evidence browsing make no model calls at all.

### 7.4 The policy is tested, not just written

`backend/tests/test_deployment_policy.py` (14 tests, offline) checks every claim
a reader would otherwise have to take on trust:

- no file under `frontend/src` mentions `OPENAI_API_KEY` or `openai.com`;
- only the `backend` service receives the key, and a missing key is a `:-`
  default rather than a startup failure;
- `.dockerignore` excludes `.env`, `ifc/`, and `*.ifc`, and no Dockerfile
  `COPY`s either;
- no committed deployment file contains a credential-shaped string;
- production credentials use `:?` and not `:-`;
- both application containers are read-only with all capabilities dropped;
- nothing is published beyond `127.0.0.1`, and the database is not published;
- the IFC mount is `:ro`;
- the overlay adds no service the base stack lacks.

A security posture that lives only in prose drifts silently, and the drift is
found by whoever gets hurt by it.

`pyyaml` was declared as an explicit dev dependency for these tests rather than
relied on transitively through `uvicorn[standard]` — the same trap `numpy` was
in before Task 33.

### 7.5 Validation

- Backend offline gate: **841 passed, 239 deselected** (14 new). Ruff clean,
  `poetry check --lock` passes.
- `compose.prod.yaml` parses; the overlay's services, hardening flags, and
  credential requirements were asserted programmatically.
- Only placeholder values derived from `.env.example` were used. The user's
  `.env` was not read.
- **Runtime validation is still outstanding**, for the same reason as Task 35:
  Docker is not installed on this machine. The commands are documented and
  unrun.

---

## 8. Documentation hygiene (Task 39)

### 8.1 One canonical agent instruction file

The review named this directly: parallel `CLAUDE.md` and `CODEX.md` "will
diverge. One canonical file, referenced by both tools, is the maintainable
pattern."

`AGENTS.md` is now that file — the cross-tool convention, and what Codex reads
natively. `CLAUDE.md` is four lines importing it (`@AGENTS.md`), so there is
literally no second copy to drift. `CODEX.md` is deleted.

Its content was not merely moved. `CODEX.md` was written in the first person as
one side of a conversation ("my current development workflow is mainly with
claude… you are the upper level manager"), and pointed at the repository's former
`BIM_RAG` path. The durable rules in it — the task/spec naming convention, the
`_done` ledger, the "push back with reasons" instruction — are preserved in
`AGENTS.md` as project rules. The conversational framing and the stale paths are
not.

### 8.2 Removed

| File | Why |
| --- | --- |
| `CODEX.md` | Conversational, first-person, stale paths, duplicated `CLAUDE.md` |
| `PROJECT_CONTEXT.md` | 419 lines of pre-project planning ending at "Decide the final narrower BIM project direction" — a milestone this project passed long ago. It describes an intent the finished system contradicts |
| `workflow.md` | Duplicated the README and had drifted: it documented `bim-pipeline` (broken and now removed) and notebooks (`01_structured_import.ipynb`, `02_vectorize.ipynb`) that do not exist |
| `Start BIM RAG.lnk` | Removed in Task 35 |
| `scripts/create-shortcut.ps1` | Generated the above |

Four root Markdown files remain: `README.md`, `AGENTS.md`, `CLAUDE.md`, and the
untracked `update_plan.md` working document.

### 8.3 Preserved

`specs/` (the eleven blueprints plus this one) and the `tasks/*_done.md` ledger
are kept in full. They are the visible, disciplined-engineering evidence the
review singles out as a differentiator — "legible design documents in their own
right… they'd survive a design review with the AI removed."

The three `docs/architecture_v00*.md` files are kept too: each is cited by a spec
or by production code (`app/query/rag/thresholds.py` points at v004's
precision/recall calibration table), so they carry evidence, not just history.
Their headers now point at `README.md` instead of the deleted `workflow.md`.

`docs/evaluation_v001_report.md` was relabelled as historical in Task 36 rather
than deleted, because its record of six defects found and fixed during a live run
is worth more than the superseded numbers around it.

### 8.4 Stale references

A link checker over all 70 tracked Markdown files reports **no broken relative
links**. Remaining mentions of removed things are all explanatory — the README
note saying why the `.lnk` is gone, and `spec_v001`'s note that `ifc_original/`
became `ifc/`. Fixed in `spec_v001`: the directory listing, the reference-model
path, and the entry-point table, which still named `bim-pipeline`.

Git history was not rewritten — that is Task 41's manual owner action.

---

## 9. Portfolio README (Task 40)

### 9.1 It leads with the problem, not the stack

The README opened with "LLM-integrated BIM information access and visualization"
— accurate, and it tells a reader nothing about why the project exists. It now
opens with **"Ask a building model a question, and see the answer in 3D"**,
then the problem: a finished IFC model holds hundreds of thousands of entities,
and answering "how many fire-rated doors are on level 3?" is a specialist task in
Revit or Solibri.

Then the argument the whole architecture rests on, as a table — BIM questions are
relational *and* graph-shaped *and* semantic, so vector search cannot count and
SQL cannot infer meaning. That is why there is a router at all, and it is what
separates this from the saturated "embed the docs, call the LLM" category.

The title is `# BIMtrieval`, not the stale `# BIM_RAG`.

### 9.2 Architecture, in one diagram and five sentences

An ASCII diagram of the three applications with PostgreSQL as the sole boundary,
followed by the request path — constraint ledger → binding → deterministic
validation → execution → grounded expression — and then the refusal example:

> Asked "how many parking spaces are there?" against a model whose `IfcSpace`
> entities are not parking, the pipeline does **not** answer with every space in
> the building.

That behaviour is the most interesting thing the system does, and it was
previously not mentioned in the README at all.

### 9.3 Honesty section

`## What this is and is not` states, in the README rather than buried in a
linked document, that it is **not** fast (~25 s median, essentially all model
reasoning), **not** multi-user (no auth — do not expose it), **not** benchmarked
against a baseline, **not** broadly validated (one model, no quantity sets),
**not** geometry-aware, and **not** a design authoring tool. Plus cost
expectations and the security boundary.

### 9.4 Screenshots — deferred to the owner, with no broken placeholder

The owner is capturing these. The README's image block sits inside an HTML
comment, so nothing renders as a broken-image icon in the meantime, and
publishing them is a two-step operation: drop the files in `docs/images/`, delete
two comment markers.

`docs/images/README.md` specifies the six shots, what each must show, why it
earns its place, capture size and format, redaction checks, and — usefully —
which are free: loading a model, orbiting, switching floors, and selection make
**no** OpenAI calls, so only the chat answer and explanation panel cost anything.

A 60-second demo is described as optional with a suggested arc, ending on the
refusal, and with the instruction not to add a link until it resolves.

### 9.5 The check is now a test, not a script

`backend/tests/test_documentation_links.py` (8 tests, offline) runs in the
default gate:

- every relative link in every tracked Markdown file resolves;
- no document names something this session removed, except lines that explain
  the removal;
- the README references no image that does not exist;
- the screenshot checklist exists;
- the README still starts with `# BIMtrieval`;
- the README alone contains every command needed to run the app — quick start,
  `.env`, database setup, import, manual setup, shutdown — so the linked docs
  are depth, not a scavenger hunt;
- the README documents no upload path;
- the README states its limitations.

HTML comments are blanked rather than deleted so reported line numbers still
match the file a reader opens. External URLs are deliberately not fetched: a
gate that depends on someone else's uptime fails for reasons unrelated to this
repository.

### 9.6 Validation

- Backend offline gate: **849 passed, 239 deselected** (8 new). Ruff clean.
- No broken relative links across 70 Markdown files.
- Screenshots and any demo recording remain **outstanding, by the owner's
  choice**. Until the files land, the README is complete but image-free.

---

## 10. Final audit and release preparation (Task 41)

### 10.1 Audit against `update_plan.md`

| Finding | Prescribed fix | State |
| --- | --- | --- |
| "Nothing runs" — no Dockerfile, no compose, no migrations, no seed script | `docker compose up` works | Compose stack + production overlay written; migrations and `bim-db-init` done. **Runtime unvalidated** — see 10.4 |
| Windows-only `.lnk` as the documented entry point | Delete it, replace with a Makefile or compose file | Done. `.lnk` and its generator deleted, Compose documented as the entry point |
| No `.env.example` | Add one | Done, with the read-only-role boundary explained |
| No CI on anything that matters | GitHub Actions running pytest + ruff | Done — 4 jobs, plus the Playwright critical path |
| Parallel `CLAUDE.md` / `CODEX.md` that will drift | Consolidate into one | Done. `AGENTS.md` canonical; `CLAUDE.md` is a 4-line import |
| No stated evaluation numbers | Publish accuracy per query type, SQL vs RAG vs hybrid | Done — `evaluation/`, headline in the README, traceability enforced by tests |
| No screenshots, GIFs, or demo video | Add them | **Outstanding** — owner is capturing them; checklist and comment-block ready |
| "Tests that execute only when the author remembers are documentation, not a safety net" | Gate them | Done — CI gate, and the red baseline resolved (27 backend failures → 0) |
| Evaluation harnesses, cost/latency budgets, retries, failure modes, observability, prompt-versioning | Fill the production half | Audited; most existed. Budgets added and test-enforced; three dead reporting paths removed |
| 19 opaque commits; coarse commit hygiene | — | **Not addressed.** Out of scope for repository work; see 10.5 |
| No evidence of collaborative development; land two upstream PRs | — | **Not addressed.** Cannot be manufactured from this repository |

### 10.2 Final gates

| Check | Result |
| --- | --- |
| Ingestion offline `pytest` | **296 passed** |
| Ingestion `ruff check` / `format --check` | clean / 73 files |
| Ingestion `pytest tests_live` | **76 passed, 6 skipped** |
| Backend offline `pytest` | **849 passed, 239 deselected** |
| Backend `ruff check` / `format --check` | clean / 199 files |
| Backend `pytest -m live` | **235 passed, 4 skipped** |
| Frontend `npm test` | **476 passed** |
| Frontend typecheck / lint / build | clean / clean / built |
| Playwright critical path | **3 passed** |
| `poetry check --lock` | passes |

Starting point for comparison: 27 backend failures, 1 frontend failure, 3
Playwright failures, 17 live failures.

### 10.3 Secret and hygiene checks

- `.env` is not tracked, and never was read during this session.
- The only tracked `.ifc` is the 1.6 KB `frontend/tests/fixtures/smoke-wall.ifc`.
- Largest tracked file: the 1.2 MB generated IFC ontology vectors — a genuine
  runtime artifact.
- A credential-pattern scan over tracked files returns hits only inside
  `test_logging_redaction.py` and `test_settings.py`, which exist to assert that
  such strings are redacted.
- Generated artifacts (`frontend/dist/`, `*.tsbuildinfo`, `playwright-report/`,
  `test-results/`) untracked and ignored.

### 10.4 Not done, and why

1. **Compose has never been run.** Docker is not installed on the development
   machine — verified absent from PATH, Program Files, the registry, running
   processes, and WSL. The stack is written and statically validated, and
   building it surfaced two real defects, but `docker compose up --build` has
   not executed. It is recorded as owner-verified-pending rather than claimed to
   work.
2. **No screenshots or demo video.** The owner elected to capture these.
3. **Git history still contains the 63 MB IFC.** Untracking it does not shrink a
   clone; that needs a history rewrite and a force-push.

### 10.5 Maintenance files added — and deliberately not added

`CHANGELOG.md` and `SECURITY.md` were added because both carry information a
reader cannot get elsewhere: what changed in this release and why, and the fact
that this tool has no authentication and must not be exposed.

`CONTRIBUTING.md` and `CODE_OF_CONDUCT.md` were **not** added. The review names
the combination of `CONDUCT.md` + `CONTRIBUTING.md` + ReadTheDocs config as "the
exact fingerprint of a packaging-course cookiecutter". Adding contribution
guidance to a solo repository with no contributors would reproduce that signal
while conveying nothing.

### 10.6 Manual owner actions

Repository work is complete. These are GitHub-side or require a force-push:

**Before tagging**

1. Capture the six screenshots into `docs/images/`, then delete the two
   `<!-- SCREENSHOTS ... -->` markers in `README.md`. Optionally record the
   60-second demo and link it.
2. Validate the container stack once Docker is installed:
   ```bash
   docker compose up --build
   docker compose run --rm import "IFC Schependomlaan incl planningsdata.ifc"
   docker compose down && docker compose up      # persistence
   docker compose down -v                        # clean teardown
   ```
   Correct anything it surfaces before tagging.
3. Optional, recommended: purge the 63 MB IFC from history and force-push.
   ```bash
   git filter-repo --path "ingestion/ifc_original/IFC Schependomlaan incl planningsdata.ifc" --invert-paths
   ```
   Until this runs, a clone is ~342 MB.

**Release**

4. Commit in coherent slices rather than one batch — the review specifically
   criticises opaque changesets. Suggested: test contract → CI → config/DB/IFC →
   containers → evaluation → hardening → docs/README.
5. Push, open a PR, confirm all four CI jobs pass.
6. Tag `v0.1.0` and publish a release using the `CHANGELOG.md` 0.1.0 section.

**Repository settings**

7. Description: *"Ask a building model a question, and see the answer in 3D.
   IFC → PostgreSQL + pgvector, hybrid SQL/graph/RAG retrieval, React/Three.js
   viewer."*
8. Topics: `bim`, `ifc`, `aec`, `rag`, `pgvector`, `postgresql`, `fastapi`,
   `threejs`, `llm`, `digital-twin`, `ifcopenshell`, `retrieval-augmented-generation`.
9. Branch protection on `main`: require the `Ingestion`, `Backend`, `Frontend`,
   and `Critical path` checks.
10. Pin the repository on the GitHub profile, and use the hero screenshot as the
    social preview image.

### 10.7 What this session did not fix

Two of the review's findings are not repository problems and remain open:
**commit hygiene** (19 opaque batches; this session's work should not become a
twentieth) and **no evidence of collaboration** — no PRs, no code review, no
upstream contributions. The review's Action 8, landing two upstream PRs to
IfcOpenShell or a comparable library, is the only realistic way to close the
second, and no amount of work inside this repository substitutes for it.

Grading is not asserted here. The evidence is recorded above; a reader can weigh
it.
