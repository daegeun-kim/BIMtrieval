"""RAG-path-specific exceptions (spec_v004 §14).

Subclass shared.errors.DegradedCapabilityError — a RAG failure is a
dependency-availability problem, not a plan-validation problem, and must
never disable SQL/graph paths (spec_v004 §4, §12 acceptance criterion 2).
"""

from __future__ import annotations

from app.shared.errors import DegradedCapabilityError


class EmbeddingServiceUnavailableError(DegradedCapabilityError):
    """The BGE-M3 embedding service failed to load or is not ready."""


class IncompatibleEmbeddingError(DegradedCapabilityError):
    """Stored rag_documents embeddings for this model/kind don't match the
    live query embedding model or dimension (spec_v004 §3)."""
