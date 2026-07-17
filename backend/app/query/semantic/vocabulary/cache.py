"""In-memory, backend-local cache for model vocabularies (Task 16 §3).

Keyed by (source_model_id, file_fingerprint, extraction_version,
profile_builder_version). The cache is process memory only — it never mutates
BIM tables or stored corpus vectors and requires no migration or re-ingestion.
If the source file fingerprint changes (a re-import under the same id), the key
changes and a fresh vocabulary is built.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config.settings import Settings, get_settings
from app.query.semantic.vocabulary.builder import (
    EXTRACTION_VERSION,
    PROFILE_BUILDER_VERSION,
    build_model_vocabulary,
)
from app.query.semantic.vocabulary.profiles import ModelVocabulary

_CACHE: dict[tuple, ModelVocabulary] = {}


def _fingerprint(session: Session, source_model_id: int) -> str | None:
    row = session.execute(
        text("SELECT file_fingerprint FROM ifc_source_models WHERE id = :id"),
        {"id": source_model_id},
    ).first()
    return row[0] if row else None


def get_model_vocabulary(
    session: Session, source_model_id: int, settings: Settings | None = None
) -> ModelVocabulary:
    """Return the cached vocabulary for a source model, building it on a miss."""
    settings = settings or get_settings()
    fingerprint = _fingerprint(session, source_model_id)
    if fingerprint is None:
        raise ValueError(f"source_model_id {source_model_id} does not exist")
    key = (source_model_id, fingerprint, EXTRACTION_VERSION, PROFILE_BUILDER_VERSION)
    cached = _CACHE.get(key)
    if cached is not None:
        return cached
    vocab = build_model_vocabulary(session, source_model_id, settings)
    _CACHE[key] = vocab
    return vocab


def clear_vocabulary_cache() -> None:
    _CACHE.clear()
