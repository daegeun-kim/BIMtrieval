"""Standard logging setup + safe JSONL query/evaluation logging.

spec_v002 Section 21 requires structured per-query logs (plan, route,
retrieved IDs, latency, token usage, ...) without ever logging secrets or
unrestricted canonical JSON. `redact_secrets` is the single choke point used
before anything is written to a JSONL log file or emitted via `logging`.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config.database import sanitize_db_error

# Match auth-credential key names only. NOT the bare substring "token" — that
# over-redacts legitimate token-usage metrics (`token_usage`, `total_tokens`,
# `prompt_tokens`), which spec_v005 §16 explicitly requires logging. Real bearer/
# access/refresh tokens are still caught by their specific forms below, and any
# `sk-...` value is caught by `_OPENAI_KEY_PATTERN` regardless of key name.
_SECRET_KEY_PATTERN = re.compile(
    r"(api[_-]?key|secret|password|authorization|bearer|"
    r"access[_-]?token|auth[_-]?token|refresh[_-]?token|db_url|database_url)",
    re.IGNORECASE,
)
_OPENAI_KEY_PATTERN = re.compile(r"sk-[A-Za-z0-9_-]{16,}")
_REDACTED = "***REDACTED***"


def redact_secrets(value: Any) -> Any:
    """Recursively redact secret-shaped keys/values from a log record.

    Redacts by key name (case-insensitive match against `_SECRET_KEY_PATTERN`),
    by value pattern (OpenAI-style `sk-...` keys), and by delegating to
    the backend-owned `app.config.database.sanitize_db_error` for embedded
    database credentials.
    Safe to call on arbitrary JSON-like structures (dict/list/str/scalars).
    """
    if isinstance(value, dict):
        return {
            k: (_REDACTED if _SECRET_KEY_PATTERN.search(str(k)) else redact_secrets(v))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [redact_secrets(v) for v in value]
    if isinstance(value, str):
        value = sanitize_db_error(value)
        value = _OPENAI_KEY_PATTERN.sub(_REDACTED, value)
        return value
    return value


def write_jsonl_event(record: dict[str, Any], path: Path) -> None:
    """Append one redacted JSON record as a line to `path`.

    Creates parent directories if needed. Adds `logged_at` if absent.
    """
    safe_record = redact_secrets(record)
    safe_record.setdefault("logged_at", datetime.now(timezone.utc).isoformat())
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(safe_record, default=str) + "\n")


def configure_logging(level: int = logging.INFO) -> logging.Logger:
    """Configure a basic console logger for backend/src.* modules."""
    logger = logging.getLogger("bim_rag_backend")
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        logger.addHandler(handler)
    logger.setLevel(level)
    return logger
