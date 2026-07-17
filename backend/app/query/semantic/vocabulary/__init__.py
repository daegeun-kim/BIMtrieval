"""Dynamic active-model semantic vocabulary (Task 16 §3).

A bounded, read-only, model-specific vocabulary derived from the live database
so the system learns exporter-specific and multilingual representations (e.g.
Dutch `plat dak`, `liftdeur`) without any manual synonym dictionary. Cached in
memory per source model; never mutates BIM tables or stored corpus vectors.
"""

from app.query.semantic.vocabulary.builder import PROFILE_BUILDER_VERSION, build_model_vocabulary
from app.query.semantic.vocabulary.cache import get_model_vocabulary
from app.query.semantic.vocabulary.profiles import (
    ClassProfile,
    ModelVocabulary,
    ObservedFactProfile,
    QuantityCoverageProfile,
)

__all__ = [
    "PROFILE_BUILDER_VERSION",
    "build_model_vocabulary",
    "get_model_vocabulary",
    "ClassProfile",
    "ModelVocabulary",
    "ObservedFactProfile",
    "QuantityCoverageProfile",
]
