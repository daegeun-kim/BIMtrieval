"""Final claim validation + deterministic operation-aware fallback (task26 §12.4).

Numeric/structured claims cite a `fact_id`; qualitative claims cite
`evidence_id`s; connection claims cite a graph fact; limitation claims cite a
limitation id. Cited values are compared against the packet.

Task 27 §6 changes what "valid" means in two directions at once, because the
recorded run failed in both:

- Too strict where citations are concerned. A grouped extremum fact carries BOTH
  a bucket key and a count, and citing the key was rejected as "does not match
  fact P2:top1 = 142"; a limitation cited as a `connection` and a projection
  distribution cited as `evidence` were rejected for their KIND while the id was
  real. Six of the recorded answers were discarded for bookkeeping like this and
  replaced by the deterministic fallback. A claim is now checked against every
  citable value of the id it names, and an id that exists in the packet is
  accepted whatever claim kind carries it.
- Too permissive where the prose is concerned. An answer said "the packet does
  not provide a count" about an exact count of 54; another disclosed a
  limitation the packet never recorded; several exposed internal vocabulary.
  Those are now rejections.

If generation fails or validation rejects it, `build_fallback_answer_v2` returns
a deterministic answer from the same results in the same plain language the
answerer is held to — an exact SQL result is never discarded because the answer
writer misbehaved (§13).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.llm.schemas_v2 import ClaimKind, GroundedAnswerV2
from app.query.binding.packet_v2 import AnswerPacketV2
from app.query.binding.phrasing import (
    banned_terms_in,
    humanize_semantic_id,
    humanize_text,
    unsupported_absence_phrases_in,
)
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

#: Hedging language that must not be attached to an exact, unqualified result.
_UNCERTAINTY_RE = re.compile(
    r"\b(?:may|might|could|possibly|perhaps|approximately|roughly|about|"
    r"cannot be determined|can't be determined|unclear|uncertain|unknown|"
    r"not certain|appears to|seems to|i think)\b",
    re.IGNORECASE,
)


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
    citable_ids = fact_ids | evidence_ids | limitation_ids | part_ids

    # task28 §9: agreement is checked on STABLE identities. A named part that
    # does not exist, or an answered part left undescribed, is a divergence
    # between the text and the authoritative results — not a phrasing question.
    unknown_parts = [p for p in generated.answer_part_ids if p not in part_ids]
    if unknown_parts:
        validation.fail(
            "the answer claims to describe result part(s) that were never "
            f"produced: {', '.join(sorted(unknown_parts)[:3])}"
        )
    answerable_ids = {p.part_id for p in packet.parts if p.is_answerable}
    if len(answerable_ids) > 1 and generated.answer_part_ids:
        missing = answerable_ids - set(generated.answer_part_ids)
        if missing:
            validation.fail(
                "the answer leaves "
                f"{len(missing)} of {len(answerable_ids)} answered part(s) of the "
                "request undescribed"
            )

    for claim in generated.claims:
        if claim.cited_id not in citable_ids:
            validation.fail(f"claim cites unknown id {claim.cited_id!r}")
            continue
        if claim.kind is ClaimKind.FACT and claim.cited_id in fact_ids:
            values = packet.fact_values(claim.cited_id)
            numeric = [v for v in values if isinstance(v, (int, float))]
            if numeric and _numbers_differ(claim.value, numeric) and not _text_matches(
                claim.value, values
            ):
                validation.fail(
                    f"claim value {claim.value!r} does not match fact "
                    f"{claim.cited_id} = {numeric[0]}"
                )

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

    _check_prose(generated, packet, validation)
    return validation


def _check_prose(
    generated: GroundedAnswerV2, packet: AnswerPacketV2, validation: AnswerValidationV2
) -> None:
    """§6: readable, and honest about what is and is not limited."""
    banned = banned_terms_in(generated.answer)
    if banned:
        validation.fail(
            "the answer uses internal pipeline wording: " + ", ".join(banned[:4])
        )

    described = [
        p
        for p in packet.parts
        if not generated.answer_part_ids or p.part_id in generated.answer_part_ids
    ]
    described = described or list(packet.parts)
    has_limitation = any(p.limitations for p in described)
    has_unknown = any(p.unknown_parts for p in described)
    all_exact = bool(described) and all(
        p.status is ResultStatusV2.EXACT and not p.limitations and not p.is_contextual
        for p in described
    )
    answerable = [p for p in described if p.is_answerable and p.result is not None]

    if generated.disclosed_limitation and not (has_limitation or has_unknown):
        validation.fail(
            "the answer discloses a limitation this model's results do not record"
        )
    if all_exact and _UNCERTAINTY_RE.search(generated.answer):
        validation.fail(
            "the answer adds uncertainty to a result that is exact and unqualified"
        )
    withheld = unsupported_absence_phrases_in(generated.answer)
    if withheld and answerable:
        validation.fail(
            "the answer says information was not provided while this model's results "
            f"contain it: {withheld[0]!r}"
        )


def _normalize_number(value: str | float | int) -> float | None:
    try:
        return float(str(value).replace(",", "").replace(" ", ""))
    except ValueError:
        return None


def _numbers_differ(asserted: str, expected: list[float | int]) -> bool:
    parsed = _normalize_number(asserted)
    if parsed is None:
        return True
    return not any(abs(parsed - float(value)) <= 1e-6 for value in expected)


def _text_matches(asserted: str, values: list[Any]) -> bool:
    """True when the asserted text is one of the fact's non-numeric values.

    A grouped extremum names a bucket ("floor 3 (Plan 11_D …)") as well as its
    count; a class breakdown names classes. Citing either is legitimate.
    """
    normalized = _loose(asserted)
    if not normalized:
        return False
    for value in values:
        if isinstance(value, str) and (
            _loose(value) == normalized
            or normalized in _loose(value)
            or _loose(value) in normalized
        ):
            return True
    return False


def _loose(value: Any) -> str:
    return re.sub(r"[^0-9a-z]+", " ", str(value).casefold()).strip()


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
# Deterministic fallback (§12.4, §13) — same plain-language rules as §6
# ---------------------------------------------------------------------------


def build_fallback_answer_v2(packet: AnswerPacketV2) -> str:
    sentences: list[str] = []
    for part in packet.parts:
        line = _fallback_line(part)
        if line:
            sentences.append(line)
    if not sentences:
        return "This model's recorded data cannot answer that question as asked."
    for part in packet.parts:
        for note in part.interpretation_notes[:1]:
            sentences.append(f"({humanize_text(note)})")
        for limitation in part.limitations[:1]:
            sentences.append(_limitation_sentence(limitation["text"]))
    return " ".join(s for s in sentences if s)


def _limitation_sentence(text: str) -> str:
    humanized = humanize_text(text)
    if not humanized:
        return ""
    return humanized[0].upper() + humanized[1:] + ("" if humanized.endswith(".") else ".")


def _subject(part: PartResultV2) -> str:
    subject = humanize_text(part.request_text.strip().rstrip("?.")).strip()
    return subject or "that"


def _fallback_line(part: PartResultV2) -> str | None:
    subject = _subject(part)
    if part.status is ResultStatusV2.UNAVAILABLE:
        reason = humanize_text(part.limitations[0]["text"]) if part.limitations else (
            "this model does not record it"
        )
        return f"This model cannot answer {subject!r}: {reason}."
    if part.status is ResultStatusV2.AMBIGUOUS:
        return f"{subject!r} has more than one reasonable reading in this model."

    result = part.result
    contextual = part.is_contextual
    if isinstance(result, EntitySetResult):
        return _count_sentence(subject, result.matched_cardinality, contextual)
    if isinstance(result, ScalarResult):
        if result.function == "count":
            return _count_sentence(subject, int(result.value or 0), contextual)
        unit = f" {result.unit}" if result.unit else ""
        measured = (
            f"{subject!r}: {result.function} {result.value}{unit}, "
            f"over the {result.covered_cardinality} of "
            f"{result.eligible_cardinality} objects that record a value."
        )
        return measured
    if isinstance(result, DistributionResult):
        if result.top_buckets:
            top = result.top_buckets[0]
            tie = " (tied with another)" if result.tie else ""
            return f"{subject!r}: {top.label or top.key}, with {top.count}{tie}."
        if not result.buckets:
            return f"This model records no values to group for {subject!r}."
        listed = ", ".join(f"{b.label or b.key} ({b.count})" for b in result.buckets[:6])
        return f"{subject!r}: {listed}."
    if isinstance(result, SampleResult):
        if result.sample is None:
            return f"This model contains no object matching {subject!r}."
        name = result.sample.name or humanize_semantic_id(f"cls:{result.sample.ifc_class}")
        detail = (
            " " + "; ".join(f"{k}: {v}" for k, v in list(result.detail.items())[:4])
            if result.detail
            else ""
        )
        return (
            f"One example for {subject!r}: {name}, one of "
            f"{result.eligible_cardinality} such objects.{detail}"
        )
    if isinstance(result, ProfileResult):
        return _profile_sentence(subject, result)
    if isinstance(result, GraphEndpointResult):
        return (
            f"{subject!r}: {result.endpoint_entity_count} connected object(s) through "
            f"{result.relationship_count} recorded relationship(s)."
        )
    if isinstance(result, QualitativeEvidenceResult):
        if not result.excerpts:
            return f"This model records no descriptive text about {subject!r}."
        return f"{subject!r}: based on {len(result.excerpts)} recorded description(s)."
    return None


def _count_sentence(subject: str, count: int, contextual: bool) -> str:
    if contextual:
        return (
            f"This model records {count:,} object(s) of the kind {subject!r} asks about, "
            "but not the specific condition asked for."
        )
    if count == 0:
        return f"This model contains no objects matching {subject!r}."
    return f"{subject!r}: {count:,}."


def _profile_sentence(subject: str, result: ProfileResult) -> str:
    structured = result.structured
    subjects = structured.get("theme_subjects") or {}
    if subjects:
        listed = ", ".join(
            f"{humanize_semantic_id('cls:' + name)} ({count})"
            for name, count in list(subjects.items())[:6]
        )
        return f"For {subject!r}, this model records {listed}."
    top = ", ".join(
        f"{humanize_semantic_id('cls:' + k)} ({v})"
        for k, v in list(structured.get("class_inventory_top", {}).items())[:5]
    )
    floors = structured.get("floors") or {}
    floor_text = (
        f" It has {floors.get('total_bands')} floor level(s), "
        f"{floors.get('occupiable')} of them occupiable."
        if floors
        else ""
    )
    return f"This model contains {structured.get('entity_total'):,} objects: {top}.{floor_text}"
