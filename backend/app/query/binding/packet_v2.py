"""The adjudicated answer packet for LLM call 2 (task26 §12.3).

Contains every answer part with its status, operation-specific structured
facts with stable fact ids, the requested/contextual distinction, resolved
interpretation labels, bounded evidence excerpts with ids, limitations, and
the grounded terminology allowlist. Never the manifest, rejected
recommendations, raw rows, embeddings, unbounded GlobalId lists, or model
reasoning.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.query.binding.results_v2 import PartResultV2

__all__ = ["AnswerPacketV2", "build_answer_packet_v2"]


@dataclass
class AnswerPacketV2:
    question: str
    response_language: str = "en"
    parts: list[PartResultV2] = field(default_factory=list)
    primary_visual_part_id: str | None = None
    clarifications: list[str] = field(default_factory=list)

    def part(self, part_id: str) -> PartResultV2 | None:
        return next((p for p in self.parts if p.part_id == part_id), None)

    def fact_ids(self) -> set[str]:
        return {f["fact_id"] for p in self.parts for f in p.facts()}

    def evidence_ids(self) -> set[str]:
        out: set[str] = set()
        for part in self.parts:
            if part.evidence is not None:
                out.update(e.evidence_id for e in part.evidence.excerpts)
        return out

    def limitation_ids(self) -> set[str]:
        return {
            limitation["limitation_id"] for p in self.parts for limitation in p.limitations
        }

    def fact_value(self, fact_id: str) -> Any:
        for part in self.parts:
            for fact in part.facts():
                if fact["fact_id"] == fact_id:
                    return fact.get("value", fact.get("count"))
        return None

    def allowed_terms(self) -> set[str]:
        terms: set[str] = set()
        for part in self.parts:
            terms.update(t.casefold() for t in part.allowed_terms if t)
            for note in part.interpretation_notes:
                terms.update(w.casefold() for w in note.split())
        return terms

    def to_prompt_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "question": self.question,
            "response_language": self.response_language,
            "answer_parts": [p.to_packet_payload() for p in self.parts],
        }
        if self.primary_visual_part_id:
            payload["primary_visual_part_id"] = self.primary_visual_part_id
        if self.clarifications:
            payload["open_questions"] = self.clarifications[:3]
        terms = sorted(
            {t for p in self.parts for t in p.allowed_terms if t}
        )
        if terms:
            payload["allowed_terminology"] = terms[:60]
        return payload


def build_answer_packet_v2(
    question: str,
    parts: list[PartResultV2],
    *,
    response_language: str = "en",
    primary_visual_part_id: str | None = None,
    clarifications: list[str] | None = None,
) -> AnswerPacketV2:
    return AnswerPacketV2(
        question=question,
        response_language=response_language,
        parts=parts,
        primary_visual_part_id=primary_visual_part_id,
        clarifications=list(clarifications or []),
    )
