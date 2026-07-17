"""Pre-planner semantic resolution unit tests (Task 16 §4, §13).

No DB / no model load — covers the pure helpers and the advisory contract.
"""

from __future__ import annotations

import numpy as np

from app.query.semantic.resolution import (
    ModelFactCandidate,
    OntologyCandidate,
    SemanticResolution,
    _build_query_text,
    _cosine_topk,
    _degraded_fallback,
)
from app.query.semantic.vocabulary.profiles import ClassProfile, ModelVocabulary


def _normed(rows):
    m = np.asarray(rows, dtype=np.float32)
    return m / np.linalg.norm(m, axis=1, keepdims=True)


def test_cosine_topk_orders_by_similarity():
    matrix = _normed([[1.0, 0.0], [0.0, 1.0], [0.9, 0.1]])
    q = _normed([[1.0, 0.05]])[0]
    hits = _cosine_topk(matrix, q, 3)
    assert [i for i, _ in hits] == [0, 2, 1]  # row 0 closest, row 1 farthest
    assert hits[0][1] >= hits[1][1] >= hits[2][1]


def test_cosine_topk_empty_matrix_is_safe():
    assert _cosine_topk(np.zeros((0, 2), dtype=np.float32), np.array([1.0, 0.0]), 5) == []


def test_build_query_text_includes_selection_and_last_user_turn():
    text = _build_query_text(
        "show these",
        history=[{"role": "user", "content": "earlier question about roofs"}],
        selection=[{"ifc_class": "IfcSlab"}],
    )
    assert "show these" in text
    assert "IfcSlab" in text
    assert "roofs" in text


def test_to_planner_context_hides_scores_and_bounds_excerpts():
    res = SemanticResolution(question="q", source_model_id=1)
    res.ontology_candidates.append(
        OntologyCandidate("IfcRoof", "IFC2X3", False, 0, False, ["ROOF"], "x" * 999, 0.87)
    )
    res.model_fact_candidates.append(
        ModelFactCandidate(
            "IfcCovering",
            "property_value",
            "property",
            "PS",
            "Type",
            "Roof",
            42,
            True,
            "y" * 999,
            0.71,
        )
    )
    ctx = res.to_planner_context(max_chars=100)
    onto = ctx["ontology_candidates"][0]
    assert "similarity" not in onto and "score" not in onto
    assert onto["present_in_model"] is False and onto["exact_model_count"] == 0
    assert len(onto["profile_excerpt"]) <= 100
    fact = ctx["model_fact_candidates"][0]
    assert fact["observed_value"] == "Roof" and fact["queryable"] is True
    assert "similarity" not in fact


def test_degraded_fallback_matches_present_class_names():
    res = SemanticResolution(question="how many doors are there", source_model_id=1)
    vocab = ModelVocabulary(
        source_model_id=1,
        file_fingerprint="fp",
        extraction_version="v001",
        profile_builder_version="v001",
        ifc_schema="IFC2X3",
        classes=[
            ClassProfile(ifc_class="IfcDoor", kind="entity", instance_count=205),
            ClassProfile(ifc_class="IfcWall", kind="entity", instance_count=648),
        ],
    )
    _degraded_fallback(res, vocab)
    # exact name match ('door') ranks first even without embeddings
    assert res.model_class_candidates[0].ifc_class == "IfcDoor"
    assert res.model_class_candidates[0].exact_model_count == 205
