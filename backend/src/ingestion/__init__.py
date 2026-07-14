"""Compatibility boundary over the existing bim_rag ingestion pipeline.

See README.md in this directory for the intended future migration path.
Nothing here re-implements ingestion logic — these modules only re-export
the existing, working `src/bim_rag/` implementation so query-path code can
depend on a stable `backend/src/ingestion/*` import surface without the
working pipeline being moved or rewritten (tasks/task04.md item 11/12).
"""
