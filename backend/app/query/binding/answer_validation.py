"""Deterministic validation of the final answer (Task 24 §8.3).

Runs after LLM call 2 and before the response leaves the backend. It checks the
model's structured claims against the answer packet it was given:

- every referenced answer part and fact id exists;
- structured numeric claims match the authoritative values and units;
- zero / unavailable / partial status is preserved;
- any named class, property, material or relationship endpoint appears in the
  packet;
- the model did not claim complete coverage from bounded RAG evidence;
- viewer selection remains backend-owned.

On failure there is **no second answer call**. §8.3 is explicit: "Do not call
the LLM again after validation failure. Return a concise safe fallback assembled
from the authoritative answer-part results and record the validation failure."
That is what `build_fallback_answer` does — it composes prose from the same
adjudicated results the model was given, so the user still gets the real numbers
even when the model's phrasing is rejected.

The fallback is an exceptional grounding safeguard, not a separate answer path
chosen by query type: LLM call 2 still runs for every answered question.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from app.llm.schemas import GroundedAnswer
from app.query.binding.evidence import AnswerPartResult, ResultStatus
from app.query.binding.packet import AnswerPacket

__all__ = [
    "AnswerValidation",
    "validate_answer",
    "build_fallback_answer",
]

#: Phrases asserting completeness. Claiming any of these while the only
#: supporting evidence is bounded semantic ranking is a §8.3 violation.
_COMPLETENESS_CLAIMS = (
    "all of the",
    "every ",
    "in total",
    "complete list",
    "exhaustive",
    "the full set",
    "none other",
)

_NUMBER_RE = re.compile(r"-?\d+(?:[.,]\d+)?")


@dataclass
class AnswerValidation:
    ok: bool = True
    failures: list[str] = field(default_factory=list)

    def fail(self, reason: str) -> None:
        self.ok = False
        self.failures.append(reason)


def _normalize(text: str | None) -> str:
    if not text:
        return ""
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return re.sub(r"[^0-9a-z]+", " ", stripped.casefold()).strip()


def _as_number(value) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    match = _NUMBER_RE.search(str(value or ""))
    if match is None:
        return None
    try:
        return float(match.group(0).replace(",", "."))
    except ValueError:  # pragma: no cover - regex constrains the shape
        return None


def validate_answer(
    answer: GroundedAnswer,
    packet: AnswerPacket,
    results: list[AnswerPartResult],
) -> AnswerValidation:
    """Validate a grounded answer against the packet that produced it (§8.3)."""
    validation = AnswerValidation()
    by_part = {r.part_id: r for r in results}

    _check_part_references(answer, packet, validation)
    _check_claims(answer, packet, validation)
    _check_status_preserved(answer, by_part, validation)
    _check_no_unfounded_completeness(answer, results, validation)
    return validation


def _check_part_references(
    answer: GroundedAnswer, packet: AnswerPacket, validation: AnswerValidation
) -> None:
    known = packet.part_ids()
    for part_id in answer.answer_part_ids:
        if part_id not in known:
            validation.fail(f"answer referenced unknown answer part {part_id!r}")


def _check_claims(
    answer: GroundedAnswer, packet: AnswerPacket, validation: AnswerValidation
) -> None:
    """Each structured claim must cite a real fact and restate it faithfully."""
    named_in_packet = _packet_names(packet)

    for claim in answer.structured_claims:
        fact = packet.fact(claim.fact_id)
        if fact is None:
            validation.fail(f"answer cited unknown fact id {claim.fact_id!r}")
            continue

        expected = _as_number(fact.value)
        asserted = _as_number(claim.value)
        if expected is not None:
            if asserted is None:
                # The model filled `value` with a label rather than the number
                # (e.g. "doors"). That is a schema misuse, not a fabrication —
                # so fall back to checking the ANSWER TEXT, which is what the
                # user actually reads. Rejecting a correct answer over field
                # hygiene would send a good result to the fallback path.
                if not _text_states_value(answer.answer, expected):
                    validation.fail(
                        f"claim on {claim.fact_id!r} carries no number and the answer text does "
                        f"not state the authoritative value {fact.value!r}"
                    )
            elif abs(asserted - expected) > 1e-6:
                # The single most important check: a number the model changed.
                validation.fail(
                    f"claim on {claim.fact_id!r} states {claim.value!r} but the authoritative "
                    f"value is {fact.value!r}"
                )
        elif _normalize(claim.value) != _normalize(str(fact.value)):
            validation.fail(
                f"claim on {claim.fact_id!r} states {claim.value!r} but the authoritative "
                f"value is {fact.value!r}"
            )

        if fact.unit and claim.unit and _normalize(claim.unit) != _normalize(fact.unit):
            validation.fail(
                f"claim on {claim.fact_id!r} states unit {claim.unit!r} but the authoritative "
                f"unit is {fact.unit!r}"
            )

        for name in claim.named_entities:
            if _normalize(name) not in named_in_packet:
                validation.fail(
                    f"answer named {name!r}, which does not appear in the supplied results"
                )


def _text_states_value(answer_text: str, expected: float) -> bool:
    """True when the answer prose actually states the authoritative number."""
    rendered = f"{int(expected)}" if float(expected).is_integer() else f"{expected:g}"
    return any(
        token == rendered for token in _NUMBER_RE.findall(answer_text or "")
    ) or rendered in (answer_text or "")


def _packet_names(packet: AnswerPacket) -> set[str]:
    """Every class/value/name the packet actually contains, normalized."""
    names: set[str] = set()
    for part in packet.parts:
        for example in part.get("examples", []):
            names.update(_normalize(v) for v in example.values() if isinstance(v, str))
        for row in part.get("by_class", []):
            names.add(_normalize(row.get("ifc_class")))
        for row in part.get("distribution", []):
            if row.get("value"):
                names.add(_normalize(row["value"]))
        connected = part.get("connected") or {}
        for example in connected.get("examples", []):
            names.update(_normalize(v) for v in example.values() if isinstance(v, str))
        if part.get("interpreted_as"):
            names.update(_normalize(part["interpreted_as"]).split())
    names.discard("")
    return names


def _check_status_preserved(
    answer: GroundedAnswer,
    by_part: dict[str, AnswerPartResult],
    validation: AnswerValidation,
) -> None:
    """zero/unavailable/partial must survive into the prose (§6, §8.1).

    Checked by looking for the two specific inversions that matter: reporting a
    zero count for data that is merely unavailable, and describing a genuine
    zero as missing information. Both mislead in opposite directions.
    """
    text = _normalize(answer.answer)
    if not text:
        return

    for part_id in answer.answer_part_ids:
        result = by_part.get(part_id)
        if result is None:
            continue

        if result.status is ResultStatus.UNAVAILABLE:
            # Claiming a number for a part whose data cannot be established.
            claimed_zero = any(
                claim.fact_id.startswith(f"{part_id}.") and _as_number(claim.value) == 0
                for claim in answer.structured_claims
            )
            if claimed_zero:
                validation.fail(
                    f"part {part_id} is unavailable, but the answer reported it as a count "
                    "of zero; absent data is not a zero value"
                )

        if result.status is ResultStatus.ZERO and _mentions_unavailability(text):
            # Softer: a zero part described as "not recorded"/"no data".
            validation.fail(
                f"part {part_id} is a genuine zero, but the answer described the information "
                "as unavailable"
            )


_UNAVAILABLE_PHRASES = (
    "not recorded",
    "no data",
    "not available",
    "cannot be determined",
    "does not record",
    "no information",
)


def _mentions_unavailability(normalized_text: str) -> bool:
    return any(_normalize(phrase) in normalized_text for phrase in _UNAVAILABLE_PHRASES)


def _check_no_unfounded_completeness(
    answer: GroundedAnswer, results: list[AnswerPartResult], validation: AnswerValidation
) -> None:
    """§8.3: the model must not claim complete coverage from bounded RAG evidence."""
    rag_only = [r for r in results if r.rag_candidate_count is not None and r.exact_total is None]
    if not rag_only:
        return
    text = _normalize(answer.answer)
    for phrase in _COMPLETENESS_CLAIMS:
        if _normalize(phrase) in text:
            validation.fail(
                "the answer claimed complete coverage, but the supporting evidence was "
                "bounded semantic ranking rather than a complete query"
            )
            return


# ---------------------------------------------------------------------------
# Safe fallback (§8.3)
# ---------------------------------------------------------------------------


def build_fallback_answer(results: list[AnswerPartResult]) -> str:
    """Compose a safe answer from the authoritative results alone.

    Used when the model's answer fails validation. It fabricates nothing: every
    sentence restates one adjudicated answer-part result, using the same
    statuses and numbers the model was given and failed to reproduce faithfully.
    """
    if not results:
        return "I couldn't produce a grounded answer for that question. Could you rephrase it?"

    lines: list[str] = []
    for result in results:
        lines.append(_fallback_line(result))
    preface = (
        "Here are the results directly from the model"
        if len(lines) > 1
        else "Here is the result directly from the model"
    )
    return preface + ":\n" + "\n".join(f"- {line}" for line in lines)


def _fallback_line(result: AnswerPartResult) -> str:
    request = result.request_text.rstrip("?.")
    if result.status is ResultStatus.EXACT:
        if result.aggregate is not None and result.aggregate.value is not None:
            unit = f" {result.aggregate.unit}" if result.aggregate.unit else ""
            return f"{request}: {result.aggregate.value:g}{unit}"
        if result.operation == "relationship":
            return f"{request}: {len(result.graph_endpoints)} connected object(s) found"
        return f"{request}: {result.exact_total}"
    if result.status is ResultStatus.ZERO:
        return f"{request}: none found in this model"
    if result.status is ResultStatus.UNAVAILABLE:
        reason = result.limitation or "this cannot be determined from the model"
        return f"{request}: {reason}"
    if result.status is ResultStatus.PARTIAL:
        known = "; ".join(result.known_parts) or "partially answered"
        unknown = "; ".join(result.unknown_parts)
        return f"{request}: {known}" + (f" (not established: {unknown})" if unknown else "")
    return f"{request}: needs clarification"
