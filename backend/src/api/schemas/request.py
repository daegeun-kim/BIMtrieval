"""Request envelope for POST /api/query (spec_v002 Section 16.1).

`selected_entity_ids` is capped at 5 (spec_v002 Section 15: "Limit selected
viewer objects supplied to LLM context to five"). `history` is capped at 20
turns as a bounded-history default (Section 16.3: "bounded history").
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

MAX_SELECTED_ENTITY_IDS = 5
MAX_HISTORY_TURNS = 20


class HistoryTurn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class SessionQueryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # `question` may be a placeholder when `reset` or `confirm_model_id` is set
    # (those are control actions, not natural-language questions) — spec_v005 §12/§13.
    question: str = Field(min_length=1, max_length=2000)
    session_id: str = Field(min_length=1, max_length=128)
    active_source_model_id: int | None = None
    selected_entity_ids: list[int] = Field(default_factory=list, max_length=MAX_SELECTED_ENTITY_IDS)
    history: list[HistoryTurn] = Field(default_factory=list, max_length=MAX_HISTORY_TURNS)

    # Clear all session chat/selection/result state and active model (spec_v005 §12).
    reset: bool = False
    # Confirm loading a catalog model candidate the user clicked (spec_v005 §13).
    confirm_model_id: int | None = None
