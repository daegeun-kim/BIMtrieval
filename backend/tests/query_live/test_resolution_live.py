"""Live pre-planner semantic resolution tests (Task 16 §4, §13).

Skips with query_live when the DB is unreachable; the embedding-dependent tests
skip if BGE-M3 cannot load.
"""

from __future__ import annotations

import pytest

from app.query.rag.embedding_service import EmbeddingService, get_embedding_service
from app.query.semantic.resolution import clear_semantic_index_cache, resolve

SID = 1


@pytest.fixture(scope="module")
def emb_getter():
    svc = get_embedding_service()
    try:
        svc.ensure_loaded()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"embedding service not available: {exc}")
    return lambda: svc


def test_resolution_identifies_doors(live_session, emb_getter):
    res = resolve(
        live_session, "how many doors are there?", SID, embedding_service_getter=emb_getter
    )
    assert not res.degraded
    top = res.ontology_candidates[0]
    assert top.ifc_class == "IfcDoor"
    assert top.present_in_model is True
    assert top.exact_model_count == 205


def test_resolution_shows_roof_absence_and_slab_presence(live_session, emb_getter):
    res = resolve(live_session, "show me all the roofs", SID, embedding_service_getter=emb_getter)
    by_class = {c.ifc_class: c for c in res.ontology_candidates}
    # IfcRoof exists in the ontology but is absent in the model — reported exactly.
    assert "IfcRoof" in by_class
    assert by_class["IfcRoof"].present_in_model is False
    assert by_class["IfcRoof"].exact_model_count == 0
    # a present roof-capable class surfaces too (IfcSlab or IfcCovering)
    assert any(
        c.present_in_model and c.exact_model_count > 0 and c.ifc_class in {"IfcSlab", "IfcCovering"}
        for c in res.ontology_candidates
    )
    # and a Type=Roof categorical fact is discoverable among model candidates
    assert any(
        f.observed_value.lower() == "roof" and f.queryable for f in res.model_fact_candidates
    )


def test_resolution_is_threshold_free(live_session, emb_getter):
    """Top-k candidates are returned regardless of a hard similarity cutoff."""
    res = resolve(
        live_session, "xyzzy nonsense unrelated", SID, embedding_service_getter=emb_getter
    )
    assert res.ontology_candidates  # still returns top-k, does not gate on a threshold
    assert not res.degraded


def test_resolution_degrades_when_embedding_unavailable(live_session):
    """Embedding failure degrades truthfully to exact vocabulary; SQL stays usable."""
    clear_semantic_index_cache()
    bad = EmbeddingService(model_name="not-a-real-model/definitely-missing")
    res = resolve(live_session, "how many doors", SID, embedding_service_getter=lambda: bad)
    assert res.degraded is True
    assert res.degraded_reason
    # exact fallback still surfaces present classes with exact counts (name match first)
    assert res.model_class_candidates
    assert res.model_class_candidates[0].ifc_class == "IfcDoor"
