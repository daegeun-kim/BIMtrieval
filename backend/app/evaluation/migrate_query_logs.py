"""Idempotent migration of the v3 query/failure logs into the one permanent
query trace (task26 §14.8).

Reads `backend/logs/query_events.jsonl` and `backend/logs/failure_cases.jsonl`,
merges records by request id when possible, and appends deduplicated legacy
records to the single Git-tracked `backend/app/evaluation/query_trace.jsonl`.
Every migrated record is marked `experiment2_v3`, `legacy_import: true`, and
declares its missing fields. Nothing the old logs did not capture is fabricated.

Run from `backend/`:
    python -m app.evaluation.migrate_query_logs
"""

from __future__ import annotations

from pathlib import Path

from app.config.settings import get_settings
from app.query.trace_v2 import QUERY_TRACE_PATH, migrate_legacy_logs


def main() -> None:
    settings = get_settings()
    query_events = Path(settings.query_log_path)
    failure_cases = Path(settings.failure_case_path)
    stats = migrate_legacy_logs(query_events, failure_cases, QUERY_TRACE_PATH)
    print(
        f"[migrate_query_logs] migrated={stats['migrated']} skipped={stats['skipped']} "
        f"-> {QUERY_TRACE_PATH}"
    )


if __name__ == "__main__":
    main()
