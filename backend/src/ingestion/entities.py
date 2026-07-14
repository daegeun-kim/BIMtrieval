"""Re-export of the existing entity-extraction implementation.

Canonical implementation: src/bim_rag/ifc_parser.py. Do not duplicate logic
here — extend the original module and this shim will stay in sync.
"""

from __future__ import annotations

from bim_rag.ifc_parser import (
    EXTRACTION_VERSION,
    extract_canonical_json,
    file_fingerprint,
    scan_model,
)

__all__ = [
    "EXTRACTION_VERSION",
    "extract_canonical_json",
    "file_fingerprint",
    "scan_model",
]
