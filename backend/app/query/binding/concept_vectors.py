"""Cached concept-embedding matrix per manifest content hash (task26 §7.2).

Dense recall is an always-run parallel channel, so its cost must be one matrix
build per (manifest content hash × embedding model × normalization version),
never a re-embedding of the remaining concepts per ledger requirement. The
matrix lives in the process cache; each material query span is embedded once
per request.

Vectors never appear in prompts or traces.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Callable

import numpy as np

from app.query.semantic.manifest_v002.schema import ManifestV002

#: Bump when concept-text normalization changes; part of the cache key.
NORMALIZATION_VERSION = "cv1"


@dataclass(frozen=True)
class ConceptVectorIndex:
    """Normalized concept vectors with their aligned semantic IDs."""

    semantic_ids: tuple[str, ...]
    matrix: np.ndarray  # (n_concepts, dim), rows L2-normalized
    embedding_model: str

    def rank(self, query_vector: np.ndarray, top_k: int = 12) -> list[tuple[str, float]]:
        query = np.asarray(query_vector, dtype="float32")
        norm = float(np.linalg.norm(query))
        if norm <= 0 or not len(self.semantic_ids):
            return []
        query /= norm
        similarities = self.matrix @ query
        order = np.argsort(-similarities)[:top_k]
        return [
            (self.semantic_ids[i], float(similarities[i]))
            for i in order
            if similarities[i] > 0
        ]


_CACHE: dict[tuple[str, str, str], ConceptVectorIndex] = {}
_LOCK = threading.Lock()


def _concept_texts(manifest: ManifestV002) -> list[tuple[str, str]]:
    """(semantic_id, search text) for every selectable concept, deterministic."""
    out: list[tuple[str, str]] = []
    for capability in sorted(manifest.capabilities.values(), key=lambda c: c.semantic_id):
        out.append((capability.semantic_id, capability.search_text))
    for traversal in sorted(manifest.traversals.values(), key=lambda t: t.semantic_id):
        out.append((traversal.semantic_id, traversal.search_text))
    for profile in sorted(manifest.profiles.values(), key=lambda p: p.semantic_id):
        out.append((profile.semantic_id, profile.search_text))
    return [(sid, text) for sid, text in out if text.strip()]


def get_concept_vector_index(
    manifest: ManifestV002,
    embedding_service: Any,
) -> ConceptVectorIndex | None:
    """The cached index for this manifest, building it once if needed.

    Returns None when the embedding service is unavailable — dense recall then
    degrades for this request without failing the query.
    """
    model_name = getattr(embedding_service, "model_name", "") or str(
        type(embedding_service).__name__
    )
    key = (manifest.content_hash, model_name, NORMALIZATION_VERSION)
    cached = _CACHE.get(key)
    if cached is not None:
        return cached

    pairs = _concept_texts(manifest)
    if not pairs:
        return None
    try:
        vectors = embedding_service.embed_texts([text for _, text in pairs])
        matrix = np.asarray(vectors, dtype="float32")
        norms = np.clip(np.linalg.norm(matrix, axis=1, keepdims=True), 1e-9, None)
        matrix = matrix / norms
    except Exception:  # noqa: BLE001 - dense recall degrades, never fails a query
        return None

    index = ConceptVectorIndex(
        semantic_ids=tuple(sid for sid, _ in pairs),
        matrix=matrix,
        embedding_model=model_name,
    )
    with _LOCK:
        _CACHE[key] = index
    return index


def embed_query_texts(
    embedding_service: Any, texts: list[str]
) -> dict[str, np.ndarray] | None:
    """Embed each DISTINCT material span once per request (§7.2)."""
    distinct = sorted({t for t in texts if t.strip()})
    if not distinct:
        return {}
    try:
        vectors = embedding_service.embed_texts(distinct)
    except Exception:  # noqa: BLE001
        return None
    return {text: np.asarray(vec, dtype="float32") for text, vec in zip(distinct, vectors)}


def clear_concept_vector_cache() -> None:
    with _LOCK:
        _CACHE.clear()


def cache_key_getter() -> Callable[[], int]:
    return lambda: len(_CACHE)
