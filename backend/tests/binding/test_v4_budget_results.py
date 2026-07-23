"""task26 §17.5 (budget) + §12 (result variants, answer validation) — offline."""

from __future__ import annotations

from app.llm.budget import RequestBudget
from app.llm.schemas_v2 import ClaimKind, GroundedAnswerV2, GroundedClaim
from app.query.binding.answer_validation_v2 import (
    build_fallback_answer_v2,
    validate_answer_v2,
)
from app.query.binding.packet_v2 import build_answer_packet_v2
from app.query.binding.results_v2 import (
    DistributionBucketV2,
    DistributionResult,
    EntitySetResult,
    PartResultV2,
    ResultExampleV2,
    ResultStatusV2,
    SampleResult,
)


# ---------------------------------------------------------------------------
# Budget (§9.5)
# ---------------------------------------------------------------------------


class _Cost:
    def __init__(self, usd):
        self.usd = usd
        self.unavailable_reason = None if usd is not None else "unknown model"


class _Usage:
    def __init__(self, usd):
        self._usd = usd

    def cost(self):
        return _Cost(self._usd)


def test_correction_skipped_when_it_would_exceed_budget():
    budget = RequestBudget(limit_usd=0.03)
    budget.track_actual("binder", _Usage(0.02))
    # correction 0.008 + answer reserve 0.01 -> 0.038 > 0.03
    assert budget.allows_correction(0.008, 0.01) is False


def test_correction_allowed_within_budget():
    budget = RequestBudget(limit_usd=0.03)
    budget.track_actual("binder", _Usage(0.005))
    assert budget.allows_correction(0.005, 0.01) is True


def test_unknown_pricing_never_reads_as_zero():
    budget = RequestBudget(limit_usd=0.03)
    budget.track_actual("binder", _Usage(0.005))
    # An unpriceable estimate must NOT be treated as affordable.
    assert budget.allows_correction(None, 0.01) is False


def test_actual_cost_accumulates():
    budget = RequestBudget()
    budget.track_actual("binder", _Usage(0.004))
    budget.track_actual("grounded_answerer", _Usage(0.006))
    assert abs(budget.spent_usd - 0.010) < 1e-9


# ---------------------------------------------------------------------------
# Result variants keep cardinalities distinct (§12.1)
# ---------------------------------------------------------------------------


def test_sample_result_answer_cardinality_is_one_not_eligible():
    sample = SampleResult(
        eligible_cardinality=551,
        sample=ResultExampleV2(entity_id=1, global_id="g", ifc_class="IfcDoor"),
    )
    assert sample.eligible_cardinality == 551
    assert sample.answer_cardinality == 1
    facts = sample.facts("P1")
    eligible = next(f for f in facts if f["fact_id"] == "P1:eligible")
    assert eligible["value"] == 551


def test_distribution_reports_top_bucket_not_the_global_total():
    dist = DistributionResult(
        base_cardinality=551,
        covered_cardinality=551,
        buckets=[
            DistributionBucketV2(key="b3", count=142, label="floor 3"),
            DistributionBucketV2(key="b2", count=125, label="floor 2"),
        ],
        top_buckets=[DistributionBucketV2(key="b3", count=142, label="floor 3")],
    )
    facts = dist.facts("P1")
    top = next(f for f in facts if f["kind"] == "extremum")
    assert top["count"] == 142
    assert top["key"] == "floor 3"


# ---------------------------------------------------------------------------
# Answer validation + fallback (§12.4)
# ---------------------------------------------------------------------------


def _entity_part(count):
    part = PartResultV2(
        part_id="P1",
        request_text="how many walls",
        result_kind="entity_set",
        status=ResultStatusV2.EXACT,
        result=EntitySetResult(scanned_cardinality=count, matched_cardinality=count),
    )
    part.allowed_terms = ["IfcWall", "wall"]
    return part


def test_a_correct_claim_passes():
    packet = build_answer_packet_v2("how many walls", [_entity_part(880)])
    generated = GroundedAnswerV2(
        answer="There are 880 walls.",
        claims=[GroundedClaim(kind=ClaimKind.FACT, cited_id="P1:matched", value="880")],
    )
    assert validate_answer_v2(generated, packet).ok


def test_a_wrong_number_is_rejected():
    packet = build_answer_packet_v2("how many walls", [_entity_part(880)])
    generated = GroundedAnswerV2(
        answer="There are 1981 walls.",
        claims=[GroundedClaim(kind=ClaimKind.FACT, cited_id="P1:matched", value="1981")],
    )
    assert not validate_answer_v2(generated, packet).ok


def test_an_uncited_large_number_is_rejected():
    packet = build_answer_packet_v2("how many walls", [_entity_part(880)])
    generated = GroundedAnswerV2(answer="There are about 5000 walls.", claims=[])
    assert not validate_answer_v2(generated, packet).ok


def test_general_knowledge_is_rejected():
    packet = build_answer_packet_v2("how many walls", [_entity_part(880)])
    generated = GroundedAnswerV2(
        answer="880 walls.",
        claims=[GroundedClaim(kind=ClaimKind.FACT, cited_id="P1:matched", value="880")],
        used_general_knowledge=True,
    )
    assert not validate_answer_v2(generated, packet).ok


def test_fallback_summarizes_results_deterministically():
    packet = build_answer_packet_v2("how many walls", [_entity_part(880)])
    fallback = build_fallback_answer_v2(packet)
    assert "880" in fallback


def test_context_only_result_is_labeled_in_fallback():
    part = _entity_part(6)
    part.is_contextual = True
    part.context_reason = "accessibility is not recorded"
    part.request_text = "accessible ramps"
    packet = build_answer_packet_v2("accessible ramps?", [part])
    fallback = build_fallback_answer_v2(packet)
    assert "Context only" in fallback
