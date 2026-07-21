"""Session-only state, store, and reset semantics (spec_v005 §12).

State is in-memory / per-browser-session only — nothing here is persisted to
the database, so `reset()` cannot and does not delete IFC source records,
structured rows, embeddings, or catalog metadata; it only replaces the
in-memory SessionState with a fresh one for the same session_id.

The store keeps, per session: the active model, pending catalog-candidate ids
awaiting user confirmation (spec_v005 §13), and the previous turn's canonical
result ids so follow-up questions resolve against stored ids rather than being
reconstructed from assistant prose (spec_v005 §12).
"""

from __future__ import annotations

import threading
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.shared.types import QueryScope

MAX_SELECTED_ENTITY_IDS = 5


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class SessionState(BaseModel):
    """spec_v005 §12 — everything a browser session carries."""

    model_config = ConfigDict(extra="forbid")

    session_id: str
    mode: QueryScope = QueryScope.MODEL_CATALOG
    active_source_model_id: int | None = None
    chat_history: list[ChatMessage] = Field(default_factory=list)
    selected_entity_ids: list[int] = Field(default_factory=list, max_length=MAX_SELECTED_ENTITY_IDS)

    # Catalog candidates offered but not yet confirmed/loaded (spec_v005 §13).
    pending_candidate_model_ids: list[int] = Field(default_factory=list)

    # Previous turn's canonical results, for canonical-ID follow-ups (spec_v005 §12).
    last_route: str | None = None
    last_primary_entity_ids: list[int] = Field(default_factory=list)
    last_context_entity_ids: list[int] = Field(default_factory=list)
    last_relationship_ids: list[int] = Field(default_factory=list)

    # --- Typed previous-result scope (Task 24 §7) ---
    # A REPRODUCIBLE description of the last accepted result, replacing the
    # truncated id lists above as the basis for follow-ups. Storing the typed
    # predicate rather than ids is what lets "how many of those are external?"
    # cover the complete previous result instead of its first 50-200 members.
    # `Any` because `PreviousScope` is a dataclass, not a pydantic model, and
    # this state is process-local and never serialized to a client.
    previous_scope: Any = None


def reset(state: SessionState) -> SessionState:
    """Return a fresh SessionState for the same session_id (spec_v005 §12).

    Clears chat history, active model selection, selected viewer objects, pending
    candidates, and prior result context. Preserving only `session_id` means
    nothing persistent-data-related is ever referenced by the return value, let
    alone deleted.
    """
    return SessionState(session_id=state.session_id)


class SessionStore:
    """Process-wide, thread-safe, in-memory session registry."""

    def __init__(self) -> None:
        self._sessions: dict[str, SessionState] = {}
        self._lock = threading.Lock()

    def get_or_create(self, session_id: str) -> SessionState:
        with self._lock:
            state = self._sessions.get(session_id)
            if state is None:
                state = SessionState(session_id=session_id)
                self._sessions[session_id] = state
            return state

    def save(self, state: SessionState) -> None:
        with self._lock:
            self._sessions[state.session_id] = state

    def reset(self, session_id: str) -> SessionState:
        with self._lock:
            fresh = SessionState(session_id=session_id)
            self._sessions[session_id] = fresh
            return fresh


_STORE = SessionStore()


def get_session_store() -> SessionStore:
    return _STORE
