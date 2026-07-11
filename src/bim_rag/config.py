"""Runtime configuration: secure db_url loading and credential sanitization."""

from __future__ import annotations

import os
import re
from pathlib import Path

from dotenv import load_dotenv

# Must run before torch/tokenizers spin up thread pools, so a sustained
# tokenization + GPU-inference workload can't saturate every logical core
# at once (CLOCK_WATCHDOG_TIMEOUT recovery mitigation, see tasks/task03.md).
os.environ.setdefault("OMP_NUM_THREADS", "4")
os.environ.setdefault("MKL_NUM_THREADS", "4")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

_REPO_ROOT = Path(__file__).resolve().parents[2]
_ENV_FILE = _REPO_ROOT / ".env"

THREAD_LIMIT = 4
# Batch-size-4 staged smoke tests (task03.md) and a subsequent chunk of the
# production run both completed without failure, so batch size 8 — the
# explicitly permitted ceiling — is now in use per user instruction.
CUDA_BATCH_SIZE = 8
MAX_CUDA_BATCH_SIZE = 8

_URL_CRED_RE = re.compile(
    r"(postgresql(?:\+\w+)?://)([^:@/]+:[^@]+@)",
    re.IGNORECASE,
)


def get_db_url() -> str:
    """Load db_url from .env without displaying it. Raises if missing."""
    load_dotenv(_ENV_FILE, override=False)
    url = os.environ.get("db_url") or os.environ.get("DB_URL")
    if not url:
        raise RuntimeError(
            "db_url not found in .env. "
            "Add `db_url=postgresql://...` to the .env file at the repository root."
        )
    return url


def sanitize_db_error(msg: str) -> str:
    """Remove credentials from error messages before logging or reporting."""
    return _URL_CRED_RE.sub(r"\1<credentials>@", msg)


def validate_batch_size(n: int) -> int:
    """Reject the batch-size-64 path that preceded the 0x101 crashes.

    Permits 1-8 only.
    """
    if n < 1 or n > MAX_CUDA_BATCH_SIZE:
        raise ValueError(
            f"CUDA batch size {n} is outside the permitted recovery range "
            f"[1, {MAX_CUDA_BATCH_SIZE}]. Batch size 64 is prohibited."
        )
    return n


IFC_SOURCE_PATH = _REPO_ROOT / "ifc_original" / "IFC Schependomlaan incl planningsdata.ifc"
