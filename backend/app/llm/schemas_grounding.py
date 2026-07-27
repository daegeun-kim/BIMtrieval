"""The grounding call's output: backend identities for pre-built slots (task30 §4).

The v5 original asked this call to return a complete typed logical plan — parts,
result kinds, Boolean structure, grouping, ordering, limits, viewer policy and
identities all at once — reconstructed from a lexical ledger while searching a
capability projection of tens of thousands of tokens. Structure the resolver had
already established was therefore re-invented on every request, and often
re-invented wrongly.

Here the structure is already fixed. This call answers exactly one question per
slot: which recorded concept serves it, or why none can. That is mechanical
backend binding, which is what a cheap model can do reliably, and it is the only
thing left for it to do.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

__all__ = ["SlotBinding", "GroundedBindings", "SEMANTIC_ID_MAX_LENGTH"]

#: One shared limit that safely accepts every manifest ID (contract id_rules).
SEMANTIC_ID_MAX_LENGTH = 120


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SlotBinding(_StrictModel):
    """The recorded concept that serves one slot, or the reason none does."""

    slot_id: str = Field(min_length=1, max_length=48)
    #: An id copied character for character from the slot's candidates or from
    #: the capability projection. Empty when the slot cannot be grounded.
    semantic_id: str | None = Field(default=None, max_length=SEMANTIC_ID_MAX_LENGTH)
    #: Only for a slot marked as combining peer subjects into one figure: the
    #: ids of the other members, in the order their slots were listed.
    union_semantic_ids: list[str] = Field(default_factory=list, max_length=4)
    #: Only for a relationship slot: the ids of the one to three path contracts
    #: composed in order, and the far-end subject when the request names one.
    path_semantic_ids: list[str] = Field(default_factory=list, max_length=3)
    endpoint_semantic_id: str | None = Field(
        default=None, max_length=SEMANTIC_ID_MAX_LENGTH
    )
    #: Why this model cannot serve the slot. Required when no id is given, and
    #: it must describe what the model does not record, never a question.
    unsupported_reason: str | None = Field(default=None, max_length=300)


class GroundedBindings(_StrictModel):
    """Planning call 2 output: one binding decision per slot (task30 §4)."""

    bindings: list[SlotBinding] = Field(default_factory=list, max_length=40)
    #: Slots whose recorded readings differ materially and cannot be chosen
    #: between safely. This is the ONLY route to a clarification from grounding.
    ambiguous_slot_ids: list[str] = Field(default_factory=list, max_length=6)
    ambiguity_question: str | None = Field(default=None, max_length=400)

    def by_slot(self) -> dict[str, SlotBinding]:
        return {b.slot_id: b for b in self.bindings}
