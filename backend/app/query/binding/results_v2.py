"""Operation-specific result variants (task26 §12.1).

Replaces the overloaded `exact_total` with discriminated results that expose
ONLY meaningful cardinalities: scanned, matched/answer, covered, eligible,
sample, and viewer counts are different numbers and never stand in for each
other. Every variant knows how to serialize itself into the answer packet with
stable fact ids.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

__all__ = [
    "ResultStatusV2",
    "ResultExampleV2",
    "EntitySetResult",
    "ScalarResult",
    "DistributionBucketV2",
    "DistributionResult",
    "SampleResult",
    "ProfileResult",
    "EvidenceExcerpt",
    "QualitativeEvidenceResult",
    "GraphEndpointResult",
    "PartResultV2",
]


class ResultStatusV2(str, Enum):
    EXACT = "exact"
    ZERO = "zero"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True)
class ResultExampleV2:
    entity_id: int
    global_id: str
    ifc_class: str
    name: str | None = None
    storey_name: str | None = None

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"ifc_class": self.ifc_class}
        if self.name:
            payload["name"] = self.name
        if self.storey_name:
            payload["storey"] = self.storey_name
        return payload


@dataclass
class EntitySetResult:
    scanned_cardinality: int = 0
    matched_cardinality: int = 0
    class_breakdown: dict[str, int] = field(default_factory=dict)

    def facts(self, part_id: str) -> list[dict[str, Any]]:
        facts = [
            {
                "fact_id": f"{part_id}:matched",
                "kind": "count",
                "value": self.matched_cardinality,
            }
        ]
        if self.class_breakdown and len(self.class_breakdown) > 1:
            facts.append(
                {
                    "fact_id": f"{part_id}:by_class",
                    "kind": "class_breakdown",
                    "value": dict(self.class_breakdown),
                }
            )
        return facts


@dataclass
class ScalarResult:
    function: str = "count"
    value: float | int | None = None
    unit: str | None = None
    covered_cardinality: int = 0
    eligible_cardinality: int = 0

    def facts(self, part_id: str) -> list[dict[str, Any]]:
        return [
            {
                "fact_id": f"{part_id}:{self.function}",
                "kind": "scalar",
                "function": self.function,
                "value": self.value,
                "unit": self.unit,
                "covered": self.covered_cardinality,
                "eligible": self.eligible_cardinality,
            }
        ]


@dataclass(frozen=True)
class DistributionBucketV2:
    key: str
    count: int
    value: float | None = None
    #: For floor grouping: the band's occupiable ordinal / classification.
    label: str | None = None


@dataclass
class DistributionResult:
    base_cardinality: int = 0
    covered_cardinality: int = 0
    missing_count: int = 0
    buckets: list[DistributionBucketV2] = field(default_factory=list)
    #: Set when order+limit selected the top bucket(s) (grouped argmax).
    top_buckets: list[DistributionBucketV2] = field(default_factory=list)
    tie: bool = False

    def facts(self, part_id: str) -> list[dict[str, Any]]:
        facts: list[dict[str, Any]] = [
            {
                "fact_id": f"{part_id}:distribution",
                "kind": "distribution",
                "base": self.base_cardinality,
                "covered": self.covered_cardinality,
                "missing": self.missing_count,
                "buckets": [
                    {"key": b.label or b.key, "count": b.count}
                    for b in self.buckets[:24]
                ],
            }
        ]
        for index, bucket in enumerate(self.top_buckets):
            facts.append(
                {
                    "fact_id": f"{part_id}:top{index + 1}",
                    "kind": "extremum",
                    "key": bucket.label or bucket.key,
                    "count": bucket.count,
                    "tie": self.tie,
                }
            )
        return facts


@dataclass
class SampleResult:
    eligible_cardinality: int = 0
    sample: ResultExampleV2 | None = None
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def answer_cardinality(self) -> int:
        return 1 if self.sample is not None else 0

    def facts(self, part_id: str) -> list[dict[str, Any]]:
        facts = [
            {
                "fact_id": f"{part_id}:eligible",
                "kind": "count",
                "value": self.eligible_cardinality,
                "meaning": "eligible objects the sample was drawn from",
            }
        ]
        if self.sample is not None:
            facts.append(
                {
                    "fact_id": f"{part_id}:sample",
                    "kind": "sample",
                    "value": self.sample.to_payload() | self.detail,
                }
            )
        return facts


@dataclass
class ProfileResult:
    structured: dict[str, Any] = field(default_factory=dict)
    evidence_ids: list[str] = field(default_factory=list)

    def facts(self, part_id: str) -> list[dict[str, Any]]:
        return [
            {"fact_id": f"{part_id}:profile:{key}", "kind": "profile_fact", "value": value}
            for key, value in self.structured.items()
        ]


@dataclass(frozen=True)
class EvidenceExcerpt:
    evidence_id: str
    source_kind: str
    similarity: float
    excerpt: str
    text_truncated: bool = False
    slice: str = "primary"  # primary | diversity


@dataclass
class QualitativeEvidenceResult:
    scope_cardinality: int = 0
    excerpts: list[EvidenceExcerpt] = field(default_factory=list)
    scope_kind: str = "structured"  # structured | unscoped_fallback
    truncated_evidence: bool = False

    def facts(self, part_id: str) -> list[dict[str, Any]]:
        return [
            {
                "fact_id": f"{part_id}:evidence_scope",
                "kind": "count",
                "value": self.scope_cardinality,
                "meaning": "objects in the structured scope the evidence describes",
            }
        ]


@dataclass
class GraphEndpointResult:
    seed_cardinality: int = 0
    traversed_cardinality: int = 0
    relationship_count: int = 0
    endpoint_fact_count: int = 0
    endpoint_entity_count: int = 0
    complete: bool = True
    endpoints: list[ResultExampleV2] = field(default_factory=list)
    path_labels: list[str] = field(default_factory=list)

    def facts(self, part_id: str) -> list[dict[str, Any]]:
        return [
            {
                "fact_id": f"{part_id}:endpoints",
                "kind": "graph",
                "value": self.endpoint_entity_count,
                "seeds": self.seed_cardinality,
                "traversed": self.traversed_cardinality,
                "relationships": self.relationship_count,
                "complete": self.complete,
                "paths": self.path_labels[:4],
            }
        ]


@dataclass
class PartResultV2:
    """One executed answer part: status + its typed result + set selectors."""

    part_id: str
    request_text: str
    result_kind: str
    status: ResultStatusV2 = ResultStatusV2.UNAVAILABLE
    result: Any = None
    #: Bounded examples for grounding/citation.
    examples: list[ResultExampleV2] = field(default_factory=list)
    #: What the viewer should show, per the typed policy (ids resolved later).
    viewer_policy: str = "none"
    viewer_where: Any = None
    viewer_sample: ResultExampleV2 | None = None
    #: Requested vs contextual distinction (§12.2).
    is_contextual: bool = False
    context_reason: str | None = None
    known_parts: list[str] = field(default_factory=list)
    unknown_parts: list[str] = field(default_factory=list)
    limitations: list[dict[str, str]] = field(default_factory=list)
    interpretation_notes: list[str] = field(default_factory=list)
    coverage_complete: bool = True
    coverage_reasons: list[str] = field(default_factory=list)
    evidence: QualitativeEvidenceResult | None = None
    statement_count: int = 0
    duration_ms: float = 0.0
    #: Terminology the final answer may use, derived from selected concepts.
    allowed_terms: list[str] = field(default_factory=list)
    #: Additional structured facts (e.g. projection value distributions).
    extra_facts: list[dict[str, Any]] = field(default_factory=list)

    def add_limitation(self, code: str, text: str) -> str:
        limitation_id = f"{self.part_id}:lim{len(self.limitations) + 1}"
        self.limitations.append({"limitation_id": limitation_id, "code": code, "text": text})
        return limitation_id

    @property
    def is_answerable(self) -> bool:
        return self.status in (ResultStatusV2.EXACT, ResultStatusV2.ZERO, ResultStatusV2.PARTIAL)

    def facts(self) -> list[dict[str, Any]]:
        facts = self.result.facts(self.part_id) if self.result is not None else []
        if self.evidence is not None and self.result is not self.evidence:
            facts.extend(self.evidence.facts(self.part_id))
        facts.extend(self.extra_facts)
        return facts

    def to_packet_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "part_id": self.part_id,
            "request": self.request_text,
            "result_kind": self.result_kind,
            "status": self.status.value,
            "facts": self.facts(),
        }
        if self.is_contextual:
            payload["contextual_only"] = True
            payload["context_reason"] = self.context_reason
        if self.known_parts:
            payload["known"] = self.known_parts[:6]
        if self.unknown_parts:
            payload["unknown"] = self.unknown_parts[:6]
        if self.limitations:
            payload["limitations"] = self.limitations[:6]
        if self.interpretation_notes:
            payload["interpretation"] = self.interpretation_notes[:4]
        if not self.coverage_complete:
            payload["coverage_incomplete"] = self.coverage_reasons[:4]
        if self.examples:
            payload["examples"] = [e.to_payload() for e in self.examples[:5]]
        if self.evidence is not None and self.evidence.excerpts:
            payload["evidence"] = [
                {
                    "evidence_id": e.evidence_id,
                    "similarity": round(e.similarity, 3),
                    "excerpt": e.excerpt,
                    "truncated": e.text_truncated,
                    "slice": e.slice,
                }
                for e in self.evidence.excerpts[:12]
            ]
        return payload
