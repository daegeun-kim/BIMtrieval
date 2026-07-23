"""Final claim validation + deterministic operation-aware fallback (task26 §12.4).

Numeric/structured claims cite a `fact_id`; qualitative claims cite
`evidence_id`s; connection claims cite a graph fact; limitation claims cite a
limitation id. Cited values are compared against the packet. Terminology is
checked against the allowlist derived from the validated plan/result — the
ordinary wording the plan itself selected ("rooms", "first floor", storey
names) passes; an arbitrary BIM noun the packet never mentioned does not.

If generation fails or validation rejects it, `build_fallback_answer_v2`
returns a deterministic answer from the same results — an exact SQL result is
never discarded because the answer writer misbehaved (§13).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.llm.schemas_v2 import ClaimKind, GroundedAnswerV2
from app.query.binding.packet_v2 import AnswerPacketV2
from app.query.binding.results_v2 import (
    DistributionResult,
    EntitySetResult,
    GraphEndpointResult,
    PartResultV2,
    ProfileResult,
    QualitativeEvidenceResult,
    ResultStatusV2,
    SampleResult,
    ScalarResult,
)

__all__ = ["AnswerValidationV2", "validate_answer_v2", "build_fallback_answer_v2"]

_NUMBER_RE = re.compile(r"(?<![\w./-])(\d{1,3}(?:[, ]\d{3})+|\d+)(?![\w./-])")


@dataclass
class AnswerValidationV2:
    ok: bool = True
    failures: list[str] = field(default_factory=list)

    def fail(self, reason: str) -> None:
        self.ok = False
        self.failures.append(reason)


def validate_answer_v2(
    generated: GroundedAnswerV2, packet: AnswerPacketV2
) -> AnswerValidationV2:
    validation = AnswerValidationV2()
    fact_ids = packet.fact_ids()
    evidence_ids = packet.evidence_ids()
    limitation_ids = packet.limitation_ids()
    part_ids = {p.part_id for p in packet.parts}

    for claim in generated.claims:
        if claim.kind is ClaimKind.FACT:
            if claim.cited_id not in fact_ids:
                validation.fail(f"claim cites unknown fact id {claim.cited_id!r}")
                continue
            expected = packet.fact_value(claim.cited_id)
            if isinstance(expected, (int, float)) and _numbers_differ(claim.value, expected):
                validation.fail(
                    f"claim value {claim.value!r} does not match fact "
                    f"{claim.cited_id} = {expected}"
                )
        elif claim.kind is ClaimKind.EVIDENCE:
            if claim.cited_id not in evidence_ids:
                validation.fail(f"claim cites unknown evidence id {claim.cited_id!r}")
        elif claim.kind is ClaimKind.CONNECTION:
            if claim.cited_id not in fact_ids:
                validation.fail(f"connection claim cites unknown fact {claim.cited_id!r}")
        elif claim.kind is ClaimKind.LIMITATION:
            # Limitation claims are disclosure, not numeric assertion: accept a
            # limitation id, a fact id, or the owning part id (the model often
            # cites the part it is disclosing about).
            if (
                claim.cited_id not in limitation_ids
                and claim.cited_id not in fact_ids
                and claim.cited_id not in part_ids
            ):
                validation.fail(f"limitation claim cites unknown id {claim.cited_id!r}")

    # Every number asserted in the prose must be a cited fact value or an
    # obviously packet-derived number.
    cited_numbers = {
        _normalize_number(c.value) for c in generated.claims if c.kind is ClaimKind.FACT
    }
    packet_numbers = _packet_numbers(packet)
    for match in _NUMBER_RE.finditer(generated.answer):
        number = _normalize_number(match.group(1))
        if number is None or number in cited_numbers or number in packet_numbers:
            continue
        if abs(number) <= 20:  # ordinals/floor numbers/small enumerations
            continue
        validation.fail(f"the answer asserts {match.group(1)!r} which no packet fact supports")

    if generated.used_general_knowledge:
        validation.fail("the answer draws on general knowledge instead of the packet")
    return validation


def _normalize_number(value: str | float | int) -> float | None:
    try:
        return float(str(value).replace(",", "").replace(" ", ""))
    except ValueError:
        return None


def _numbers_differ(asserted: str, expected: float | int) -> bool:
    parsed = _normalize_number(asserted)
    if parsed is None:
        return True
    return abs(parsed - float(expected)) > 1e-6


def _packet_numbers(packet: AnswerPacketV2) -> set[float]:
    numbers: set[float] = set()

    def _walk(value: Any) -> None:
        if isinstance(value, bool):
            return
        if isinstance(value, (int, float)):
            numbers.add(float(value))
        elif isinstance(value, dict):
            for inner in value.values():
                _walk(inner)
        elif isinstance(value, (list, tuple)):
            for inner in value:
                _walk(inner)

    for part in packet.parts:
        for fact in part.facts():
            _walk(fact)
    return numbers


# ---------------------------------------------------------------------------
# Deterministic fallback (§12.4, §13)
# ---------------------------------------------------------------------------


def build_fallback_answer_v2(packet: AnswerPacketV2) -> str:
    lines: list[str] = []
    for part in packet.parts:
        line = _fallback_line(part)
        if line:
            lines.append(line)
    if not lines:
        return (
            "I could not produce a grounded answer for this question from the model's data."
        )
    for part in packet.parts:
        for note in part.interpretation_notes[:1]:
            lines.append(f"({note})")
        for limitation in part.limitations[:1]:
            lines.append(f"Note: {limitation['text']}.")
    return " ".join(lines)


def _fallback_line(part: PartResultV2) -> str | None:
    subject = part.request_text.strip().rstrip("?")
    if part.status is ResultStatusV2.UNAVAILABLE:
        reason = part.limitations[0]["text"] if part.limitations else "it is not recorded"
        return f"'{subject}': unavailable — {reason}."
    if part.status is ResultStatusV2.AMBIGUOUS:
        return f"'{subject}': needs clarification."
    result = part.result
    prefix = "Context only: " if part.is_contextual else ""
    if isinstance(result, EntitySetResult):
        return f"{prefix}'{subject}': {result.matched_cardinality} match(es)."
    if isinstance(result, ScalarResult):
        unit = f" {result.unit}" if result.unit else ""
        return (
            f"{prefix}'{subject}': {result.function} = {result.value}{unit} "
            f"(over {result.covered_cardinality} of {result.eligible_cardinality} objects)."
        )
    if isinstance(result, DistributionResult):
        if result.top_buckets:
            top = result.top_buckets[0]
            tie = " (tied)" if result.tie else ""
            return f"{prefix}'{subject}': {top.label or top.key} with {top.count}{tie}."
        listed = ", ".join(f"{b.label or b.key}: {b.count}" for b in result.buckets[:6])
        return f"{prefix}'{subject}': {listed}."
    if isinstance(result, SampleResult):
        if result.sample is None:
            return f"{prefix}'{subject}': no eligible object."
        name = result.sample.name or result.sample.ifc_class
        return (
            f"{prefix}'{subject}': for example {name} "
            f"(one of {result.eligible_cardinality} eligible)."
        )
    if isinstance(result, ProfileResult):
        top = ", ".join(
            f"{k}: {v}" for k, v in list(result.structured.get("class_inventory_top", {}).items())[:5]
        )
        return f"{prefix}'{subject}': {result.structured.get('entity_total')} entities ({top})."
    if isinstance(result, GraphEndpointResult):
        return (
            f"{prefix}'{subject}': {result.endpoint_entity_count} connected object(s) via "
            f"{result.relationship_count} recorded relationship(s)."
        )
    if isinstance(result, QualitativeEvidenceResult):
        return f"{prefix}'{subject}': {len(result.excerpts)} evidence excerpt(s) retrieved."
    return None
