# Changelog

Notable changes to BIMtrieval. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versions follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] — 2026-08-06

First public release. The query pipeline, viewer, and evaluation existed before
this; what this release adds is everything needed for someone other than the
author to run it.

### Added

- **Docker Compose environment.** `docker compose up --build` starts PostgreSQL
  with pgvector, schema setup, the read-only backend, and the viewer. A
  production overlay (`compose.prod.yaml`) adds mandatory credentials, read-only
  root filesystems, dropped capabilities, and bounded resources.
- **Continuous integration.** GitHub Actions runs the offline gate for all three
  projects plus the Playwright critical path on every pull request and push to
  `main`. Secret-free: no `.env`, no API key, no database, no model download.
- **`.env.example`** documenting the three configuration names and, more
  usefully, the boundary between the ingestion write connection and the
  backend's dedicated read-only role.
- **`bim-db-init`** — one idempotent command for extension, schema, migrations,
  catalog seed, and optional read-only-role bootstrap, with a real
  `schema_migrations` ledger that refuses a migration edited after it was
  applied.
- **`bim-import <path>`** — one command for the complete import workflow,
  accepting a path or a filename in the new root-level `ifc/` folder.
- **Published benchmark** under `evaluation/`: versioned cases, machine-readable
  results, a report with full provenance, and stated correctness/latency/cost
  budgets. 26/27 cases, 0 grounding failures.
- **`docs/self-hosting.md`** — provider-neutral self-host procedure, security
  posture, backup, and cost expectations.
- **`AGENTS.md`** as the single canonical instruction file for AI assistants.

### Fixed

- **Semantic search silently returned nothing.** `rag_documents` carries one
  global HNSW index over 261,943 rows while every RAG query filters to ~2.7% of
  it. With pgvector's `hnsw.iterative_scan` off, the index scan collected
  neighbours globally and only then applied the filter, so a filtered search
  returned **zero** candidates at `top_k < 10` against 6,989 matching documents —
  which reads downstream as "the model contains no such objects". Measured
  recall went from 0/3 to 3/3.
- **The ingestion wheel shipped no SQL.** No package-data declaration, so a
  non-editable install contained zero `.sql` files and `bim-db-init` would have
  reported "none pending" against a database with no schema. Invisible locally,
  because the editable install points at the source tree.
- **`numpy` was an undeclared dependency**, present only transitively through
  torch. A backend install without torch could not collect its own test suite.
- **`bim-pipeline` had been a broken entry point**, importing `run_stage1` and
  `run_stage2` after both were removed. Deleted; `bim-import` replaces it.
- **`/dev/binding` reported a diagnostic that could only ever be empty.**
  `silently_dropped_modifiers` stopped being populated when Task 25 moved that
  contract to the constraint ledger, so an empty list read as "nothing was
  dropped" rather than "not measured here".
- 27 failing backend tests, 1 frontend test, and the Playwright critical path,
  all resolved rather than tolerated.

### Changed

- Torch and sentence-transformers moved to an optional `embedding` Poetry group.
  A multi-gigabyte CUDA wheel no longer gates a test run, and containers install
  the CPU build instead. Without the group the backend still starts and answers
  SQL and graph questions; the RAG path reports its degraded mode.
- Database-backed, browser, and live suites are separately named and cannot
  enter the default gate: `pytest -m live` (backend), `pytest tests_live`
  (ingestion), `npx playwright test` (frontend).
- Frontend bundle split into app (320 kB), `three`, and `bim` chunks, so a UI
  change no longer invalidates 6.4 MB of cached vendor code.
- IFC models live in `ifc/` at the repository root instead of
  `ingestion/ifc_original/`.

### Removed

- **`Start BIM RAG.lnk`** — a Windows shortcut binary, committed to Git, storing
  an absolute path, documented as the way to start the system.
- **A 63 MB IFC model** from version control. It remains in Git history; see the
  release checklist.
- `CODEX.md` and `PROJECT_CONTEXT.md`, consolidated into `AGENTS.md`;
  `workflow.md`, consolidated into `README.md`.
- 320 lines of retired binding-validation machinery that nothing had called
  since Task 25, and a dead `EvidenceDisclosure` frontend component.

### Known limitations

- ~25 s median per question, essentially all model reasoning. Not yet
  interactive.
- No authentication. Single-user local tool; do not expose it.
- The benchmark has no vector-only or SQL-only baseline arm, so it shows the
  pipeline works, not that hybrid retrieval beats a simpler approach.
- One IFC2X3 model with no quantity sets in the published run.

[Unreleased]: https://github.com/daegeun-kim/BIMtrieval/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/daegeun-kim/BIMtrieval/releases/tag/v0.1.0
