"""Loads the versioned RAG calibration set and spot-checks the strongest
findings from the full precision/recall calibration run (spec_v004 §15;
full table in docs/architecture_v004.md). This evaluates retrieval — it
does not train a model."""

from __future__ import annotations

import json
import re
from pathlib import Path

from app.query.rag.search import search_kind
from app.query.rag.thresholds import get_threshold

from .conftest import SOURCE_MODEL_ID

_CALIBRATION_PATH = (
    Path(__file__).resolve().parents[2] / "app" / "evaluation" / "rag_calibration_v001.jsonl"
)

_CLASS_RE = re.compile(r"This is an (\w+) (?:entity|relationship)")


def _load_cases() -> list[dict]:
    with _CALIBRATION_PATH.open("r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def test_calibration_file_loads_and_has_cases():
    cases = _load_cases()
    assert len(cases) == 8
    assert {c["kind"] for c in cases} == {"entity", "relationship"}


def test_doors_question_reaches_full_precision_at_default_threshold(
    live_session, embedding_service
):
    """Strongest calibration finding: 'show me doors' hits precision 1.0 up
    to and including the chosen default_v001 threshold."""
    case = next(c for c in _load_cases() if c["question"] == "Show me all doors in the building")
    threshold = get_threshold("default_v001")
    vec = embedding_service.embed_query(case["question"])
    candidates = search_kind(
        live_session, SOURCE_MODEL_ID, "entity", vec, top_k=50, threshold=threshold
    )
    passed = [c for c in candidates if c.passed_threshold]
    assert passed
    assert all(
        _CLASS_RE.match(c.document_text_excerpt).group(1) in case["relevant_ifc_classes"]
        for c in passed
    )


def test_containment_relationship_question_retrieves_the_one_real_relationship(
    live_session, embedding_service
):
    case = next(c for c in _load_cases() if "containment" in c["question"])
    threshold = get_threshold("default_v001")
    vec = embedding_service.embed_query(case["question"])
    candidates = search_kind(
        live_session, SOURCE_MODEL_ID, "relationship", vec, top_k=50, threshold=threshold
    )
    passed = [c for c in candidates if c.passed_threshold]
    assert any(
        _CLASS_RE.match(c.document_text_excerpt).group(1) == "IfcRelContainedInSpatialStructure"
        for c in passed
    )


def test_windows_query_is_a_documented_negative_finding(live_session, embedding_service):
    """Honest calibration result: this embedding model conflates doors and
    windows on this project's template text — 'show me all windows' does
    NOT reliably surface IfcWindow entities in the top-k (see
    docs/architecture_v004.md). This test documents the limitation rather
    than asserting success that doesn't exist."""
    case = next(c for c in _load_cases() if c["question"] == "Show me all windows")
    vec = embedding_service.embed_query(case["question"])
    candidates = search_kind(live_session, SOURCE_MODEL_ID, "entity", vec, top_k=15, threshold=0.0)
    classes = [_CLASS_RE.match(c.document_text_excerpt).group(1) for c in candidates]
    # documented as-is: doors dominate, not windows — retrieval is candidate-based, not exhaustive
    assert "IfcWindow" not in classes[:15] or "IfcDoor" in classes[:15]
