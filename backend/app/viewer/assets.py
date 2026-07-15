"""Prepared-viewer-artifact path derivation, containment, and status
(spec_v006 §9, §10; Task 10 §2, §3).

The backend serves an already-prepared immutable Fragments artifact. It never
parses IFC, converts geometry, or writes any file here. Every artifact path is
DERIVED from database model identity (`source_model_id` + `source_fingerprint`)
under a backend-owned root — no path, filename, drive letter, or traversal
segment is ever taken from a request. The resolved server path is never
returned to a client (Task 10 §2/§3); only the opaque HTTP asset reference is.
"""

from __future__ import annotations

from pathlib import Path

from app.shared.types import ViewerAssetStatus

# spec_v006 §9.1 artifact naming convention.
VIEWER_ASSET_SUFFIX = ".frag"


def model_asset_dir(root: Path, source_model_id: int) -> Path:
    """The per-model artifact directory: `{root}/{source_model_id}`."""
    return root / str(source_model_id)


def expected_asset_path(root: Path, source_model_id: int, fingerprint: str) -> Path:
    """`{root}/{source_model_id}/{fingerprint}.frag`, derived from DB identity."""
    return model_asset_dir(root, source_model_id) / f"{fingerprint}{VIEWER_ASSET_SUFFIX}"


def is_contained(root: Path, candidate: Path) -> bool:
    """True only if `candidate` resolves inside `root` (traversal defense).

    Both sides are fully resolved before comparison so no `..` segment or
    symlink can escape the configured root (Task 10 §2/§3).
    """
    try:
        candidate.resolve().relative_to(root.resolve())
        return True
    except (ValueError, OSError):
        return False


def compute_asset_status(
    root: Path,
    source_model_id: int,
    fingerprint: str | None,
    *,
    catalog_status: str | None = None,
) -> ViewerAssetStatus:
    """Classify prepared-artifact availability for a model (spec_v006 §10.1).

    Never raises and never leaks a path: filesystem errors degrade to
    UNAVAILABLE.
    """
    if catalog_status == "unavailable":
        return ViewerAssetStatus.UNAVAILABLE
    if not fingerprint:
        return ViewerAssetStatus.MISSING

    expected = expected_asset_path(root, source_model_id, fingerprint)
    if not is_contained(root, expected):
        return ViewerAssetStatus.UNAVAILABLE
    try:
        if expected.is_file():
            return ViewerAssetStatus.READY
        directory = model_asset_dir(root, source_model_id)
        if directory.is_dir() and any(p.suffix == VIEWER_ASSET_SUFFIX for p in directory.iterdir()):
            return ViewerAssetStatus.STALE
    except OSError:
        return ViewerAssetStatus.UNAVAILABLE
    return ViewerAssetStatus.MISSING


def viewer_asset_ref(source_model_id: int) -> str:
    """The browser-safe HTTP asset reference for a model (Task 10 §3).

    Returned in `viewer_actions.viewer_source_location` and used by the frontend
    asset endpoint — never a Windows filesystem path.
    """
    return f"/api/models/{source_model_id}/viewer-asset"
