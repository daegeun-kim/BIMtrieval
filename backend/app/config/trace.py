"""Terminal observability: standard operational output + opt-in trace mode
(tasks/task13.md §1, amended by tasks/task15.md §1).

Two layers with different gating:

**Always on (standard operational output, task15):**

- every SQL/RAG/vector statement actually submitted to the database is printed
  once, as the exact parameterized SQL, labelled by path:

      [SQL]
      SELECT ... WHERE ifc_entities.source_model_id = %(source_model_id_1)s ...

      [RAG]
      SELECT ... ORDER BY rag_documents.embedding <=> %(embedding_1)s ...

- one bounded API status record per HTTP **400–599** response. Successful
  2xx/3xx/304 endpoint calls print nothing.

**Opt-in (`BIM_RAG_TRACE=1`, task13):** per-operation summary records with
timing, counts, and histograms. These deliberately do NOT repeat the SQL —
statements are printed exactly once by the always-on layer (task15: no
duplicate statement output).

What this module structurally cannot leak:

- **SQL parameter values.** The `after_cursor_execute` hook logs the
  `statement` text only and never reads `parameters`. Values are therefore
  never collected — which also means the pgvector query embedding (a bound
  parameter) cannot appear: the printed statement holds a placeholder.
- **Secrets.** Every record passes through the existing `redact_secrets`
  choke point (`app.config.logging`) before rendering.

Timings are always **seconds** (`elapsed_s`), never milliseconds.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections import Counter
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Iterable, Iterator, Sequence

from sqlalchemy import Engine, event

from app.config.logging import configure_logging, redact_secrets
from app.config.settings import get_settings

_TRACE_LOGGER_NAME = "bim_rag_backend.trace"
_DB_LOGGER_NAME = "bim_rag_backend.db"

# One correlation id per HTTP request; SQL/RAG sub-records nest under it.
_request_id: ContextVar[str | None] = ContextVar("bim_rag_trace_request_id", default=None)
# Which retrieval path is currently submitting statements: "SQL" unless a RAG
# search context is active. Used only to label the always-on statement output.
_db_label: ContextVar[str] = ContextVar("bim_rag_db_label", default="SQL")

_logger_ready = False


def trace_enabled() -> bool:
    """True only when BIM_RAG_TRACE is set truthy (default: off)."""
    return bool(get_settings().bim_rag_trace)


def new_request_id() -> str:
    return uuid.uuid4().hex[:12]


def get_request_id() -> str | None:
    return _request_id.get()


@contextmanager
def request_context(request_id: str) -> Iterator[str]:
    token = _request_id.set(request_id)
    try:
        yield request_id
    finally:
        _request_id.reset(token)


# ---------------------------------------------------------------------------
# Always-on statement output (task15 §1). Parameter values are never collected.
# ---------------------------------------------------------------------------


@event.listens_for(Engine, "after_cursor_execute")
def _print_submitted_statement(
    conn: Any, cursor: Any, statement: str, parameters: Any, context: Any, executemany: bool
) -> None:
    """Print each statement the moment it was actually submitted (never one that
    was merely planned), exactly once, in its parameterized multiline form.
    `parameters` is deliberately ignored — values are never read, so they cannot
    be printed or interpolated."""
    _ensure_logger(_DB_LOGGER_NAME).info("[%s]\n%s", _db_label.get(), statement.strip())


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


def histogram(values: Iterable[str | None]) -> dict[str, int]:
    """Compact count-by-label, ordered by count desc then label asc."""
    counts = Counter(v for v in values if v)
    return {k: c for k, c in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))}


def format_histogram(hist: dict[str, int]) -> str:
    """`IfcDoor: 5, IfcWindow: 3`"""
    return ", ".join(f"{k}: {v}" for k, v in hist.items()) if hist else "(none)"


@dataclass
class SqlTraceRecord:
    operation: str
    exact_count: int | None = None
    row_count: int | None = None
    result_histogram: dict[str, int] = field(default_factory=dict)
    elapsed_s: float | None = None
    notes: list[str] = field(default_factory=list)


@dataclass
class RagTraceRecord:
    semantic_query: str
    document_kinds: list[str] = field(default_factory=list)
    top_k: int | None = None
    minimum_similarity: float | None = None
    retrieved_count: int | None = None
    similarity_min: float | None = None
    similarity_max: float | None = None
    result_histogram: dict[str, int] = field(default_factory=dict)
    elapsed_s: float | None = None


# ---------------------------------------------------------------------------
# Rendering / emission
# ---------------------------------------------------------------------------


def _ensure_logger(name: str = _TRACE_LOGGER_NAME) -> logging.Logger:
    global _logger_ready
    if not _logger_ready:
        configure_logging()
        _logger_ready = True
    return logging.getLogger(name)


def _render(value: Any, indent: int = 1) -> list[str]:
    """Indented, scannable nested list — deliberately not dense one-line JSON."""
    pad = "  " * indent
    lines: list[str] = []
    if isinstance(value, dict):
        for k, v in value.items():
            if isinstance(v, (dict, list)) and v:
                lines.append(f"{pad}{k}:")
                lines.extend(_render(v, indent + 1))
            elif isinstance(v, (dict, list)):
                continue  # omit empty containers rather than printing noise
            elif v is None:
                continue
            else:
                lines.append(f"{pad}{k}: {v}")
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, (dict, list)):
                lines.extend(_render(item, indent))
            else:
                text = str(item)
                first, *rest = text.splitlines() or [""]
                lines.append(f"{pad}- {first}")
                lines.extend(f"{pad}  {line.strip()}" for line in rest)
    else:
        lines.append(f"{pad}{value}")
    return lines


def emit(kind: str, payload: dict[str, Any], *, force: bool = False) -> None:
    """Render one redacted record to the terminal.

    Gated on BIM_RAG_TRACE unless `force=True` — error/usage records are
    standard operational output (task15 §1) and print regardless of trace mode.
    Redaction applies on every path.
    """
    if not force and not trace_enabled():
        return
    safe = redact_secrets(payload)
    body = "\n".join(_render(safe))
    _ensure_logger().info("%s\n%s", kind, body)


def _base_payload() -> dict[str, Any]:
    return {"request_id": get_request_id()}


def emit_api_error_record(
    *, request_id: str, method: str, route: str, status: int, elapsed_s: float
) -> None:
    """One bounded record for an HTTP 400–599 response (task15 §1).

    Callers must only invoke this for error statuses — successful calls print
    nothing. Route *template* only, never the raw URL, so query strings that may
    carry user data are not logged. No bodies, chat history, headers,
    credentials, filesystem paths, or exception internals.
    """
    emit(
        "[API error]",
        {
            "request_id": request_id,
            "method": method,
            "route": route,
            "status": status,
            "elapsed_s": round(elapsed_s, 4),
        },
        force=True,
    )


def emit_openai_usage(*, prompt_tokens: int, completion_tokens: int, total_tokens: int) -> None:
    """One per-question OpenAI usage summary (task15 §1): the sum of every call
    made for one user question, from API-reported usage. Exactly these three
    aggregate numbers — no cumulative counter, no cost estimate."""
    emit(
        "[OpenAI usage]",
        {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
        },
        force=True,
    )


def emit_sql_record(rec: SqlTraceRecord) -> None:
    """Trace-only operation summary. The SQL itself is NOT repeated here — the
    always-on statement output already printed it once (task15 §1)."""
    payload = _base_payload()
    payload.update(
        {
            "operation": rec.operation,
            "exact_count": rec.exact_count,
            "row_count": rec.row_count,
            "result_histogram": format_histogram(rec.result_histogram)
            if rec.result_histogram
            else None,
            "elapsed_s": rec.elapsed_s,
            "notes": rec.notes,
        }
    )
    emit("[trace] sql", payload)


def emit_rag_record(rec: RagTraceRecord) -> None:
    """Trace-only retrieval summary; the vector SQL is printed by the always-on
    layer, never repeated here."""
    similarity_range = (
        f"{rec.similarity_min:.4f} - {rec.similarity_max:.4f}"
        if rec.similarity_min is not None and rec.similarity_max is not None
        else None
    )
    payload = _base_payload()
    payload.update(
        {
            "semantic_query": rec.semantic_query,
            "document_kinds": rec.document_kinds,
            "top_k": rec.top_k,
            "minimum_similarity": rec.minimum_similarity,
            "retrieved_count": rec.retrieved_count,
            "similarity_range": similarity_range,
            "result_histogram": format_histogram(rec.result_histogram)
            if rec.result_histogram
            else None,
            "elapsed_s": rec.elapsed_s,
        }
    )
    emit("[trace] rag", payload)


# ---------------------------------------------------------------------------
# Operation context managers
# ---------------------------------------------------------------------------


@contextmanager
def trace_sql_operation(operation: str) -> Iterator[SqlTraceRecord]:
    """Wrap one SQL-path operation. Callers always get a record and may set its
    fields unconditionally; the summary is emitted only when tracing is enabled.
    Statement printing is independent and always on."""
    rec = SqlTraceRecord(operation=operation)
    start = time.perf_counter()
    try:
        yield rec
    finally:
        rec.elapsed_s = round(time.perf_counter() - start, 4)
        emit_sql_record(rec)  # no-op unless BIM_RAG_TRACE=1


@contextmanager
def trace_rag_search(
    *,
    semantic_query: str,
    document_kinds: Sequence[str],
    top_k: int | None,
    minimum_similarity: float | None,
) -> Iterator[RagTraceRecord]:
    """Wrap one vector retrieval. Always active so statements submitted inside
    it are labelled [RAG] by the always-on output; the summary record itself is
    trace-gated. The embedding is a bound parameter, so the printed statement
    contains a placeholder and the vector never appears."""
    rec = RagTraceRecord(
        semantic_query=semantic_query,
        document_kinds=list(document_kinds),
        top_k=top_k,
        minimum_similarity=minimum_similarity,
    )
    start = time.perf_counter()
    label_token = _db_label.set("RAG")
    try:
        yield rec
    finally:
        _db_label.reset(label_token)
        rec.elapsed_s = round(time.perf_counter() - start, 4)
        emit_rag_record(rec)  # no-op unless BIM_RAG_TRACE=1
