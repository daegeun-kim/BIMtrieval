# Ingestion compatibility boundary

`src/bim_rag/` (repo root) is the working, tested IFC → PostgreSQL/pgvector
pipeline delivered by `specs/spec_v001_ifc_to_db.md` (Tasks 01–03). It is not
moved, rewritten, or duplicated as part of the query-architecture work
(`specs/spec_v002_query_architecture.md` / Task 04).

The modules in this directory (`entities.py`, `relationships.py`,
`embeddings.py`) are thin re-export shims, not new implementations. They let
query-path code (and any future backend code) depend on a stable
`backend/src/ingestion/*` surface without importing `bim_rag.*` paths
directly, and without any working ingestion behavior changing location.

`embeddings.py` re-exports lazily (a function, not a module-level import)
because `bim_rag.stage2_embed` imports `torch`/`sentence-transformers` at
module scope; `pipeline_structured.ifc_to_db()` already defers that import
for the same reason, and this shim preserves that property.

## Intended future migration path

A dedicated refactoring task, protected by the existing ingestion regression
suite (`tests/test_*.py`, 158 tests as of Task 03), may eventually:

1. Move `src/bim_rag/{ifc_parser,rel_parser,stage2_embed,...}.py` into
   `backend/src/ingestion/` for real (not as shims).
2. Update `src/bim_rag/pipeline_structured.py` and the `bim-stage1`/
   `bim-stage2`/`bim-pipeline` console scripts to the new location.
3. Remove these shim modules once nothing imports the old `bim_rag.*` paths.

Until that task runs, `bim_rag.*` remains the source of truth and these
shims are the only sanctioned way for `backend/src/*` to reach it.
