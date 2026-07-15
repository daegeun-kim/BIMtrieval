"""Viewer-asset path derivation, containment, and status (Task 10 §2, §3).

Pure filesystem/logic tests — no database, no OpenAI, no network.
"""

from __future__ import annotations

from pathlib import Path

from app.shared.types import ViewerAssetStatus
from app.viewer.assets import (
    VIEWER_ASSET_SUFFIX,
    compute_asset_status,
    expected_asset_path,
    is_contained,
    viewer_asset_ref,
)


def test_expected_path_is_derived_from_identity(tmp_path: Path):
    p = expected_asset_path(tmp_path, 7, "fp123")
    assert p == tmp_path / "7" / f"fp123{VIEWER_ASSET_SUFFIX}"


def test_containment_allows_derived_path(tmp_path: Path):
    assert is_contained(tmp_path, expected_asset_path(tmp_path, 1, "fp"))


def test_containment_rejects_traversal(tmp_path: Path):
    outside = tmp_path / "sub" / ".." / ".." / "secret.frag"
    assert is_contained(tmp_path, outside) is False


def test_status_ready_when_fingerprint_file_exists(tmp_path: Path):
    d = tmp_path / "1"
    d.mkdir()
    (d / f"fpA{VIEWER_ASSET_SUFFIX}").write_bytes(b"frag")
    assert compute_asset_status(tmp_path, 1, "fpA") is ViewerAssetStatus.READY


def test_status_stale_when_other_fingerprint_present(tmp_path: Path):
    d = tmp_path / "1"
    d.mkdir()
    (d / f"oldfp{VIEWER_ASSET_SUFFIX}").write_bytes(b"frag")
    assert compute_asset_status(tmp_path, 1, "newfp") is ViewerAssetStatus.STALE


def test_status_missing_when_no_directory(tmp_path: Path):
    assert compute_asset_status(tmp_path, 99, "fp") is ViewerAssetStatus.MISSING


def test_status_unavailable_when_catalog_marks_unavailable(tmp_path: Path):
    assert (
        compute_asset_status(tmp_path, 1, "fp", catalog_status="unavailable")
        is ViewerAssetStatus.UNAVAILABLE
    )


def test_asset_ref_is_http_path_not_filesystem():
    ref = viewer_asset_ref(5)
    assert ref == "/api/models/5/viewer-asset"
    assert ":" not in ref and "\\" not in ref
