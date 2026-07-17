"""Static IFC2X3 ontology validation (Task 16 §2, §13 Static ontology).

Offline: reads the committed JSON + index only. No DB, no OpenAI, no BGE-M3
model load (the index test compares metadata and array shape, it does not embed).
"""

from __future__ import annotations

import json

import pytest

from app.query.semantic.ontology.loader import (
    PROFILE_VERSION,
    compute_content_hash,
    get_ontology,
    get_ontology_index,
    json_path,
    profile_text,
    split_class_words,
)

_BRANCHES = ("IfcObjectDefinition", "IfcPropertyDefinition", "IfcRelationship")


@pytest.fixture(scope="module")
def doc():
    return get_ontology("IFC2X3")


def _branch(entity) -> str:
    chain = [entity.ifc_class] + entity.ancestors
    for b in _BRANCHES:
        if b in chain:
            return b
    return "IfcRoot"


def test_exactly_301_ifcroot_hierarchy_entries(doc):
    assert doc.entity_count == 301
    assert len(doc.entities) == 301


def test_root_branch_counts(doc):
    counts = {b: 0 for b in _BRANCHES}
    root = 0
    for e in doc.entities:
        b = _branch(e)
        if b == "IfcRoot":
            root += 1
        else:
            counts[b] += 1
    assert counts["IfcObjectDefinition"] == 233
    assert counts["IfcPropertyDefinition"] == 17
    assert counts["IfcRelationship"] == 50
    assert root == 1  # IfcRoot itself


def test_no_duplicate_class_names(doc):
    names = [e.ifc_class for e in doc.entities]
    assert len(names) == len(set(names))


def test_single_parent_ancestry_terminates_at_root(doc):
    by_name = {e.ifc_class: e for e in doc.entities}
    for e in doc.entities:
        if e.ifc_class == "IfcRoot":
            assert e.immediate_parent is None
            assert e.ancestors == []
            continue
        # exactly one immediate parent, and the chain ends at IfcRoot
        assert e.immediate_parent is not None
        assert e.ancestors[-1] == "IfcRoot"
        assert e.ancestors[0] == e.immediate_parent
        # ancestry is a real chain in this ontology (every hop present)
        assert e.immediate_parent in by_name


def test_schema_metadata_and_hash(doc):
    assert doc.schema_name == "IFC2X3"
    assert doc.source
    assert doc.release
    assert doc.ontology_version == "v001"
    assert doc.profile_version == PROFILE_VERSION
    # get_ontology already recomputes+verifies the hash; assert it here too.
    assert compute_content_hash(doc.entities) == doc.content_hash


def test_representative_classes_and_predefined_types(doc):
    by_name = {e.ifc_class: e for e in doc.entities}
    slab = by_name["IfcSlab"]
    assert slab.abstract is False
    assert slab.immediate_parent == "IfcBuildingElement"
    assert {"FLOOR", "ROOF", "LANDING", "BASESLAB"} <= set(slab.predefined_types)
    assert "ROOFING" in by_name["IfcCovering"].predefined_types
    assert by_name["IfcWallStandardCase"].immediate_parent == "IfcWall"
    assert "IfcDoor" in by_name
    assert "IfcRoof" in by_name  # present in schema even though absent in the model


def test_no_synonym_or_alias_gate(doc):
    # No alias/synonym field on the model...
    for field in ("aliases", "synonyms", "alias", "synonym"):
        assert field not in type(doc.entities[0]).model_fields
    # ...and no such key in the raw committed JSON either.
    raw = json.loads(json_path("IFC2X3").read_text(encoding="utf-8"))
    banned = {"alias", "aliases", "synonym", "synonyms"}
    for e in raw["entities"]:
        assert banned.isdisjoint(e.keys())


def test_profile_text_deterministic_and_grounded(doc):
    slab = next(e for e in doc.entities if e.ifc_class == "IfcSlab")
    t1 = profile_text(slab)
    t2 = profile_text(slab)
    assert t1 == t2
    assert "IfcSlab" in t1
    assert "Slab" in t1
    assert "ROOF" in t1  # predefined-type literal surfaced for retrieval


def test_split_class_words():
    assert split_class_words("IfcWallStandardCase") == "Wall Standard Case"
    assert split_class_words("IfcSlab") == "Slab"
    assert split_class_words("IfcRelDefinesByType") == "Rel Defines By Type"


def test_committed_index_matches_json(doc):
    idx = get_ontology_index("IFC2X3")
    assert len(idx) == 301
    assert idx.embedding_model == "BAAI/bge-m3"
    assert idx.embedding_dim == 1024
    assert idx.vectors.shape == (301, 1024)
    # rows are aligned with the JSON entity order
    assert [e.ifc_class for e in idx.entities] == [e.ifc_class for e in doc.entities]
