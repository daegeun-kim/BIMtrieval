"""SQL-path-specific exceptions (spec_v003 §15).

All subclass shared.errors so route handlers can catch one shared base
without importing execution internals.
"""

from __future__ import annotations

from shared.errors import (
    LimitExceededError,
    PlanValidationError,
    ScopeViolationError,
    UnsupportedOperationError,
)


class FieldNotFoundError(UnsupportedOperationError):
    """A plan referenced a field absent from the source model's schema catalog."""


class AmbiguousFieldError(PlanValidationError):
    """A field concept resolved to multiple materially different values (spec_v003 §8).

    Callers should surface `candidates` to the user/planner as a clarification
    prompt rather than silently picking one.
    """

    def __init__(self, message: str, candidates: list[dict]) -> None:
        super().__init__(message)
        self.candidates = candidates


class CrossModelAccessError(ScopeViolationError):
    """A plan attempted to access records outside its declared source_model_id."""


class TraversalDepthExceededError(LimitExceededError):
    """Requested graph traversal depth exceeds the configured maximum (spec_v003 §12)."""


class UnsupportedFilterOperatorError(PlanValidationError):
    """An operator is not valid for the resolved field's declared type."""


class UnknownEntityOrRelationshipError(PlanValidationError):
    """A plan referenced an entity_id/relationship_id/global_id that does not exist."""
