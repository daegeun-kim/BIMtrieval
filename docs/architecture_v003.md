# BIM RAG v003 SQL/Graph Query Path: Commands and Documentation

Governed by `specs/spec_v003_sql_query_path.md` (Task 05). Implements the
complete deterministic catalog, SQL, and relational IFC-graph query service
on top of the Task 04 architecture scaffold. Validated by supplying typed
plans directly — no OpenAI planner is involved (that's v005 scope).

## Environment

No new dependencies. Uses the same `bim_rag` conda env / `pip install -e ".[query]"`
extra as Task 04 (`docs/architecture_v002.md`).

## One-time database setup (already executed for this project)

```bash
# from the repo root, with backend/src and src on PYTHONPATH
python -m db.apply_catalog_migration     # additive: model_families, source_model_catalog_entries
python -m db.bootstrap_readonly_role     # creates bim_rag_query_ro, writes DATABASE_URL to .env
```

Both scripts are idempotent — safe to re-run. `apply_catalog_migration`
snapshots the five existing tables' row counts before and after and raises
if they differ. `bootstrap_readonly_role` requires `CREATEROLE` on the
connection in `.env`'s `db_url` (this project's connection is already a
PostgreSQL superuser, so no separate admin action was needed); it generates
a random password with `secrets.token_urlsafe(32)`, writes only the
resulting `DATABASE_URL=...` DSN into `.env` (never printed/logged), and
verifies the new role can `SELECT` but not `INSERT`/`CREATE`.

All `query.sql.*`/`query.graph.*` code and every live test in
`backend/tests/query_live/` runs through `db.session.get_engine()`, which
prefers `DATABASE_URL` — i.e. everything here actually executes as the
read-only role, not the ingestion superuser connection.

## Package layout

```text
backend/src/query/sql/
├── schemas.py        17 typed per-operation plans (spec_v003 §6), bounded FilterCondition/
│                      FilterGroup expression tree (max depth 3, max 20 conditions)
├── operations.py      SqlOperation -> plan-model registry, MissingValueState vocabulary
├── field_registry.py  per-source-model sanitized schema catalog + resolve_field/resolve_concept
├── compiler.py         sole SQLAlchemy Core query builder — bound parameters only
├── catalog.py           list/filter/rank models, model versions, model metadata
├── entities.py           count/list/get/filter/aggregate/group/find_missing_values/get_selected
├── relationships.py       list/get relationships, get_relationship_members
├── aggregates.py           coverage-aware count/sum/min/max/average/group_by
├── hydration.py             rows -> Task04 evidence shapes (PrimaryEntityResult/...)
└── errors.py                 FieldNotFoundError, AmbiguousFieldError, CrossModelAccessError, ...

backend/src/query/graph/
├── schemas.py         TraversalHop/TraversalResult
├── registry.py          IFC relationship class -> semantic role + exact schema role names
├── traversal.py           bounded BFS (depth 1-3), cycle prevention, source_model_id isolation
└── hydration.py            traversal -> primary/context entities + ViewerActions

backend/src/db/
├── apply_catalog_migration.py   one-off: creates the 2 new tables, seeds catalog metadata
└── bootstrap_readonly_role.py   one-off: creates/verifies bim_rag_query_ro

backend/tests/
├── query_sql/    schema + pure-function unit tests (no DB)
├── query_graph/  registry structure tests (no DB)
└── query_live/   102 live, read-only tests against the real database (skip cleanly if unreachable)
```

## A note on this project's actual data

The only ingested model (Schependomlaan, `source_model_id=1`, IFC2X3,
6,989 entities / 3,473 relationships) is real, messy ArchiCAD export data:

- **`quantity_sets` is empty and `materials` is `[]` on all 6,989 entities.**
  There is no `BaseQuantities`/`Pset_XxxCommon` structure to query.
- **`property_sets` has exactly one bucket, `SynchroResourceProperty`**,
  containing thousands of raw `[SourcePset]PropName` string keys (Dutch
  text), not clean per-Pset objects.
- Only 6 relationship classes have rows: `IfcRelDefinesByProperties`(3228),
  `IfcRelAssignsTasks`(125), `IfcRelAssignsToProcess`(73),
  `IfcRelSequence`(42), `IfcRelAggregates`(4),
  `IfcRelContainedInSpatialStructure`(1) — the last one alone contains
  *all* 3,505 spatially-contained elements via a single relationship
  instance, which is why depth-3 "both direction" traversal from any
  element fans out to thousands of context entities (a real property of
  this model's graph, not a traversal bug — see
  `test_graph_traversal.py::test_depth_bound_is_respected`).
- `bim_rag.ifc_parser._extract_qsets` only computes a **linear** project-length
  unit factor (`normalized_unit="m"`); it is not area/volume/angle-aware.
  `field_registry.normalize_quantity_value()` therefore only supports `"mm"`
  conversion — `"mm2"`/`"mm3"`/`"degrees"` correctly report *not available*
  rather than silently squaring/cubing a linear factor.

The query engine itself is built generically and spec-complete (all 17
operations, all operators, the full spec-named relationship semantic
registry — including classes with zero rows here, for future models). Live
tests against this specific model correctly report the *absence* of
quantity/material data rather than fabricating it — see
`backend/src/evaluation/benchmark_v002_sql_graph_cases.jsonl` (the "average
door width" case) and `test_field_resolution.py`.

## Verification performed

- 300/300 tests pass: 158 pre-existing ingestion + 40 Task 04 + 102 new
  Task 05 tests (`backend/tests/query_sql`, `query_graph`, `query_live`).
- `ruff format` / `ruff check` clean.
- Migration verified additive: existing 5-table row counts identical
  before/after (`ifc_source_models=1, ifc_entities=6989,
  ifc_relationships=3473, relationship_members=17668, rag_documents=10462`).
- `bim_rag_query_ro` verified: `SELECT` succeeds, `INSERT`/`CREATE TABLE`
  rejected with a permission error.
- Manual spot checks against real data: `filter_entities` for `IfcDoor`
  (205, matches direct SQL), `traverse_relationships` for
  `IfcRelContainedInSpatialStructure` from the one real `IfcDoor` used in
  tests (correctly resolves to `Storey-1`).
- Benchmark: `backend/src/evaluation/benchmark_v002_sql_graph_cases.jsonl`
  (8 manually-verified cases with canonical IDs/exact counts), re-verified
  against the live engine in `test_benchmark.py`.

## Stop condition (tasks/task05.md)

```text
SQL/catalog path: IMPLEMENTED AND VALIDATED
IFC graph path: IMPLEMENTED AND VALIDATED
Existing canonical BIM IDs: PRESERVED
RAG query path: NOT IMPLEMENTED
OpenAI orchestration: NOT EXECUTED
```
