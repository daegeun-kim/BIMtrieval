"""Field-concept index (Task 24 §4.1, §13.3).

Offline: builds the index from a SYNTHETIC `ModelVocabulary`, so no DB, no
OpenAI, no embedding. The synthetic model deliberately mixes unrelated field
families (a boolean property, a rating string, a quantity, a classification-like
attribute) so a mechanism that only worked for one of them cannot pass (§13.3
"use several unrelated BIM fields and classes to prove general behavior").

Its class and value names are invented for the test and are NOT the corpus
models' values — nothing here encodes an expected count or a real stored value.
"""

from __future__ import annotations

import pytest

from app.query.binding.lexical import content_tokens, token_overlap
from app.query.semantic.field_concepts import (
    FieldConcept,
    build_field_concept_index,
)
from app.query.semantic.vocabulary.profiles import (
    ModelVocabulary,
    ObservedFactProfile,
    QuantityCoverageProfile,
)


def _fact(ifc_class, fact_kind, set_name, field_name, value, count=10):
    return ObservedFactProfile(
        ifc_class=ifc_class,
        fact_kind=fact_kind,
        source="property" if set_name else "attribute",
        set_name=set_name,
        field_name=field_name,
        observed_value=value,
        normalized_value=None,
        occurrence_count=count,
    )


@pytest.fixture()
def vocab() -> ModelVocabulary:
    v = ModelVocabulary(
        source_model_id=99,
        file_fingerprint="fp-test",
        extraction_version="v001",
        profile_builder_version="v001",
        ifc_schema="IFC2X3",
    )
    v.facts = [
        # A boolean property on two unrelated classes.
        _fact("IfcWall", "property_value", "Pset_WallCommon", "IsExternal", "true"),
        _fact("IfcWall", "property_value", "Pset_WallCommon", "IsExternal", "false"),
        _fact("IfcWindow", "property_value", "Pset_WindowCommon", "IsExternal", "true"),
        # A categorical string property.
        _fact("IfcWall", "property_value", "Pset_WallCommon", "FireRating", "EI30"),
        _fact("IfcWall", "property_value", "Pset_WallCommon", "FireRating", "EI60"),
        # A numeric-looking property.
        _fact("IfcDoor", "property_value", "Pset_DoorCommon", "NominalWidth", "900"),
        _fact("IfcDoor", "property_value", "Pset_DoorCommon", "NominalWidth", "1200"),
        # Coverage facts drive populated/total.
        ObservedFactProfile(
            ifc_class="IfcWall",
            fact_kind="property_coverage",
            source="property",
            set_name="Pset_WallCommon",
            field_name="FireRating",
            observed_value="40/100 populated",
            normalized_value=None,
            occurrence_count=40,
        ),
        # Fixed attribute fields.
        _fact("IfcSpace", "object_type", None, None, "Rooms"),
        _fact("IfcSpace", "object_type", None, None, "Corridors"),
        _fact("IfcDoor", "type_name", None, None, "D2 ny"),
    ]
    v.quantities = [
        QuantityCoverageProfile(
            ifc_class="IfcSlab",
            set_name="Qto_SlabBaseQuantities",
            field_name="GrossArea",
            populated_count=30,
            total_count=50,
            unit_available=True,
        )
    ]
    return v


@pytest.fixture()
def index(vocab, monkeypatch):
    monkeypatch.setattr(
        "app.query.semantic.field_concepts.get_model_vocabulary",
        lambda session, sid, settings=None: vocab,
    )
    return build_field_concept_index(session=None, source_model_id=99)


def _find(index, field_kind, set_name, field_name) -> FieldConcept:
    concept = index.get(field_kind, set_name, field_name)
    assert concept is not None, f"{field_kind}/{set_name}/{field_name} missing from index"
    return concept


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def test_property_fields_are_indexed_with_their_observed_values(index):
    fire = _find(index, "property", "Pset_WallCommon", "FireRating")
    assert set(fire.sample_values) == {"EI30", "EI60"}
    assert fire.applicable_classes == ("IfcWall",)


def test_the_same_field_across_two_property_sets_stays_distinct(index):
    """`IsExternal` lives in a different pset per class; conflating them would
    apply a wall's coverage to windows."""
    wall = _find(index, "property", "Pset_WallCommon", "IsExternal")
    window = _find(index, "property", "Pset_WindowCommon", "IsExternal")
    assert wall.applicable_classes == ("IfcWall",)
    assert window.applicable_classes == ("IfcWindow",)


def test_coverage_counts_are_recorded(index):
    fire = _find(index, "property", "Pset_WallCommon", "FireRating")
    assert fire.populated_count == 40
    assert fire.total_count == 100
    assert fire.coverage_ratio == pytest.approx(0.4)


def test_quantity_fields_are_numeric_and_carry_unit_availability(index):
    area = _find(index, "quantity", "Qto_SlabBaseQuantities", "GrossArea")
    assert area.data_type == "number"
    assert area.unit_available is True
    assert area.populated_count == 30 and area.total_count == 50


def test_fixed_attribute_and_type_fact_fields_are_present(index):
    assert _find(index, "attribute", None, "object_type").sample_values
    assert _find(index, "type_fact", None, "type_name").sample_values
    # Fixed fields with no observed values still exist so a question can reach them.
    assert index.get("attribute", None, "name") is not None
    assert index.get("attribute", None, "predefined_type") is not None


# ---------------------------------------------------------------------------
# Data-type inference drives the operator set
# ---------------------------------------------------------------------------


def test_boolean_property_infers_boolean_type_and_equality_operators(index):
    ext = _find(index, "property", "Pset_WallCommon", "IsExternal")
    assert ext.data_type == "boolean"
    assert set(ext.operators) == {"eq", "ne"}


def test_numeric_property_infers_number_type_and_comparison_operators(index):
    width = _find(index, "property", "Pset_DoorCommon", "NominalWidth")
    assert width.data_type == "number"
    assert "gt" in width.operators and "between" in width.operators


def test_categorical_property_infers_text_type_and_string_operators(index):
    """Regression guard for a defect this suite caught during implementation.

    `EI30`/`EI60` CONTAIN digits, and inference used a substring numeric search,
    so a fire-rating field was typed numeric and offered `gt`/`between`. Stored
    values must be tested for numeric-ness in full, not searched.
    """
    fire = _find(index, "property", "Pset_WallCommon", "FireRating")
    assert fire.data_type == "text"
    assert "case_insensitive_exact" in fire.operators
    assert "gt" not in fire.operators and "between" not in fire.operators


# ---------------------------------------------------------------------------
# Search — ordinary wording reaching the right field (§4.1)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("question", "expected_field"),
    [
        ("which walls have a fire rating", "FireRating"),
        ("how many external windows are there", "IsExternal"),
        ("what is the gross area of the slabs", "GrossArea"),
        ("show the nominal width of each door", "NominalWidth"),
        # Paraphrases written for this test, absent from specs/test_query.md (§13.6).
        ("do any partitions carry a fire rating value", "FireRating"),
        ("anything marked external", "IsExternal"),
        ("total gross area please", "GrossArea"),
    ],
)
def test_search_reaches_the_field_a_question_names(index, question, expected_field):
    hits = index.search(frozenset(content_tokens(question)))
    assert hits, f"no field candidate for {question!r}"
    assert hits[0][0].field_name == expected_field


def test_search_returns_nothing_for_a_concept_the_model_does_not_carry(index):
    """§6: missing field coverage is not a zero value. A thermal question must
    find no field rather than being redirected to a similar-sounding one."""
    hits = index.search(frozenset(content_tokens("what is the u-value and thermal transmittance")))
    assert hits == []


def test_search_can_be_restricted_to_the_subject_family(index):
    """A field existing on one subject family but not another (§13.3)."""
    tokens = frozenset(content_tokens("external"))
    wall_hits = index.search(tokens, subject_classes={"IfcWall"})
    assert [c.set_name for c, _ in wall_hits] == ["Pset_WallCommon"]
    window_hits = index.search(tokens, subject_classes={"IfcWindow"})
    assert [c.set_name for c, _ in window_hits] == ["Pset_WindowCommon"]


def test_fully_named_field_outranks_a_partial_match(index):
    hits = index.search(frozenset(content_tokens("fire rating")))
    assert hits[0][1] == 1.0
    assert hits[0][0].field_name == "FireRating"


def test_a_verbose_set_name_does_not_bury_its_own_fields(index):
    """Regression guard for a defect this suite caught during implementation.

    Scoring against field-name AND set-name tokens combined made
    `Pset_WallCommon.FireRating` a five-token target, so the question
    "fire rating" scored 0.4 and fell below the threshold. Every field in a
    verbosely-named set was unreachable. Qualification must use the field name
    only; the set name may influence ordering but never eligibility.
    """
    hits = index.search(frozenset(content_tokens("fire rating")))
    assert [c.field_name for c, _ in hits] == ["FireRating"]

    long_set = FieldConcept(
        field_kind="property",
        set_name="Pset_ExtremelyLongVendorSpecificSetNameHere",
        field_name="FireRating",
        data_type="text",
        operators=("exact",),
    )
    assert token_overlap(frozenset({"fire", "rating"}), long_set.name_tokens) == 1.0


def test_set_name_breaks_ties_between_same_named_fields_on_different_families(index):
    """The set name must still do useful work: naming a family should prefer
    that family's copy of a shared field name."""
    hits = index.search(frozenset(content_tokens("external walls")))
    assert hits[0][0].set_name == "Pset_WallCommon"


def test_search_is_bounded_and_deterministic(index):
    tokens = frozenset(content_tokens("external fire rating width area name type"))
    first = index.search(tokens, limit=3)
    assert len(first) <= 3
    assert [c.key for c, _ in first] == [c.key for c, _ in index.search(tokens, limit=3)]


def test_search_result_carries_no_unbounded_value_dump(index):
    """§1.3: 'a few query-relevant normalized observed values, not a global
    value dump'."""
    for concept in index.concepts:
        assert len(concept.sample_values) <= 6
