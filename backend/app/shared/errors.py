"""Shared error hierarchy for the query architecture.

These are raised by plan validation and (in later tasks) by SQL/RAG/graph/hybrid
execution. Keeping them here — rather than per-path modules — lets API route
handlers catch one shared base without importing execution internals.
"""

from __future__ import annotations


class BimRagError(Exception):
    """Base class for all backend query-architecture errors."""


class PlanValidationError(BimRagError):
    """A query plan failed schema/semantic validation (spec_v002 Section 8)."""


class UnsupportedOperationError(PlanValidationError):
    """Plan requested an operation outside the allowlisted vocabulary."""


class ScopeViolationError(PlanValidationError):
    """Plan requested detailed retrieval without a valid active-model scope."""


class ModelNotFoundError(PlanValidationError):
    """Plan referenced a source_model_id that does not exist."""


class LimitExceededError(PlanValidationError):
    """Plan requested a result/traversal size beyond configured limits."""


class DegradedCapabilityError(BimRagError):
    """A required backend capability (e.g. the embedding service) is unavailable.

    Distinct from PlanValidationError: the plan itself was valid, but a
    dependency needed to execute it is not currently available
    (spec_v002 Section 11.4).
    """
