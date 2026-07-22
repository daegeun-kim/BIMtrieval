"""Semantic-manifest path derivation, containment, and status (task25 §2.1).

Mirrors `app/viewer/assets.py` deliberately: every artifact path is DERIVED from
database model identity (`source_model_id` + `file_fingerprint`) under a
backend-owned root. No path segment is ever taken from a request, and the
resolved server path is never returned to a client.

The four-state status is what makes a stale artifact detectable. A manifest
whose filename does not match the model's CURRENT fingerprint is `STALE`, not
`READY` — the backend must never bind a question against semantics describing a
different version of the file.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path

#: Matches the suffix the ingestion writer publishes.
MANIFEST_SUFFIX = ".semantic.json"


class ManifestStatus(str, Enum):
    """Availability of a model's semantic manifest."""

    #: An artifact exists for this model's current fingerprint.
    READY = "ready"
    #: An artifact exists for this model, but for a DIFFERENT fingerprint.
    STALE = "stale"
    #: No artifact at all.
    MISSING = "missing"
    #: The root is unreachable, escaped containment, or the model has no
    #: fingerprint to derive a path from.
    UNAVAILABLE = "unavailable"


def manifest_dir(root: Path, source_model_id: int) -> Path:
    """The per-model artifact directory: `{root}/{source_model_id}`."""
    return root / str(source_model_id)


def expected_manifest_path(root: Path, source_model_id: int, fingerprint: str) -> Path:
    """`{root}/{source_model_id}/{fingerprint}.semantic.json`."""
    return manifest_dir(root, source_model_id) / f"{fingerprint}{MANIFEST_SUFFIX}"


def is_contained(root: Path, candidate: Path) -> bool:
    """True only if `candidate` resolves inside `root` (traversal defense)."""
    try:
        candidate.resolve().relative_to(root.resolve())
        return True
    except (ValueError, OSError):
        return False


def compute_manifest_status(
    root: Path,
    source_model_id: int,
    fingerprint: str | None,
) -> ManifestStatus:
    """Classify manifest availability. Never raises, never leaks a path."""
    if not fingerprint:
        return ManifestStatus.UNAVAILABLE

    expected = expected_manifest_path(root, source_model_id, fingerprint)
    if not is_contained(root, expected):
        return ManifestStatus.UNAVAILABLE
    try:
        if expected.is_file():
            return ManifestStatus.READY
        directory = manifest_dir(root, source_model_id)
        if directory.is_dir() and any(
            p.name.endswith(MANIFEST_SUFFIX) for p in directory.iterdir()
        ):
            # An artifact for a previous version of this file. Reporting it as
            # STALE rather than READY is the whole point: binding against
            # semantics for different geometry would be silently wrong.
            return ManifestStatus.STALE
    except OSError:
        return ManifestStatus.UNAVAILABLE
    return ManifestStatus.MISSING
