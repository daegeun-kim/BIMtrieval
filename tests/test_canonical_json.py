"""Tests: canonical JSON finiteness, cycle prevention, collision avoidance (spec §7)."""

from __future__ import annotations

import json

from tests.conftest import minimal_canonical


def test_canonical_is_json_serialisable():
    c = minimal_canonical()
    dumped = json.dumps(c)
    assert isinstance(dumped, str)


def test_canonical_no_cycles():
    """Verify no recursive references by round-tripping through JSON."""
    c = minimal_canonical()
    reloaded = json.loads(json.dumps(c))
    assert reloaded["meta"]["ifc_class"] == "IfcWall"


def test_pset_names_preserved():
    psets = {
        "Pset_WallCommon": {"IsExternal": {"value": True, "type": "bool"}},
        "Custom_PSet": {"Color": {"value": "Red", "type": "str"}},
    }
    c = minimal_canonical(psets=psets)
    assert "Pset_WallCommon" in c["property_sets"]
    assert "Custom_PSet" in c["property_sets"]


def test_pset_keys_do_not_collide():
    """Two property sets with same property name must not overwrite each other."""
    psets = {
        "Pset_A": {"Width": {"value": 100, "type": "float"}},
        "Pset_B": {"Width": {"value": 200, "type": "float"}},
    }
    c = minimal_canonical(psets=psets)
    assert c["property_sets"]["Pset_A"]["Width"]["value"] == 100
    assert c["property_sets"]["Pset_B"]["Width"]["value"] == 200


def test_qset_names_preserved():
    qsets = {"Qto_WallBaseQuantities": {"Length": {"value": 5.0, "provenance": "quantity"}}}
    c = minimal_canonical(qsets=qsets)
    assert "Qto_WallBaseQuantities" in c["quantity_sets"]


def test_null_optional_fields_omitted_from_identity():
    c = minimal_canonical(name=None)
    assert "name" not in c["identity"]


def test_warnings_list_present():
    c = minimal_canonical()
    assert isinstance(c["warnings"], list)


def test_meta_always_contains_required_fields():
    c = minimal_canonical(ifc_class="IfcDoor", global_id="DOOR001")
    assert c["meta"]["ifc_class"] == "IfcDoor"
    assert c["meta"]["global_id"] == "DOOR001"
    assert c["meta"]["extraction_version"] == "v001"


def test_materials_are_list():
    c = minimal_canonical(materials=[{"name": "Concrete"}])
    assert isinstance(c["materials"], list)
    assert c["materials"][0]["name"] == "Concrete"


def test_storey_none_when_absent():
    c = minimal_canonical(storey_name=None)
    assert c["storey"] is None


def test_storey_present_when_given():
    c = minimal_canonical(storey_name="Ground Floor")
    assert c["storey"]["name"] == "Ground Floor"
