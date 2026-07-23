"""Loading, validating, and caching v002 manifests (task26 §5).

Same reader discipline as the v001 loader it replaces: the backend never
builds, repairs, or falls back — a missing/stale/invalid artifact raises
`ManifestV002UnavailableError` and the question answers honestly that the
model is not query-ready.
"""

from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config.settings import Settings, get_settings
from app.query.semantic.contract import ACCESS_CONTRACT_VERSION
from app.query.semantic.manifest.paths import ManifestStatus, is_contained, manifest_dir
from app.query.semantic.manifest_v002.schema import (
    MANIFEST_SCHEMA_VERSION_V002,
    ManifestV002,
    parse_manifest_v002,
)

MANIFEST_SUFFIX_V002 = ".semantic.v002.json"


class ManifestV002UnavailableError(RuntimeError):
    """No valid, current v002 semantic manifest exists for the requested model."""

    def __init__(self, source_model_id: int, status: ManifestStatus, detail: str) -> None:
        self.source_model_id = source_model_id
        self.status = status
        super().__init__(detail)


def expected_manifest_v002_path(root: Path, source_model_id: int, fingerprint: str) -> Path:
    return manifest_dir(root, source_model_id) / f"{fingerprint}{MANIFEST_SUFFIX_V002}"


def compute_manifest_v002_status(
    root: Path, source_model_id: int, fingerprint: str | None
) -> ManifestStatus:
    if not fingerprint:
        return ManifestStatus.UNAVAILABLE
    expected = expected_manifest_v002_path(root, source_model_id, fingerprint)
    if not is_contained(root, expected):
        return ManifestStatus.UNAVAILABLE
    try:
        if expected.is_file():
            return ManifestStatus.READY
        directory = manifest_dir(root, source_model_id)
        if directory.is_dir() and any(
            p.name.endswith(MANIFEST_SUFFIX_V002) for p in directory.iterdir()
        ):
            return ManifestStatus.STALE
    except OSError:
        return ManifestStatus.UNAVAILABLE
    return ManifestStatus.MISSING


_CACHE: dict[tuple[Any, ...], ManifestV002] = {}
_LOCK = threading.Lock()


def get_manifest_v002(
    session: Session,
    source_model_id: int,
    settings: Settings | None = None,
) -> ManifestV002:
    settings = settings or get_settings()
    fingerprint = _model_fingerprint(session, source_model_id)
    root = settings.get_model_semantics_root()

    key = (source_model_id, fingerprint, MANIFEST_SCHEMA_VERSION_V002, str(root))
    cached = _CACHE.get(key)
    if cached is not None:
        return cached

    manifest = _load(root, source_model_id, fingerprint)
    with _LOCK:
        _CACHE[key] = manifest
    return manifest


def _model_fingerprint(session: Session, source_model_id: int) -> str | None:
    row = session.execute(
        text("SELECT file_fingerprint FROM ifc_source_models WHERE id = :id"),
        {"id": source_model_id},
    ).fetchone()
    return row[0] if row else None


def _load(root: Path, source_model_id: int, fingerprint: str | None) -> ManifestV002:
    status = compute_manifest_v002_status(root, source_model_id, fingerprint)
    if status is not ManifestStatus.READY:
        raise ManifestV002UnavailableError(source_model_id, status, _explain(status, source_model_id))

    path = expected_manifest_v002_path(root, source_model_id, fingerprint)
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ManifestV002UnavailableError(
            source_model_id,
            ManifestStatus.UNAVAILABLE,
            f"the semantic manifest for model {source_model_id} could not be read "
            f"({type(exc).__name__})",
        ) from None

    _validate(document, source_model_id, fingerprint)
    return parse_manifest_v002(document)


def _validate(document: dict[str, Any], source_model_id: int, fingerprint: str | None) -> None:
    identity = document.get("identity")
    content = document.get("content")
    if not isinstance(identity, dict) or not isinstance(content, dict):
        raise ManifestV002UnavailableError(
            source_model_id,
            ManifestStatus.UNAVAILABLE,
            f"the semantic manifest for model {source_model_id} is structurally invalid",
        )

    if int(identity.get("source_model_id", -1)) != source_model_id:
        raise ManifestV002UnavailableError(
            source_model_id,
            ManifestStatus.UNAVAILABLE,
            f"the semantic manifest at model {source_model_id}'s path describes model "
            f"{identity.get('source_model_id')}",
        )

    if fingerprint and identity.get("file_fingerprint") != fingerprint:
        raise ManifestV002UnavailableError(
            source_model_id,
            ManifestStatus.STALE,
            f"the semantic manifest for model {source_model_id} describes a different "
            "version of the source file",
        )

    if identity.get("manifest_schema_version") != MANIFEST_SCHEMA_VERSION_V002:
        raise ManifestV002UnavailableError(
            source_model_id,
            ManifestStatus.STALE,
            f"the semantic manifest for model {source_model_id} uses schema "
            f"{identity.get('manifest_schema_version')!r}, but this backend reads "
            f"{MANIFEST_SCHEMA_VERSION_V002!r}; re-run ingestion to regenerate it",
        )

    if identity.get("contract_version") != ACCESS_CONTRACT_VERSION:
        raise ManifestV002UnavailableError(
            source_model_id,
            ManifestStatus.STALE,
            f"the semantic manifest for model {source_model_id} was built against access "
            f"contract {identity.get('contract_version')!r}, but this backend uses "
            f"{ACCESS_CONTRACT_VERSION!r}",
        )

    if _content_hash(content) != identity.get("content_hash"):
        raise ManifestV002UnavailableError(
            source_model_id,
            ManifestStatus.UNAVAILABLE,
            f"the semantic manifest for model {source_model_id} failed its integrity check",
        )


def _content_hash(content: dict[str, Any]) -> str:
    canonical = json.dumps(
        content, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _explain(status: ManifestStatus, source_model_id: int) -> str:
    if status is ManifestStatus.STALE:
        return (
            f"the semantic manifest for model {source_model_id} was generated for a "
            "different version of the source file; re-run ingestion to regenerate it"
        )
    if status is ManifestStatus.MISSING:
        return (
            f"no v002 semantic manifest has been generated for model {source_model_id}; "
            "run the ingestion pipeline to make it query-ready"
        )
    return f"the semantic manifest for model {source_model_id} is unavailable"


def clear_manifest_v002_cache() -> None:
    with _LOCK:
        _CACHE.clear()
