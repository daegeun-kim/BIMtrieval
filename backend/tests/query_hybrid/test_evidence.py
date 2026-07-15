"""Evidence bounds, deterministic overflow, and answer-payload safety (spec_v005 §10, §11)."""

from __future__ import annotations

from app.api.schemas.response import PrimaryEntityResult, RelationshipResult
from app.config.settings import Settings
from app.query.hybrid.evidence import apply_bounds, build_answer_payload
from app.query.hybrid.schemas import EvidencePackage, RagInternalItem
from app.shared.types import AnswerBasis


def _entities(n: int) -> list[PrimaryEntityResult]:
    return [
        PrimaryEntityResult(entity_id=i, global_id=f"g{i}", ifc_class="IfcDoor", name=f"d{i}")
        for i in range(n)
    ]


def _pkg(**kw) -> EvidencePackage:
    return EvidencePackage(question="q", route="sql", scope="active_model", source_model_id=1, **kw)


def test_primary_bounded_and_overflow_summarized():
    settings = Settings(max_primary_entities=50)
    pkg = _pkg(primary_entities=_entities(120))
    apply_bounds(pkg, settings)
    assert len(pkg.primary_entities) == 50
    assert pkg.exact_totals["primary_entities"] == 120
    assert any("120 primary matches" in s for s in pkg.overflow_summaries)


def test_relationships_bounded():
    settings = Settings(max_relationships=20)
    rels = [
        RelationshipResult(relationship_id=i, global_id=f"r{i}", ifc_class="IfcRelAggregates")
        for i in range(35)
    ]
    pkg = _pkg(relationships=rels)
    apply_bounds(pkg, settings)
    assert len(pkg.relationships) == 20
    assert pkg.exact_totals["relationships"] == 35


def test_answer_payload_excludes_internal_rag_scores():
    pkg = _pkg(
        primary_entities=_entities(2),
        rag_internal=[RagInternalItem("entity", 1, 0.87, 1)],
        answer_basis=AnswerBasis.SEMANTIC_RETRIEVAL,
    )
    payload = build_answer_payload(pkg)
    text = str(payload)
    assert "0.87" not in text
    assert "rag_internal" not in payload
    assert "similarity" not in text
    # compact entity summaries are present
    assert payload["primary_entities"][0]["ifc_class"] == "IfcDoor"


def test_answer_payload_carries_totals_and_provenance():
    pkg = _pkg(
        answer_basis=AnswerBasis.HYBRID_EVIDENCE,
        combination="intersection",
        exact_totals={"primary_matches": 3},
        conflicts=["c1"],
        missing_coverage=["m1"],
    )
    payload = build_answer_payload(pkg)
    assert payload["answer_basis"] == "hybrid_evidence"
    assert payload["combination"] == "intersection"
    assert payload["exact_totals"]["primary_matches"] == 3
    assert payload["conflicts"] == ["c1"]
    assert payload["missing_coverage"] == ["m1"]
