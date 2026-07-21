"""Synthetic active-model fixtures for the Task 24 binding tests.

Offline by construction: the vocabulary and field index are built in memory and
patched in, so no DB, OpenAI, or embedding model is touched. The real IFC
ontology IS loaded, because the schema roles and inheritance under test are
properties of the ontology itself.

The synthetic model deliberately mixes families (walls with subtypes, doors with
a co-present door STYLE, spaces whose "room" identity exists only as a stored
value, an absent-from-model class, a high-count irrelevant class) so that the
§13.6 anti-overfitting properties can be asserted without reference to any real
corpus model. Counts here are invented and are NOT the corpus models' values.
"""

from __future__ import annotations

import pytest

from app.query.semantic.vocabulary.profiles import (
    ClassProfile,
    ModelVocabulary,
    ObservedFactProfile,
    QuantityCoverageProfile,
)

SYNTHETIC_MODEL_ID = 4242


def _cls(ifc_class, count, kind="entity", **kw):
    return ClassProfile(ifc_class=ifc_class, kind=kind, instance_count=count, **kw)


def _fact(ifc_class, fact_kind, value, count=5, set_name=None, field_name=None, source="attribute"):
    return ObservedFactProfile(
        ifc_class=ifc_class,
        fact_kind=fact_kind,
        source=source,
        set_name=set_name,
        field_name=field_name,
        observed_value=value,
        normalized_value=None,
        occurrence_count=count,
    )


@pytest.fixture()
def synthetic_vocab() -> ModelVocabulary:
    v = ModelVocabulary(
        source_model_id=SYNTHETIC_MODEL_ID,
        file_fingerprint="fp-synthetic",
        extraction_version="v001",
        profile_builder_version="v001",
        ifc_schema="IFC2X3",
    )
    v.classes = [
        # A superclass with a present subtype.
        _cls("IfcWall", 40),
        _cls("IfcWallStandardCase", 60),
        # An occurrence co-present with its type definition.
        _cls("IfcDoor", 25),
        _cls("IfcDoorStyle", 3),
        # A whole with a co-present component that is NOT its descendant.
        _cls("IfcStair", 7),
        _cls("IfcStairFlight", 11),
        # Spatial structure whose "room" identity lives only in the data.
        _cls("IfcSpace", 30),
        _cls("IfcBuildingStorey", 9),
        # A deliberately high-count irrelevant class (§13.6 injection test).
        _cls("IfcBuildingElementProxy", 9000),
        _cls("IfcCurtainWall", 4),
        # A traversable relationship class.
        _cls(
            "IfcRelContainedInSpatialStructure",
            500,
            kind="relationship",
            endpoint_roles=[("RelatingStructure", 500), ("RelatedElements", 500)],
        ),
    ]
    v.facts = [
        # "rooms" is reachable ONLY through a stored value.
        _fact("IfcSpace", "object_type", "Rooms", 20),
        _fact("IfcSpace", "object_type", "Corridors", 6),
        # Boolean + categorical properties on unrelated families.
        _fact(
            "IfcWall",
            "property_value",
            "true",
            30,
            set_name="Pset_WallCommon",
            field_name="IsExternal",
            source="property",
        ),
        _fact(
            "IfcWall",
            "property_value",
            "false",
            70,
            set_name="Pset_WallCommon",
            field_name="IsExternal",
            source="property",
        ),
        _fact(
            "IfcWall",
            "property_value",
            "EI60",
            45,
            set_name="Pset_WallCommon",
            field_name="FireRating",
            source="property",
        ),
        _fact(
            "IfcDoor",
            "property_value",
            "true",
            5,
            set_name="Pset_DoorCommon",
            field_name="IsExternal",
            source="property",
        ),
        _fact("IfcDoor", "type_name", "D2 ny", 12),
        ObservedFactProfile(
            ifc_class="IfcWall",
            fact_kind="property_coverage",
            source="property",
            set_name="Pset_WallCommon",
            field_name="FireRating",
            observed_value="45/100 populated",
            normalized_value=None,
            occurrence_count=45,
        ),
    ]
    v.quantities = [
        QuantityCoverageProfile(
            ifc_class="IfcSpace",
            set_name="Qto_SpaceBaseQuantities",
            field_name="GrossFloorArea",
            populated_count=0,
            total_count=30,
            unit_available=False,
        )
    ]
    return v


@pytest.fixture()
def synthetic_storey_model():
    """Three logical floor bands over five storey entities.

    Deliberately band_count != storey_count so tests can prove the §11.4
    distinction (a logical floor is not a storey entity) without depending on a
    real model's numbers.
    """
    from app.query.semantic.spatial import FloorBand, Storey, StoreyModel

    bands = [
        FloorBand(index=0, storeys=[Storey("g0", "Ground", 0.0)]),
        FloorBand(
            index=1,
            storeys=[
                Storey("l1a", "Level 1 slab", 3000.0),
                Storey("l1b", "Level 1 finish", 3050.0),
            ],
        ),
        FloorBand(
            index=2,
            storeys=[
                Storey("l2a", "Level 2 slab", 6000.0),
                Storey("l2b", "Level 2 finish", 6050.0),
            ],
        ),
    ]
    return StoreyModel(
        bands=bands, reference_index=0, reference_basis="elevation_zero", total_storeys=5
    )


@pytest.fixture()
def slate_env(synthetic_vocab, synthetic_storey_model, monkeypatch):
    """Patch the cached/DB-backed lookups the slate builder reads."""
    from app.query.semantic import field_concepts as fc_module
    from app.query.semantic.field_concepts import build_field_concept_index

    monkeypatch.setattr(
        fc_module, "get_model_vocabulary", lambda s, sid, settings=None: synthetic_vocab
    )
    index = build_field_concept_index(session=None, source_model_id=SYNTHETIC_MODEL_ID)

    from app.query.binding import slate as slate_module

    monkeypatch.setattr(
        slate_module, "get_model_vocabulary", lambda s, sid, settings=None: synthetic_vocab
    )
    monkeypatch.setattr(
        slate_module, "get_field_concept_index", lambda s, sid, settings=None: index
    )
    monkeypatch.setattr(slate_module, "build_storey_model", lambda s, sid: synthetic_storey_model)
    return synthetic_vocab
