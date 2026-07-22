"""Manifest generation against the real imported models (task25 §9.1).

Self-skipping: if PostgreSQL is unreachable the whole module skips green, the
same convention the backend's `query_live` package uses. Nothing here writes to
the database — every statement is a read.

Assertions are written as INVARIANTS over whatever models happen to be imported,
not as expectations about a particular file, so they keep their meaning as the
corpus changes. The two exceptions are the explicit backfill checks required by
§9.1, which must name the models they are about.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from bim_rag.config import get_db_url, get_model_semantics_root
from bim_rag.semantic_manifest import (
    build_semantic_manifest,
    estimate_tokens,
    manifest_path,
    read_manifest,
    validate_document,
)
from bim_rag.semantic_manifest.schema import (
    COVERAGE_UNSUPPORTED_SOURCE_STRUCTURE,
    REQUIRED_SECTIONS,
)

#: §2.4 soft efficiency target for the complete binder request.
SOFT_TOKEN_TARGET = 272_000


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


def _source_model_ids() -> list[int]:
    with Session(_ENGINE) as session:
        return [r[0] for r in session.execute(text("SELECT id FROM ifc_source_models ORDER BY id"))]


MODEL_IDS = _source_model_ids() if _ENGINE is not None else []


@pytest.fixture(scope="module", params=MODEL_IDS)
def manifest(request):
    with Session(_ENGINE) as session:
        return build_semantic_manifest(session, request.param)


# ---------------------------------------------------------------------------
# Structure
# ---------------------------------------------------------------------------


def test_every_model_produces_a_valid_manifest(manifest):
    assert validate_document(manifest) == []


def test_every_model_exposes_exactly_the_four_representations(manifest):
    """Four views of one model — never a fifth, and specifically never a
    separate logical-floor level (§2.3)."""
    assert set(manifest["content"]) == set(REQUIRED_SECTIONS)


def test_generation_is_deterministic(manifest):
    with Session(_ENGINE) as session:
        rebuilt = build_semantic_manifest(session, manifest["identity"]["source_model_id"])

    assert rebuilt["identity"]["content_hash"] == manifest["identity"]["content_hash"]


def test_the_manifest_stays_below_the_soft_token_target(manifest):
    """§2.4 / §10: the current project models must fit without truncation."""
    assert estimate_tokens(manifest) < SOFT_TOKEN_TARGET


def test_the_manifest_identity_matches_the_stored_source_model(manifest):
    sid = manifest["identity"]["source_model_id"]
    with Session(_ENGINE) as session:
        row = session.execute(
            text("SELECT file_fingerprint, ifc_schema FROM ifc_source_models WHERE id = :id"),
            {"id": sid},
        ).fetchone()

    assert manifest["identity"]["file_fingerprint"] == row[0]
    assert manifest["identity"]["ifc_schema"] == row[1]


# ---------------------------------------------------------------------------
# Completeness — nothing silently capped
# ---------------------------------------------------------------------------


def test_every_present_entity_class_appears(manifest):
    sid = manifest["identity"]["source_model_id"]
    with Session(_ENGINE) as session:
        expected = {
            r[0]
            for r in session.execute(
                text("SELECT DISTINCT ifc_class FROM ifc_entities WHERE source_model_id = :id"),
                {"id": sid},
            )
        }

    listed = {c["ifc_class"] for c in manifest["content"]["object_level"]["classes"]}

    assert listed == expected


def test_every_relationship_class_appears(manifest):
    sid = manifest["identity"]["source_model_id"]
    with Session(_ENGINE) as session:
        expected = {
            r[0]
            for r in session.execute(
                text(
                    "SELECT DISTINCT ifc_class FROM ifc_relationships WHERE source_model_id = :id"
                ),
                {"id": sid},
            )
        }

    listed = {
        c["ifc_class"] for c in manifest["content"]["relationship_level"]["relationship_classes"]
    }

    assert listed == expected


def test_every_reliable_property_field_appears(manifest):
    """No global fact cap, no per-field cap, no minimum-occurrence threshold.

    Counted against the database directly, so a reintroduced cap fails here.
    """
    sid = manifest["identity"]["source_model_id"]
    reliable = [
        c
        for c in manifest["content"]["type_property_level"]["property_containers"]
        if "fields" in c
    ]
    if not reliable:
        pytest.skip("this model exposes no reliably structured property container")

    names = [c["container"] for c in reliable]
    with Session(_ENGINE) as session:
        expected = {
            (r[0], r[1])
            for r in session.execute(
                text(
                    "SELECT DISTINCT ps.key, pr.key FROM ifc_entities e, "
                    "jsonb_each(e.canonical_json->'property_sets') ps, jsonb_each(ps.value) pr "
                    "WHERE e.source_model_id = :id AND jsonb_typeof(ps.value) = 'object' "
                    "AND ps.key = ANY(:names)"
                ),
                {"id": sid, "names": names},
            )
        }

    listed = {(c["container"], f["field"]) for c in reliable for f in c["fields"]}

    assert listed == expected


def test_singleton_values_are_not_dropped(manifest):
    """A value observed exactly once is still a value someone may ask about."""
    enumerated = [
        field
        for container in manifest["content"]["type_property_level"]["property_containers"]
        for field in container.get("fields", [])
        if "values" in field
    ]
    if not enumerated:
        pytest.skip("this model exposes no enumerated property values")

    counts = [v["count"] for field in enumerated for v in field["values"]]

    assert min(counts) == 1, "a minimum-occurrence threshold appears to have been reintroduced"


def test_high_cardinality_fields_stay_searchable_rather_than_absent(manifest):
    """§2.2: keep the concept and the capability, not the occurrence data."""
    searchable = [
        attribute
        for klass in manifest["content"]["object_level"]["classes"]
        for attribute in klass["attributes"]
        if attribute.get("searchable")
    ]
    for attribute in searchable:
        assert "values" not in attribute
        assert attribute["distinct_value_count"] > 0
        assert attribute["coverage"] != "absent"


# ---------------------------------------------------------------------------
# Unreliable source structures
# ---------------------------------------------------------------------------


def test_an_unreliable_container_exposes_no_field_names(manifest):
    """The limitation is described; the unreliable identifiers are not carried.

    Generalized over whatever containers trip the detector — this asserts the
    RULE, not any particular model's data.
    """
    unsupported = [
        container
        for section in ("property_containers", "quantity_containers")
        for container in manifest["content"]["type_property_level"][section]
        if container.get("coverage") == COVERAGE_UNSUPPORTED_SOURCE_STRUCTURE
    ]
    if not unsupported:
        pytest.skip("this model has no unreliably structured container")

    for container in unsupported:
        assert "fields" not in container
        assert container["structure_diagnostic"]["distinct_field_count"] > 0
        assert "reason" in container["structure_diagnostic"]


def test_an_unreliable_container_is_declared_as_a_missing_capability(manifest):
    """A question needing it must be answerable as `unavailable`, with a reason."""
    unsupported = [
        container
        for section in ("property_containers", "quantity_containers")
        for container in manifest["content"]["type_property_level"][section]
        if container.get("coverage") == COVERAGE_UNSUPPORTED_SOURCE_STRUCTURE
    ]
    if not unsupported:
        pytest.skip("this model has no unreliably structured container")

    declared = {
        capability["scope"]
        for capability in manifest["content"]["global_level"]["missing_capabilities"]
    }

    for container in unsupported:
        assert container["container"] in declared


# ---------------------------------------------------------------------------
# Backfill evidence (§9.1, §10)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("source_model_id", [1, 2])
def test_the_backfilled_artifact_exists_and_loads(source_model_id):
    """The two already-ingested models must have real, loadable artifacts."""
    with Session(_ENGINE) as session:
        row = session.execute(
            text("SELECT file_fingerprint FROM ifc_source_models WHERE id = :id"),
            {"id": source_model_id},
        ).fetchone()
    if row is None:
        pytest.skip(f"source model {source_model_id} is not imported here")

    path = manifest_path(get_model_semantics_root(), source_model_id, row[0])
    assert path.is_file(), f"no semantic manifest published for source model {source_model_id}"

    document = read_manifest(path)

    assert document["identity"]["file_fingerprint"] == row[0]
    assert validate_document(document) == []
