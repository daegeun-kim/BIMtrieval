"""The compact answer packet sent to LLM call 2 (Task 24 §8.2).

The final LLM's only job is to EXPRESS results that have already been
adjudicated (§8.1). Everything it would need in order to re-decide the question
is therefore withheld by construction, not by instruction:

    no rejected candidates          no similarity scores
    no planner reasoning            no unselected ontology candidates
    no repeated group ids to sort   no 50 cross-group examples
    no complete viewer identities   no raw canonical JSON
    no database ids                 no SQL

That list is §8.2's "do not send" verbatim, and each exclusion has a matching
test. The reason it is structural rather than a prompt rule: a previous
architecture handed the answering model competing evidence groups and asked it
to both choose and write, which is how a count of spaces became "778 parking
spaces". If the model never receives alternatives, it cannot pick the wrong one.

Every fact the model may assert carries a stable `fact_id`. Final validation
(§8.3) then checks each structured claim against the packet by id, so a number
that does not come from the database cannot survive.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.config.settings import Settings, get_settings
from app.query.binding.evidence import AnswerPartResult, ResultStatus

__all__ = ["AnswerPacket", "FactRecord", "build_answer_packet"]

#: §10.2 — "default to at most 3 examples per answer part".
DEFAULT_EXAMPLE_LIMIT = 3


@dataclass(frozen=True)
class FactRecord:
    """One checkable numeric/textual fact the answer may cite.

    `value` is the authoritative value straight from execution. Final
    validation compares the model's structured claims against these by id, so
    a fabricated or drifted number is caught deterministically (§8.3).
    """

    fact_id: str
    part_id: str
    kind: str  # total | aggregate | distribution | endpoint_count | coverage
    value: Any
    unit: str | None = None
    label: str = ""

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"id": self.fact_id, "kind": self.kind, "value": self.value}
        if self.unit:
            payload["unit"] = self.unit
        if self.label:
            payload["about"] = self.label
        return payload


@dataclass
class AnswerPacket:
    """Everything LLM call 2 receives, and nothing else."""

    question: str
    response_language: str = "en"
    parts: list[dict[str, Any]] = field(default_factory=list)
    facts: list[FactRecord] = field(default_factory=list)
    #: Which answer part drives the viewer, for the model's phrasing only —
    #: the backend owns the actual selection (§8.3, §9).
    primary_visual_part_id: str | None = None

    def fact(self, fact_id: str) -> FactRecord | None:
        return next((f for f in self.facts if f.fact_id == fact_id), None)

    def part_ids(self) -> set[str]:
        return {p["part_id"] for p in self.parts}

    def to_prompt_payload(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "respond_in_language": self.response_language,
            "answer_parts": self.parts,
            "facts": [f.to_payload() for f in self.facts],
        }


def build_answer_packet(
    question: str,
    results: list[AnswerPartResult],
    *,
    response_language: str = "en",
    primary_visual_part_id: str | None = None,
    settings: Settings | None = None,
) -> AnswerPacket:
    """Build the §8.2 packet from adjudicated answer-part results."""
    settings = settings or get_settings()
    packet = AnswerPacket(
        question=question,
        response_language=response_language,
        primary_visual_part_id=primary_visual_part_id,
    )

    for result in results:
        entry: dict[str, Any] = {
            "part_id": result.part_id,
            "you_were_asked": result.request_text,
            "status": result.status.value,
        }
        if result.interpretation:
            entry["interpreted_as"] = result.interpretation

        _add_totals(packet, result, entry)
        _add_distribution(result, entry)
        _add_examples(result, entry, settings)
        _add_graph(packet, result, entry)
        _add_limitation(result, entry)
        packet.parts.append(entry)

    return packet


def _fact_id(part_id: str, suffix: str) -> str:
    return f"{part_id}.{suffix}"


def _add_totals(packet: AnswerPacket, result: AnswerPartResult, entry: dict) -> None:
    """Exact totals and aggregates, each as a checkable fact."""
    if result.exact_total is not None and result.operation != "relationship":
        fact_id = _fact_id(result.part_id, "total")
        packet.facts.append(
            FactRecord(
                fact_id=fact_id,
                part_id=result.part_id,
                kind="total",
                value=result.exact_total,
                label=result.request_text,
            )
        )
        entry["exact_total"] = {"fact_id": fact_id, "value": result.exact_total}

    if result.aggregate is not None:
        fact_id = _fact_id(result.part_id, "aggregate")
        packet.facts.append(
            FactRecord(
                fact_id=fact_id,
                part_id=result.part_id,
                kind="aggregate",
                value=result.aggregate.value,
                unit=result.aggregate.unit,
                label=f"{result.aggregate.function} for {result.request_text}",
            )
        )
        entry["aggregate"] = {
            "fact_id": fact_id,
            "function": result.aggregate.function,
            "value": result.aggregate.value,
            "unit": result.aggregate.unit,
            # Coverage travels WITH the number so the model cannot present a
            # partially-covered aggregate as complete (§6).
            "covers": result.aggregate.coverage_count,
            "of_matching": result.aggregate.matched_count,
            "complete": result.aggregate.complete,
        }

    # A class breakdown is included only when the result genuinely spans several
    # classes; §8.2 allows it "only when requested or necessary".
    if len(result.class_breakdown) > 1:
        entry["by_class"] = [
            {"ifc_class": cls, "count": count} for cls, count in result.class_breakdown.items()
        ]


def _add_distribution(result: AnswerPartResult, entry: dict) -> None:
    if not result.distribution:
        return
    entry["distribution"] = [
        {"value": bucket.key, "count": bucket.count} for bucket in result.distribution[:20]
    ]


def _add_examples(result: AnswerPartResult, entry: dict, settings: Settings) -> None:
    """Bounded representative examples — never a whole inventory (§8.2, §10.2).

    Identities are deliberately absent: the viewer channel owns GlobalIds, and
    §8.2 forbids sending complete viewer identities to the answering model.
    """
    if not result.examples:
        return
    limit = (
        min(settings.max_list_limit, len(result.examples))
        if result.operation == "list"
        else DEFAULT_EXAMPLE_LIMIT
    )
    entry["examples"] = [_example_payload(example) for example in result.examples[:limit]]
    if result.exact_total is not None and result.exact_total > len(entry["examples"]):
        entry["examples_note"] = (
            f"{len(entry['examples'])} of {result.exact_total} shown as examples; "
            "the exact total above is the answer"
        )


def _example_payload(example) -> dict[str, Any]:
    payload: dict[str, Any] = {"ifc_class": example.ifc_class}
    if example.name:
        payload["name"] = example.name
    if example.storey_name:
        payload["storey"] = example.storey_name
    return payload


def _add_graph(packet: AnswerPacket, result: AnswerPartResult, entry: dict) -> None:
    if result.operation != "relationship":
        return
    fact_id = _fact_id(result.part_id, "endpoints")
    count = len(result.graph_endpoints)
    packet.facts.append(
        FactRecord(
            fact_id=fact_id,
            part_id=result.part_id,
            kind="endpoint_count",
            value=count,
            label=f"objects connected for {result.request_text}",
        )
    )
    entry["connected"] = {
        "fact_id": fact_id,
        "count": count,
        # Bounded endpoints only, and explicitly labelled as computed by
        # traversal so the model cannot present inference as connectivity (§5.4).
        "established_by": "graph traversal over recorded IFC relationships",
        "examples": [_example_payload(e) for e in result.graph_endpoints[:DEFAULT_EXAMPLE_LIMIT]],
    }


def _add_limitation(result: AnswerPartResult, entry: dict) -> None:
    """One concise reason for a non-exact result, plus the known/unknown split.

    §6 requires partial evidence to identify the known and unknown parts
    separately — a single blended sentence lets a gap read as a result.
    """
    if result.limitation:
        entry["limitation"] = result.limitation
    if result.status is ResultStatus.PARTIAL:
        if result.known_parts:
            entry["known"] = result.known_parts
        if result.unknown_parts:
            entry["not_known"] = result.unknown_parts
    if result.rag_candidate_count is not None:
        # Explicitly labelled as bounded so it can never be read as a total
        # (§5.3: "RAG is bounded semantic evidence, never an exact total").
        entry["semantic_examples_considered"] = {
            "count": result.rag_candidate_count,
            "note": "bounded semantic evidence, not a total",
        }
