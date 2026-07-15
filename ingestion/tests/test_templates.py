"""Tests: feature-template selection, determinism, null omission, dedup (spec §8)."""

from __future__ import annotations

from bim_rag.templates import TEMPLATE_VERSION, _build_feature_sentences, generate_text
from tests.conftest import minimal_canonical


def test_template_version_is_v001():
    assert TEMPLATE_VERSION == "v001"


def test_identity_always_present():
    c = minimal_canonical(ifc_class="IfcWall")
    text, _ = generate_text(c)
    assert "IfcWall" in text


def test_global_id_always_present():
    c = minimal_canonical(global_id="WALL001")
    text, _ = generate_text(c)
    assert "WALL001" in text


def test_name_included_when_present():
    c = minimal_canonical(name="W-001")
    text, _ = generate_text(c)
    assert "W-001" in text


def test_name_omitted_when_null():
    c = minimal_canonical(name=None)
    text, _ = generate_text(c)
    assert "None" not in text
    assert "null" not in text


def test_storey_included_when_present():
    c = minimal_canonical(storey_name="Ground Floor")
    text, _ = generate_text(c)
    assert "Ground Floor" in text


def test_storey_omitted_when_null():
    c = minimal_canonical(storey_name=None)
    text, _ = generate_text(c)
    assert "storey" not in text.lower()


def test_property_included():
    psets = {"Pset_WallCommon": {"IsExternal": {"value": True, "type": "bool"}}}
    c = minimal_canonical(psets=psets)
    text, _ = generate_text(c)
    assert "IsExternal" in text
    assert "Pset_WallCommon" in text


def test_property_with_null_value_omitted():
    psets = {"Pset_WallCommon": {"FireRating": {"value": None, "type": "NoneType"}}}
    c = minimal_canonical(psets=psets)
    text, _ = generate_text(c)
    assert "FireRating" not in text


def test_quantity_included():
    qsets = {
        "Qto_WallBaseQuantities": {
            "Length": {
                "value": 5000.0,
                "normalized_value": 5.0,
                "normalized_unit": "m",
                "provenance": "quantity",
            }
        }
    }
    c = minimal_canonical(qsets=qsets)
    text, _ = generate_text(c)
    assert "Length" in text
    assert "5.0 m" in text


def test_determinism():
    c = minimal_canonical(
        psets={"Pset_A": {"X": {"value": 1, "type": "int"}}},
    )
    t1, _ = generate_text(c)
    t2, _ = generate_text(c)
    assert t1 == t2


def test_no_relationship_info_in_text():
    c = minimal_canonical()
    text, _ = generate_text(c)
    assert "IfcRel" not in text


def test_deduplication():
    """Identical sentences should appear only once."""
    c = minimal_canonical(name="W-001")
    sentences = _build_feature_sentences(c)
    texts = [s for _, s in sentences]
    assert len(texts) == len(set(texts))


def test_identical_feature_types_use_identical_templates():
    """Width property from two different classes must produce same template pattern."""
    wall = minimal_canonical(
        ifc_class="IfcWall",
        psets={"Pset_A": {"Width": {"value": 100, "type": "float"}}},
    )
    door = minimal_canonical(
        ifc_class="IfcDoor",
        psets={"Pset_A": {"Width": {"value": 100, "type": "float"}}},
    )

    # Extract the property sentence template pattern (strip class-specific parts)
    def get_prop_sentence(c):
        sents = _build_feature_sentences(c)
        return next((s for _, s in sents if "Width" in s), None)

    s1 = get_prop_sentence(wall)
    s2 = get_prop_sentence(door)
    assert s1 is not None
    assert s2 is not None
    # Same template means same structural pattern when value/pset are identical
    assert s1 == s2


def test_predefined_type_notdefined_omitted():
    c = minimal_canonical(predefined_type="NOTDEFINED")
    text, _ = generate_text(c)
    assert "NOTDEFINED" not in text


def test_predefined_type_userdefined_omitted():
    c = minimal_canonical(predefined_type="USERDEFINED")
    text, _ = generate_text(c)
    assert "USERDEFINED" not in text


def test_predefined_type_solidwall_included():
    c = minimal_canonical(predefined_type="SOLIDWALL")
    text, _ = generate_text(c)
    assert "SOLIDWALL" in text


def test_truncation_flag_false_for_short_text():
    c = minimal_canonical()
    _, truncated = generate_text(c)
    assert truncated is False


def test_truncation_flag_true_for_very_long_text():
    """Force truncation by adding many properties."""
    psets = {
        f"Pset_{i}": {f"Property_{j}": {"value": "x" * 50, "type": "str"} for j in range(20)}
        for i in range(10)
    }
    c = minimal_canonical(psets=psets)
    _, truncated = generate_text(c)
    assert truncated is True


def test_material_included():
    c = minimal_canonical(materials=[{"name": "Concrete"}])
    text, _ = generate_text(c)
    assert "Concrete" in text


def test_no_none_or_null_literals_in_text():
    c = minimal_canonical(name=None, storey_name=None)
    text, _ = generate_text(c)
    assert "None" not in text
    assert "null" not in text
