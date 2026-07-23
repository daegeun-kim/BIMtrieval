"""Request-scoped trace accumulator + one permanent append-only query log
(task26 §14).

Every request submitted through the app's query endpoint appends exactly ONE
terminal JSON record to `backend/app/evaluation/query_trace.jsonl` — a
Git-tracked, append-only file. No rotation, truncation, or overwrite. The
record carries the complete bounded diagnostic flow: identity/version block,
exact input, ordered stages, exact structured LLM outputs, the delivered
envelope, highlighted GlobalIds, and per-call cost.

A serialization/write failure must never replace a successful user response:
the flush emits a stderr diagnostic and attempts a minimal terminal record
instead (§14.1). Secrets are never logged; exact query/answer content is
intentionally enabled for this local diagnostic log.
"""

from __future__ import annotations

import datetime as _dt
import json
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

TRACE_SCHEMA_VERSION = "query_trace_v001"
PIPELINE_VERSION = "experiment2_v4"

#: The one active permanent log, relative to the backend working directory.
QUERY_TRACE_PATH = Path(__file__).resolve().parents[1] / "evaluation" / "query_trace.jsonl"


def resolve_trace_path(configured: str | None = None) -> Path:
    """The active trace path — a configured override (tests) or the default."""
    return Path(configured) if configured else QUERY_TRACE_PATH

_WRITE_LOCK = threading.Lock()

#: Hard per-record byte bound; a record over this is truncated with a marker
#: rather than growing without limit (§14.7).
_MAX_RECORD_BYTES = 400_000


@lru_cache(maxsize=1)
def _git_identity() -> dict[str, Any]:
    """Process-start Git commit + dirty flag, cached (§14.3). Never fatal."""
    try:
        root = Path(__file__).resolve().parents[3]
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        ).stdout.strip()
        dirty = bool(
            subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=root,
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            ).stdout.strip()
        )
        return {"git_commit": commit or None, "git_dirty": dirty}
    except Exception:  # noqa: BLE001 - identity is best-effort
        return {"git_commit": None, "git_dirty": None}


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


_SECRET_MARKERS = ("api_key", "authorization", "password", "secret", "database_url", "db_url")


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            k: ("***" if any(m in k.lower() for m in _SECRET_MARKERS) else _redact(v))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_redact(v) for v in value[:200]]
    if isinstance(value, str) and value.startswith("sk-"):
        return "***"
    return value


@dataclass
class QueryTrace:
    """One request's accumulating trace record (§14.2).

    Created at `QueryService.handle_query` entry, before any routing, LLM, or
    database work; flushed exactly once in a `finally` boundary.
    """

    request_id: str
    session_id: str
    action: str = "question"
    started_at: str = field(default_factory=_now)
    _start: float = field(default_factory=time.perf_counter)
    record: dict[str, Any] = field(default_factory=dict)
    stages: list[dict[str, Any]] = field(default_factory=list)
    trace_path: Path | None = None
    _flushed: bool = False

    def __post_init__(self) -> None:
        self.record = {
            "trace_schema_version": TRACE_SCHEMA_VERSION,
            "pipeline_version": PIPELINE_VERSION,
            "request_id": self.request_id,
            "session_id": self.session_id,
            "action": self.action,
            "started_at": self.started_at,
            **_git_identity(),
        }

    # -- accumulation --------------------------------------------------------

    def set(self, **fields: Any) -> None:
        self.record.update(fields)

    def set_versions(self, **fields: Any) -> None:
        self.record.setdefault("versions", {}).update(fields)

    def add_stage(self, name: str, status: str = "ok", **payload: Any) -> None:
        stage: dict[str, Any] = {"name": name, "status": status}
        stage.update(_redact(payload))
        self.stages.append(stage)

    def extend_stages(self, stages: list[dict[str, Any]]) -> None:
        for stage in stages:
            self.stages.append(_redact(stage))

    def set_delivery(
        self,
        *,
        answer: str | None,
        envelope: dict[str, Any] | None,
        viewer_global_ids: list[str] | None = None,
        viewer_total: int | None = None,
        viewer_truncated: bool | None = None,
    ) -> None:
        self.record["final_answer"] = answer
        if envelope is not None:
            self.record["delivered_envelope"] = _redact(envelope)
        if viewer_global_ids is not None:
            self.record["viewer_global_ids"] = viewer_global_ids
            self.record["viewer_returned"] = len(viewer_global_ids)
        if viewer_total is not None:
            self.record["viewer_matches_total"] = viewer_total
        if viewer_truncated is not None:
            self.record["viewer_truncated"] = viewer_truncated

    def terminal(self, stage: str, status: str) -> None:
        self.record["terminal_stage"] = stage
        self.record["terminal_status"] = status

    # -- flush ---------------------------------------------------------------

    def flush(self, path: Path | None = None) -> None:
        """Append exactly one terminal record. Never raises into the caller."""
        if self._flushed:
            return
        self._flushed = True
        target = path or self.trace_path or QUERY_TRACE_PATH
        self.record["completed_at"] = _now()
        self.record["duration_ms"] = round((time.perf_counter() - self._start) * 1000.0, 1)
        self.record.setdefault("terminal_stage", "response_delivery")
        self.record.setdefault("terminal_status", "success")
        self.record["stages"] = self.stages
        try:
            _append_record(target, self.record)
        except Exception as exc:  # noqa: BLE001 - §14.1: logging never fails a response
            print(
                f"[query_trace] failed to append trace record: {type(exc).__name__}",
                file=sys.stderr,
            )
            try:
                _append_record(
                    target,
                    {
                        "trace_schema_version": TRACE_SCHEMA_VERSION,
                        "pipeline_version": PIPELINE_VERSION,
                        "request_id": self.request_id,
                        "session_id": self.session_id,
                        "started_at": self.started_at,
                        "completed_at": _now(),
                        "terminal_stage": self.record.get("terminal_stage", "trace_write"),
                        "terminal_status": "trace_serialization_failed",
                    },
                )
            except Exception:  # noqa: BLE001 - final fallback is stderr only
                pass


def _append_record(path: Path, record: dict[str, Any]) -> None:
    line = json.dumps(record, ensure_ascii=False, default=str)
    encoded = line.encode("utf-8")
    if len(encoded) > _MAX_RECORD_BYTES:
        record = dict(record)
        record["stages"] = record.get("stages", [])[:6]
        record["truncated_record"] = True
        record.pop("delivered_envelope", None)
        line = json.dumps(record, ensure_ascii=False, default=str)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _WRITE_LOCK, open(path, "a", encoding="utf-8") as handle:
        handle.write(line + "\n")


# ---------------------------------------------------------------------------
# Legacy migration (§14.8)
# ---------------------------------------------------------------------------


def migrate_legacy_logs(
    query_events_path: Path,
    failure_cases_path: Path,
    target_path: Path | None = None,
) -> dict[str, int]:
    """Idempotently import v3 logs as explicit `experiment2_v3` records.

    Records are merged by request id when both files carry one; nothing the old
    logs did not capture is fabricated — every migrated record names its
    missing fields.
    """
    target = target_path or QUERY_TRACE_PATH
    existing_ids: set[str] = set()
    if target.exists():
        with open(target, encoding="utf-8") as handle:
            for line in handle:
                try:
                    existing_ids.add(json.loads(line).get("request_id", ""))
                except json.JSONDecodeError:
                    continue

    def _load(path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        records = []
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return records

    events = _load(query_events_path)
    failures = _load(failure_cases_path)
    failures_by_id: dict[str, dict[str, Any]] = {}
    for failure in failures:
        request_id = failure.get("request_id")
        if request_id:
            failures_by_id.setdefault(request_id, failure)

    migrated = skipped = 0
    for event in events:
        request_id = event.get("request_id") or f"legacy:{migrated + skipped}"
        if request_id in existing_ids:
            skipped += 1
            continue
        failure = failures_by_id.pop(request_id, None)
        record = {
            "trace_schema_version": TRACE_SCHEMA_VERSION,
            "pipeline_version": "experiment2_v3",
            "legacy_import": True,
            "legacy_pipeline_label": event.get("pipeline", "task24_binding"),
            "request_id": request_id,
            "session_id": event.get("session_id"),
            "action": "question",
            "legacy_event": _redact(event),
            "missing_fields": [
                "ledger",
                "recommendations",
                "binder_output",
                "validation",
                "compiled_sql",
                "rag_evidence",
                "graph_evidence",
                "answer_packet",
                "raw_answer_output",
                "delivered_envelope",
                "viewer_global_ids",
            ],
            "terminal_stage": "response_delivery",
            "terminal_status": "legacy_success",
        }
        if failure is not None:
            record["legacy_failure"] = _redact(failure)
        _append_record(target, record)
        existing_ids.add(request_id)
        migrated += 1

    for request_id, failure in failures_by_id.items():
        if request_id in existing_ids:
            skipped += 1
            continue
        _append_record(
            target,
            {
                "trace_schema_version": TRACE_SCHEMA_VERSION,
                "pipeline_version": "experiment2_v3",
                "legacy_import": True,
                "legacy_pipeline_label": "task24_binding",
                "request_id": request_id,
                "session_id": failure.get("session_id"),
                "action": "question",
                "legacy_failure": _redact(failure),
                "missing_fields": [
                    "ledger",
                    "recommendations",
                    "binder_output",
                    "validation",
                    "compiled_sql",
                    "rag_evidence",
                    "graph_evidence",
                    "answer_packet",
                    "raw_answer_output",
                    "delivered_envelope",
                    "viewer_global_ids",
                ],
                "terminal_stage": failure.get("kind", "unknown"),
                "terminal_status": "legacy_failure",
            },
        )
        existing_ids.add(request_id)
        migrated += 1

    return {"migrated": migrated, "skipped": skipped}
