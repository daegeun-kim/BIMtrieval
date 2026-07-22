"""Loading, validating, and caching semantic manifests (task25 §2.1, §8).

The backend is a strict READER here. It never builds, repairs, or writes a
manifest — that is ingestion's job, and keeping it one-directional is what makes
the artifact a real contract rather than two implementations that drift.

Three validations run before a manifest is trusted, because each failure mode
produces a differently-wrong answer:

- the artifact must exist for the model's CURRENT fingerprint (otherwise the
  binder reasons about a different version of the file);
- its `content_hash` must match its content (otherwise it was truncated or
  edited);
- its `source_model_id` must match the model requested (otherwise a question
  binds against another building entirely).

Any failure raises `ManifestUnavailableError`. There is deliberately no fallback
to the legacy capped vocabulary: §8 forbids running the old and new semantic
sources as competing active paths, and a silent downgrade would reintroduce
exactly the information loss this task exists to remove.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config.settings import Settings, get_settings
from app.query.semantic.manifest.paths import (
    ManifestStatus,
    compute_manifest_status,
    expected_manifest_path,
)
from app.query.semantic.manifest.schema import (
    MANIFEST_SCHEMA_VERSION,
    SemanticManifest,
    parse_manifest,
)


class ManifestUnavailableError(RuntimeError):
    """No valid, current semantic manifest exists for the requested model."""

    def __init__(self, source_model_id: int, status: ManifestStatus, detail: str) -> None:
        self.source_model_id = source_model_id
        self.status = status
        super().__init__(detail)


#: Process cache. Keyed so that a changed model, file, schema, or builder all
#: invalidate naturally — there is no TTL and no manual flush in the query path.
_CACHE: dict[tuple[Any, ...], SemanticManifest] = {}
_LOCK = threading.Lock()


def get_semantic_manifest(
    session: Session,
    source_model_id: int,
    settings: Settings | None = None,
) -> SemanticManifest:
    """Return the validated manifest for `source_model_id`.

    Raises `ManifestUnavailableError` when no current, valid artifact exists.
    """
    settings = settings or get_settings()
    fingerprint = _model_fingerprint(session, source_model_id)
    root = settings.get_model_semantics_root()

    key = (source_model_id, fingerprint, MANIFEST_SCHEMA_VERSION, str(root))
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


def _load(root: Path, source_model_id: int, fingerprint: str | None) -> SemanticManifest:
    status = compute_manifest_status(root, source_model_id, fingerprint)
    if status is not ManifestStatus.READY:
        raise ManifestUnavailableError(
            source_model_id,
            status,
            _explain(status, source_model_id),
        )

    path = expected_manifest_path(root, source_model_id, fingerprint)
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ManifestUnavailableError(
            source_model_id,
            ManifestStatus.UNAVAILABLE,
            f"the semantic manifest for model {source_model_id} could not be read "
            f"({type(exc).__name__})",
        ) from None

    _validate(document, source_model_id, fingerprint)
    return parse_manifest(document)


def _validate(document: dict[str, Any], source_model_id: int, fingerprint: str | None) -> None:
    identity = document.get("identity")
    content = document.get("content")
    if not isinstance(identity, dict) or not isinstance(content, dict):
        raise ManifestUnavailableError(
            source_model_id,
            ManifestStatus.UNAVAILABLE,
            f"the semantic manifest for model {source_model_id} is structurally invalid",
        )

    # Source isolation: a manifest naming another model must never be used, even
    # if it somehow occupies the right path.
    if int(identity.get("source_model_id", -1)) != source_model_id:
        raise ManifestUnavailableError(
            source_model_id,
            ManifestStatus.UNAVAILABLE,
            f"the semantic manifest at model {source_model_id}'s path describes model "
            f"{identity.get('source_model_id')}",
        )

    if fingerprint and identity.get("file_fingerprint") != fingerprint:
        raise ManifestUnavailableError(
            source_model_id,
            ManifestStatus.STALE,
            f"the semantic manifest for model {source_model_id} describes a different "
            "version of the source file",
        )

    if identity.get("manifest_schema_version") != MANIFEST_SCHEMA_VERSION:
        raise ManifestUnavailableError(
            source_model_id,
            ManifestStatus.STALE,
            f"the semantic manifest for model {source_model_id} uses schema "
            f"{identity.get('manifest_schema_version')!r}, but this backend reads "
            f"{MANIFEST_SCHEMA_VERSION!r}; re-run ingestion to regenerate it",
        )

    if _content_hash(content) != identity.get("content_hash"):
        raise ManifestUnavailableError(
            source_model_id,
            ManifestStatus.UNAVAILABLE,
            f"the semantic manifest for model {source_model_id} failed its integrity check",
        )


def _content_hash(content: dict[str, Any]) -> str:
    """Recompute the writer's hash. Must mirror the ingestion serializer exactly."""
    import hashlib

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
            f"no semantic manifest has been generated for model {source_model_id}; "
            "run the ingestion notebook to make it query-ready"
        )
    return f"the semantic manifest for model {source_model_id} is unavailable"


def clear_manifest_cache() -> None:
    """Drop the process cache. For tests and for post-ingestion refresh."""
    with _LOCK:
        _CACHE.clear()
