"""Re-export of the existing relationship-extraction implementation.

Canonical implementation: src/bim_rag/rel_parser.py. Do not duplicate logic
here — extend the original module and this shim will stay in sync.
"""

from __future__ import annotations

from bim_rag.rel_parser import (
    extract_member_rows,
    extract_relationship_canonical_json,
    resolve_members,
)

__all__ = [
    "extract_member_rows",
    "extract_relationship_canonical_json",
    "resolve_members",
]
