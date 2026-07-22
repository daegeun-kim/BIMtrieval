"""Semantic-manifest loading, validation, and caching (task25 §2.1, §9.1).

The loader is the backend's trust boundary for model semantics. These tests pin
the refusals as tightly as the successes, because every rejected case here would
otherwise produce a confidently wrong answer about the wrong data:

- a stale artifact describes different geometry;
- a cross-model artifact describes a different building;
- a corrupt artifact describes nothing reliable.

There is deliberately no fallback path to test — §8 forbids running the legacy
capped vocabulary as a competing semantic source, so a failure must surface, not
degrade.
"""

from __future__ import annotations

import hashlib
import json

import pytest

from app.query.semantic.manifest import (
    COVERAGE_ABSENT,
    COVERAGE_POPULATED,
    COVERAGE_UNSUPPORTED_SOURCE_STRUCTURE,
    KIND_CLASS,
    KIND_PROPERTY,
    MANIFEST_SCHEMA_VERSION,
    ManifestStatus,
    ManifestUnavailableError,
    clear_manifest_cache,
    compute_manifest_status,
    expected_manifest_path,
    parse_manifest,
)
from app.query.semantic.manifest.loader import _load, _validate

FINGERPRINT = "a" * 64
OTHER_FINGERPRINT = "b" * 64


def _content(**overrides):
    content = {
        "object_level": {
            "classes": [
                {
                    "id": "cls:IfcWall",
                    "ifc_class": "IfcWall",
                    "count": 100,
                    "attributes": [
                        {
                            "id": "attr:IfcWall.name",
                            "field": "name",
                            "data_type": "text",
                            "coverage": COVERAGE_POPULATED,
                            "populated_count": 100,
                            "total_count": 100,
                            "distinct_value_count": 3,
                            "values": [
                                {"value": "Basic Wall", "count": 80},
                                {"value": "Curtain Wall", "count": 20},
                            ],
                        },
                        {
                            "id": "attr:IfcWall.tag",
                            "field": "tag",
                            "data_type": "text",
                            "coverage": COVERAGE_POPULATED,
                            "populated_count": 100,
                            "total_count": 100,
                            "distinct_value_count": 900,
                            "searchable": True,
                        },
                    ],
                }
            ]
        },
        "type_property_level": {
            "property_containers": [
                {
                    "id": "propertyset:Pset_WallCommon",
                    "container": "Pset_WallCommon",
                    "kind": "property",
                    "applies_to": ["IfcWall"],
                    "occurrence_count": 100,
                    "distinct_field_count": 2,
                    "coverage": COVERAGE_POPULATED,
                    "fields": [
                        {
                            "id": "prop:Pset_WallCommon.IsExternal",
                            "field": "IsExternal",
                            "set": "Pset_WallCommon",
                            "data_type": "boolean",
                            "operators": ["equals", "not_equals"],
                            "coverage": COVERAGE_POPULATED,
                            "populated_count": 100,
                            "total_count": 100,
                            "distinct_value_count": 2,
                            "values": [
                                {"value": "false", "count": 70},
                                {"value": "true", "count": 30},
                            ],
                        }
                    ],
                },
                {
                    "id": "propertyset:MysteryBag",
                    "container": "MysteryBag",
                    "kind": "property",
                    "applies_to": ["IfcWall"],
                    "occurrence_count": 50,
                    "distinct_field_count": 4000,
                    "coverage": COVERAGE_UNSUPPORTED_SOURCE_STRUCTURE,
                    "structure_diagnostic": {
                        "container": "MysteryBag",
                        "distinct_field_count": 4000,
                        "reason": "no stable field schema",
                    },
                },
            ],
            "quantity_containers": [],
            "materials": [],
            "classifications": [],
        },
        "relationship_level": {
            "relationship_classes": [
                {
                    "id": "rel:IfcRelContainedInSpatialStructure",
                    "ifc_class": "IfcRelContainedInSpatialStructure",
                    "count": 12,
                    "coverage": COVERAGE_POPULATED,
                    "endpoint_roles": [
                        {
                            "id": "rel:IfcRelContainedInSpatialStructure:RelatedElements",
                            "role": "RelatedElements",
                            "endpoints": [{"endpoint_ifc_class": "IfcWall", "count": 100}],
                        }
                    ],
                }
            ]
        },
        "global_level": {
            "entity_total": 100,
            "class_inventory": [{"ifc_class": "IfcWall", "count": 100}],
            "storeys": [
                {
                    "id": "storey:S1",
                    "name": "Level 1",
                    "global_id": "S1",
                    "elevation": 0.0,
                }
            ],
            "missing_capabilities": [
                {"capability": "quantity_queries", "scope": None, "coverage": COVERAGE_ABSENT}
            ],
        },
    }
    content.update(overrides)
    return content


def _hash(content):
    canonical = json.dumps(
        content, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _document(source_model_id=5, fingerprint=FINGERPRINT, content=None, **identity_overrides):
    content = content if content is not None else _content()
    identity = {
        "source_model_id": source_model_id,
        "file_fingerprint": fingerprint,
        "file_name": "synthetic.ifc",
        "ifc_schema": "IFC2X3",
        "extraction_version": "v001",
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "builder_version": "v001",
        "content_hash": _hash(content),
    }
    identity.update(identity_overrides)
    return {"identity": identity, "content": content}


def _publish(root, document):
    identity = document["identity"]
    path = expected_manifest_path(root, identity["source_model_id"], identity["file_fingerprint"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(document, sort_keys=True, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    return path


@pytest.fixture(autouse=True)
def _clear_cache():
    clear_manifest_cache()
    yield
    clear_manifest_cache()


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------


def test_a_current_artifact_is_ready(tmp_path):
    _publish(tmp_path, _document())

    assert compute_manifest_status(tmp_path, 5, FINGERPRINT) is ManifestStatus.READY


def test_an_artifact_for_another_fingerprint_is_stale_not_ready(tmp_path):
    """The defining case: semantics for a different version of the same file."""
    _publish(tmp_path, _document(fingerprint=OTHER_FINGERPRINT))

    assert compute_manifest_status(tmp_path, 5, FINGERPRINT) is ManifestStatus.STALE


def test_no_artifact_is_missing(tmp_path):
    assert compute_manifest_status(tmp_path, 5, FINGERPRINT) is ManifestStatus.MISSING


def test_a_model_without_a_fingerprint_is_unavailable(tmp_path):
    assert compute_manifest_status(tmp_path, 5, None) is ManifestStatus.UNAVAILABLE


def test_a_traversal_path_is_refused(tmp_path):
    assert compute_manifest_status(tmp_path, 5, "../../escape") is ManifestStatus.UNAVAILABLE


# ---------------------------------------------------------------------------
# Loading and refusal
# ---------------------------------------------------------------------------


def test_a_valid_artifact_loads(tmp_path):
    _publish(tmp_path, _document())

    manifest = _load(tmp_path, 5, FINGERPRINT)

    assert manifest.source_model_id == 5
    assert manifest.file_fingerprint == FINGERPRINT


def test_a_stale_artifact_is_refused_rather_than_used(tmp_path):
    _publish(tmp_path, _document(fingerprint=OTHER_FINGERPRINT))

    with pytest.raises(ManifestUnavailableError) as excinfo:
        _load(tmp_path, 5, FINGERPRINT)

    assert excinfo.value.status is ManifestStatus.STALE
    assert "different version" in str(excinfo.value)


def test_a_missing_artifact_explains_how_to_fix_it(tmp_path):
    with pytest.raises(ManifestUnavailableError) as excinfo:
        _load(tmp_path, 5, FINGERPRINT)

    assert "ingestion" in str(excinfo.value)


def test_a_cross_model_artifact_is_refused(tmp_path):
    """Source isolation: a manifest naming another model is never usable."""
    document = _document(source_model_id=99)
    document["identity"]["file_fingerprint"] = FINGERPRINT
    path = expected_manifest_path(tmp_path, 5, FINGERPRINT)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(ManifestUnavailableError) as excinfo:
        _load(tmp_path, 5, FINGERPRINT)

    assert "describes model 99" in str(excinfo.value)


def test_a_tampered_artifact_fails_its_integrity_check(tmp_path):
    document = _document()
    document["content"]["global_level"]["entity_total"] = 999999
    path = expected_manifest_path(tmp_path, 5, FINGERPRINT)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(ManifestUnavailableError, match="integrity"):
        _load(tmp_path, 5, FINGERPRINT)


def test_a_future_schema_version_is_refused_with_guidance(tmp_path):
    document = _document()
    document["identity"]["manifest_schema_version"] = "v999"
    document["identity"]["content_hash"] = _hash(document["content"])
    path = expected_manifest_path(tmp_path, 5, FINGERPRINT)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(ManifestUnavailableError, match="re-run ingestion"):
        _load(tmp_path, 5, FINGERPRINT)


def test_unparseable_json_is_refused(tmp_path):
    path = expected_manifest_path(tmp_path, 5, FINGERPRINT)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")

    with pytest.raises(ManifestUnavailableError, match="could not be read"):
        _load(tmp_path, 5, FINGERPRINT)


def test_validation_accepts_a_well_formed_document():
    _validate(_document(), 5, FINGERPRINT)


# ---------------------------------------------------------------------------
# Parsing into the uniform concept namespace
# ---------------------------------------------------------------------------


def test_every_section_contributes_concepts():
    manifest = parse_manifest(_document())
    kinds = {c.kind for c in manifest.concepts.values()}

    assert {"class", "attribute", "property", "relationship", "endpoint_role", "storey"} <= kinds


def test_semantic_ids_are_unique_and_directly_addressable():
    manifest = parse_manifest(_document())

    assert manifest.concept("cls:IfcWall").kind == KIND_CLASS
    assert manifest.concept("prop:Pset_WallCommon.IsExternal").kind == KIND_PROPERTY
    assert manifest.concept("nope:missing") is None


def test_an_unsupported_container_is_present_but_not_queryable():
    """It must be selectable so it can be CITED as the reason for unavailable,
    while never being executable as a filter."""
    manifest = parse_manifest(_document())
    bag = manifest.concept("propertyset:MysteryBag")

    assert bag is not None
    assert bag.is_queryable is False
    assert bag.limitation == "no stable field schema"


def test_an_absent_field_stays_queryable_because_zero_is_an_answer():
    content = _content()
    content["object_level"]["classes"][0]["attributes"][0]["coverage"] = COVERAGE_ABSENT
    manifest = parse_manifest(_document(content=content))

    assert manifest.concept("attr:IfcWall.name").is_queryable is True


def test_a_searchable_field_carries_its_cardinality_but_no_values():
    manifest = parse_manifest(_document())
    tag = manifest.concept("attr:IfcWall.tag")

    assert tag.searchable is True
    assert tag.values == ()
    assert tag.distinct_value_count == 900


def test_enumerated_values_are_addressable_case_insensitively():
    manifest = parse_manifest(_document())
    is_external = manifest.concept("prop:Pset_WallCommon.IsExternal")

    assert is_external.has_value("TRUE")
    assert is_external.has_value("true")
    assert not is_external.has_value("maybe")


def test_boolean_field_values_distinguish_the_filtered_subset():
    """The Task 24 defect in data form: "external walls" is 30, not 100.

    The manifest must make the distinction available; a binder that reports the
    field instead of filtering on it would still answer 100.
    """
    manifest = parse_manifest(_document())
    is_external = manifest.concept("prop:Pset_WallCommon.IsExternal")

    assert dict(is_external.values)["true"] == 30
    assert manifest.concept("cls:IfcWall").total_count == 100


def test_class_and_field_roles_stay_distinct():
    manifest = parse_manifest(_document())

    assert manifest.concept("cls:IfcWall").is_field is False
    assert manifest.concept("prop:Pset_WallCommon.IsExternal").is_field is True


def test_identifier_text_is_split_for_lexical_matching():
    manifest = parse_manifest(_document())

    assert manifest.concept("cls:IfcWall").text == "Ifc Wall"


def test_missing_capabilities_are_carried_through():
    manifest = parse_manifest(_document())

    assert manifest.missing_capabilities[0]["capability"] == "quantity_queries"


def test_fields_for_class_respects_applicability():
    manifest = parse_manifest(_document())
    fields = {c.semantic_id for c in manifest.fields_for_class("IfcWall")}

    assert "prop:Pset_WallCommon.IsExternal" in fields


def test_the_raw_document_is_retained_for_the_binder():
    """§2.4: the binder receives the COMPLETE manifest, untruncated."""
    document = _document()
    manifest = parse_manifest(document)

    assert manifest.document == document
