"""Read-only repository interface shape.

Concrete query compilation (allowlisted operations, parameterized SQL,
source_model_id scoping) is v003 scope. This module only fixes the shared
shape so v003 can implement against a stable interface.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from sqlalchemy.orm import Session


class ReadOnlyRepository(ABC):
    """Base class for repositories used by the query paths.

    Implementations must scope every query by `source_model_id` where
    applicable (spec_v002 Section 20) and must never accept raw SQL fragments.
    """

    def __init__(self, session: Session) -> None:
        self.session = session

    @abstractmethod
    def get_by_id(self, entity_id: int) -> Any:
        raise NotImplementedError
