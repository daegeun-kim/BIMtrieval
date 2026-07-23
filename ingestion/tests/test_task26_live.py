"""Live-database assertions for task26 spatial membership and manifest v002.

Self-skipping when PostgreSQL is unreachable (same convention as
`test_semantic_manifest_live.py`). Read-only.

The explicit model-numbered checks are the §17.2 live assertions the task
requires; everything else is an invariant over whatever models are imported.
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from bim_rag.config import get_db_url, get_model_semantics_root


def _engine():
    try:
        engine = create_engine(get_db_url())
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return engine
    except Exception:
        return None


_ENGINE = _engine()

pytestmark = pytest.mark.skipif(_ENGINE is None, reason="live database not reachable")


def _model_ids() -> list[int]:
    with Session(_ENGINE) as session:
        return [r[0] for r in session.execute(text("SELECT id FROM ifc_source_models ORDER BY id"))]


MODEL_IDS = _model_ids() if _ENGINE is not None else []


# ---------------------------------------------------------------------------
# §17.2 explicit live assertions
# ---------------------------------------------------------------------------


def _space_membership_counts(sid: int) -> tuple[int, int]:
    with Session(_ENGINE) as session:
        resolved = session.execute(
            text(
                "SELECT count(*) FROM ifc_entities e WHERE e.source_model_id = :sid "
                "AND e.ifc_class = 'IfcSpace' AND EXISTS ("
                "SELECT 1 FROM entity_spatial_memberships m "
                "WHERE m.source_model_id = e.source_model_id AND m.entity_id = e.id)"
            ),
            {"sid": sid},
        ).scalar()
        total = session.execute(
            text(
                "SELECT count(*) FROM ifc_entities WHERE source_model_id = :sid "
                "AND ifc_class = 'IfcSpace'"
            ),
            {"sid": sid},
        ).scalar()
    return int(resolved or 0), int(total or 0)


@pytest.mark.skipif(2 not in MODEL_IDS, reason="model 2 not imported")
def test_all_model2_spaces_resolve_through_effective_membership():
    resolved, total = _space_membership_counts(2)
    assert total == 778
    assert resolved == total


@pytest.mark.skipif(3 not in MODEL_IDS, reason="model 3 not imported")
def test_all_model3_spaces_resolve_through_effective_membership():
    resolved, total = _space_membership_counts(3)
    assert total == 187
    assert resolved == total


@pytest.mark.skipif(1 not in MODEL_IDS, reason="model 1 not imported")
def test_model1_remains_single_storey():
    manifest = _load_manifest(1)
    floors = manifest["content"]["derived_floors"]
    assert len(floors["bands"]) == 1
    assert floors["bands"][0]["classification"] == "occupiable"


@pytest.mark.skipif(4 not in MODEL_IDS, reason="model 4 not imported")
def test_model4_does_not_invent_spaces_and_flags_roof_uncertainty():
    resolved, total = _space_membership_counts(4)
    assert total == 0
    assert resolved == 0
    manifest = _load_manifest(4)
    bands = manifest["content"]["derived_floors"]["bands"]
    classifications = {b["classification"] for b in bands}
    # The roof-named-but-populated boundary stays honest.
    assert "uncertain" in classifications or "non_occupiable_reference" in classifications
    assert any(b["classification"] == "occupiable" for b in bands)


# ---------------------------------------------------------------------------
# Invariants over every imported model
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module", params=MODEL_IDS)
def model_id(request):
    return request.param


def _load_manifest(sid: int) -> dict:
    from bim_rag.semantic_manifest.writer_v002 import manifest_path_v002

    with Session(_ENGINE) as session:
        fingerprint = session.execute(
            text("SELECT file_fingerprint FROM ifc_source_models WHERE id = :sid"),
            {"sid": sid},
        ).scalar()
    path = manifest_path_v002(get_model_semantics_root(), sid, fingerprint)
    return json.loads(path.read_text(encoding="utf-8"))


def test_membership_is_model_isolated_and_deduplicated(model_id):
    with Session(_ENGINE) as session:
        cross = session.execute(
            text(
                "SELECT count(*) FROM entity_spatial_memberships m "
                "JOIN ifc_entities e ON e.id = m.entity_id "
                "WHERE m.source_model_id = :sid AND e.source_model_id <> :sid"
            ),
            {"sid": model_id},
        ).scalar()
        duplicates = session.execute(
            text(
                "SELECT count(*) FROM (SELECT entity_global_id, storey_global_id, source_kind "
                "FROM entity_spatial_memberships WHERE source_model_id = :sid "
                "GROUP BY 1, 2, 3 HAVING count(*) > 1) d"
            ),
            {"sid": model_id},
        ).scalar()
    assert cross == 0
    assert duplicates == 0


def test_primary_membership_is_unambiguous(model_id):
    with Session(_ENGINE) as session:
        conflicting = session.execute(
            text(
                "SELECT count(*) FROM (SELECT entity_global_id "
                "FROM entity_spatial_memberships "
                "WHERE source_model_id = :sid AND is_primary "
                "GROUP BY 1 HAVING count(DISTINCT storey_global_id) > 1) x"
            ),
            {"sid": model_id},
        ).scalar()
    assert conflicting == 0


def test_manifest_v002_valid_and_contract_checked(model_id):
    from bim_rag.semantic_manifest.schema_v002 import validate_document_v002

    document = _load_manifest(model_id)
    assert validate_document_v002(document) == []
    assert document["identity"]["contract_version"] == "v001"


def test_every_executable_capability_has_applicability(model_id):
    document = _load_manifest(model_id)
    for capability in document["content"]["capabilities"]:
        if capability["executable"]:
            assert capability["applicability"], capability["id"]
        else:
            assert capability.get("limitation"), capability["id"]


def test_field_applicability_is_per_class_not_container_union(model_id):
    """No applicability entry may claim more knowns than the class has rows."""
    document = _load_manifest(model_id)
    class_counts = {
        f"cls:{r['ifc_class']}": r["count"] for r in document["content"]["class_inventory"]
    }
    for capability in document["content"]["capabilities"]:
        for entry in capability.get("applicability", ()):
            if entry["subject"] in class_counts:
                assert entry["known_count"] <= class_counts[entry["subject"]], capability["id"]
                assert entry["eligible_count"] == class_counts[entry["subject"]], capability["id"]


def test_traversals_keep_roles_and_endpoints_together(model_id):
    document = _load_manifest(model_id)
    for traversal in document["content"]["traversals"]:
        assert traversal["from_role"] != traversal["to_role"]
        assert traversal["from_classes"]
        assert traversal["to_classes"]
        assert traversal["max_supported_hops"] >= 1
