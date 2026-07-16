"""Truthful component details + instance/type/family group matching
(tasks/task13.md §4, §5).

Offline: the DB session dependency is overridden and the entity query functions
are monkeypatched, so no PostgreSQL or OpenAI access occurs.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.api.app import app
from app.api.routes import models as models_route
from app.query.sql import entities as entity_ops
from app.viewer import details as detail_ops

MODEL_ID = 1
GID = "3xR$Hs0Ab0GwPzKMDUAAAA"

# A realistic canonical_json in the exact shape bim_rag.ifc_parser writes.
CANONICAL_WITH_TYPE_AND_FAMILY = {
    "meta": {"predefined_type": "DOOR"},
    "identity": {
        "name": "Deur_binnen_88x231",
        "description": "Binnendeur",
        "object_type": "Deur",
        "tag": "331621",
    },
    "storey": {"name": "01 begane grond", "global_id": "STOREY-GID"},
    "type": {"name": "DoorType_88x231", "global_id": "TYPE-GID", "predefined_type": "DOOR"},
    "materials": [{"name": "Hout"}, {"name": "Hout"}, {"name": "Glas"}],
    "property_sets": {
        "Pset_DoorCommon": {
            "IsExternal": {"value": False, "type": "bool"},
            "FireRating": {"value": "30", "type": "str"},
            "Reference": {"value": "88x231", "type": "str"},
            # Not allowlisted -> must never appear in the response.
            "SecretInternalNote": {"value": "do-not-leak", "type": "str"},
        }
    },
    "quantity_sets": {
        "Qto_DoorBaseQuantities": {
            "Width": {"value": 880.0, "provenance": "quantity", "unit": "project_unit"},
            # Not allowlisted -> excluded.
            "SomeUnknownQty": {"value": 1.0, "provenance": "quantity"},
        }
    },
    "placement": {"local_z": 0.0},
    "warnings": [],
}

# The current Schependomlaan model's real situation: no explicit type, no family.
CANONICAL_NO_TYPE_NO_FAMILY = {
    "meta": {"predefined_type": None},
    "identity": {"name": "Basiswand:Wand_Bui_Spouw:305150"},
    "storey": {"name": "01 begane grond", "global_id": "STOREY-GID"},
    "type": None,
    "materials": [],
    "property_sets": {},
    "quantity_sets": {},
    "placement": {},
    "warnings": [],
}


def _row(canonical, gid=GID, ifc_class="IfcDoor"):
    return SimpleNamespace(id=42, global_id=gid, ifc_class=ifc_class, canonical_json=canonical)


@pytest.fixture()
def api():
    app.dependency_overrides[models_route.get_db] = lambda: object()
    yield TestClient(app)
    app.dependency_overrides.pop(models_route.get_db, None)


def _stub_entity(monkeypatch, canonical, **kw):
    row = _row(canonical, **kw)
    monkeypatch.setattr(
        entity_ops,
        "get_entity_canonical",
        lambda _s, model_id, gid: row if (model_id == MODEL_ID and gid == row.global_id) else None,
    )
    return row


# ---------------------------------------------------------------------------
# Details endpoint (task13 §4)
# ---------------------------------------------------------------------------


def test_details_returns_allowlisted_bounded_schema(api, monkeypatch):
    _stub_entity(monkeypatch, CANONICAL_WITH_TYPE_AND_FAMILY)
    monkeypatch.setattr(entity_ops, "get_ifc_class_for_global_id", lambda *_a: "IfcDoorType")

    resp = api.get(f"/api/models/{MODEL_ID}/entities/{GID}/details")
    assert resp.status_code == 200
    body = resp.json()

    assert set(body.keys()) == {"source_model_id", "instance", "type", "family", "availability"}
    inst = body["instance"]
    assert inst["global_id"] == GID
    assert inst["ifc_class"] == "IfcDoor"
    assert inst["name"] == "Deur_binnen_88x231"
    assert inst["predefined_type"] == "DOOR"
    assert inst["storey_name"] == "01 begane grond"
    # materials de-duplicated, order preserved
    assert inst["materials"] == ["Hout", "Glas"]

    # Only allowlisted properties/quantities are returned.
    prop_names = {p["name"] for p in inst["properties"]}
    assert prop_names == {"IsExternal", "FireRating", "Reference"}
    assert {q["name"] for q in inst["quantities"]} == {"Width"}
    # A non-allowlisted value must never leak, under any key.
    assert "SecretInternalNote" not in resp.text
    assert "do-not-leak" not in resp.text
    assert "SomeUnknownQty" not in resp.text


def test_details_reports_explicit_type_and_family_with_provenance(api, monkeypatch):
    _stub_entity(monkeypatch, CANONICAL_WITH_TYPE_AND_FAMILY)
    monkeypatch.setattr(entity_ops, "get_ifc_class_for_global_id", lambda *_a: "IfcDoorType")

    body = api.get(f"/api/models/{MODEL_ID}/entities/{GID}/details").json()

    assert body["type"] == {
        "name": "DoorType_88x231",
        "global_id": "TYPE-GID",
        "ifc_class": "IfcDoorType",
        "predefined_type": "DOOR",
    }
    # Family carries its source pset/property for transparency (task13 §4).
    assert body["family"] == {
        "value": "88x231",
        "property_set": "Pset_DoorCommon",
        "property_name": "Reference",
    }
    assert body["availability"] == {
        "instance": True,
        "same_type": True,
        "same_family": True,
        "type_unavailable_reason": None,
        "family_unavailable_reason": None,
    }


def test_details_absent_type_and_family_is_a_valid_result_not_an_error(api, monkeypatch):
    """The current model has no useful IfcRelDefinesByType data — unavailable is
    expected and must degrade cleanly with a bounded reason (task13 §4)."""
    _stub_entity(monkeypatch, CANONICAL_NO_TYPE_NO_FAMILY, ifc_class="IfcWallStandardCase")

    resp = api.get(f"/api/models/{MODEL_ID}/entities/{GID}/details")
    assert resp.status_code == 200
    body = resp.json()

    # Omitted, not an empty placeholder.
    assert body["type"] is None
    assert body["family"] is None
    assert body["availability"]["same_type"] is False
    assert body["availability"]["same_family"] is False
    assert body["availability"]["type_unavailable_reason"]
    assert body["availability"]["family_unavailable_reason"]
    # Instance identity is always available.
    assert body["instance"]["ifc_class"] == "IfcWallStandardCase"


def test_details_never_infers_type_or_family_from_the_object_name(api, monkeypatch):
    """ "Basiswand:Wand_Bui_Spouw:305150" looks like a Revit family:type string.
    It must NOT be mined for type/family (task13 §4)."""
    _stub_entity(monkeypatch, CANONICAL_NO_TYPE_NO_FAMILY, ifc_class="IfcWallStandardCase")

    body = api.get(f"/api/models/{MODEL_ID}/entities/{GID}/details").json()

    assert body["instance"]["name"] == "Basiswand:Wand_Bui_Spouw:305150"
    assert body["type"] is None
    assert body["family"] is None


def test_details_never_returns_raw_canonical_json(api, monkeypatch):
    _stub_entity(monkeypatch, CANONICAL_WITH_TYPE_AND_FAMILY)
    monkeypatch.setattr(entity_ops, "get_ifc_class_for_global_id", lambda *_a: None)

    resp = api.get(f"/api/models/{MODEL_ID}/entities/{GID}/details")
    text = resp.text
    for internal_key in ("canonical_json", "property_sets", "quantity_sets", "placement", "meta"):
        assert internal_key not in text


def test_details_unknown_entity_is_404(api, monkeypatch):
    monkeypatch.setattr(entity_ops, "get_entity_canonical", lambda *_a: None)
    resp = api.get(f"/api/models/{MODEL_ID}/entities/NOPE/details")
    assert resp.status_code == 404


def test_details_cross_model_identity_is_404_without_revealing_existence(api, monkeypatch):
    """A GlobalId that exists in ANOTHER model must 404 exactly like one that
    does not exist at all (task13 §4)."""
    # The stub only resolves within MODEL_ID, mirroring the source_model_id-scoped query.
    _stub_entity(monkeypatch, CANONICAL_WITH_TYPE_AND_FAMILY)

    resp = api.get(f"/api/models/{MODEL_ID + 1}/entities/{GID}/details")
    assert resp.status_code == 404
    body = resp.json()
    assert body["detail"]["status"] == "unknown_entity"
    # The response must not hint that the entity lives in another model.
    assert "another" not in resp.text.lower()
    assert str(MODEL_ID) not in body["detail"]["message"]


# ---------------------------------------------------------------------------
# Highlight-group endpoint (task13 §5)
# ---------------------------------------------------------------------------


def _identity_result(gids, total=None, truncated=False):
    rows = [SimpleNamespace(global_id=g, ifc_class="IfcDoor") for g in gids]
    return entity_ops.ViewerIdentityResult(
        rows=rows,
        exact_total=total if total is not None else len(gids),
        truncated=truncated,
    )


def _post_group(client, scope, model_id=MODEL_ID, gid=GID):
    return client.post(
        f"/api/models/{model_id}/entities/highlight-group",
        json={"selected_global_id": gid, "scope": scope},
    )


def test_group_instance_scope_returns_only_the_selected_entity(api, monkeypatch):
    _stub_entity(monkeypatch, CANONICAL_WITH_TYPE_AND_FAMILY)
    monkeypatch.setattr(
        entity_ops,
        "match_instance",
        lambda *_a: (_identity_result([GID]), {"IfcDoor": 1}),
    )

    body = _post_group(api, "instance").json()
    assert body["available"] is True
    assert body["global_ids"] == [GID]
    assert body["total"] == 1
    assert body["truncated"] is False
    assert body["class_counts"] == {"IfcDoor": 1}


def test_group_type_scope_prefers_explicit_type_global_id(api, monkeypatch):
    _stub_entity(monkeypatch, CANONICAL_WITH_TYPE_AND_FAMILY)
    seen = {}

    def _by_gid(_s, model_id, type_gid, limit):
        seen["type_gid"] = type_gid
        return _identity_result(["A", "B", "C"]), {"IfcDoor": 3}

    monkeypatch.setattr(entity_ops, "match_by_type_global_id", _by_gid)
    monkeypatch.setattr(
        entity_ops,
        "match_by_type_name",
        lambda *_a: pytest.fail("must prefer the explicit type GlobalId"),
    )

    body = _post_group(api, "type").json()
    assert seen["type_gid"] == "TYPE-GID"
    assert body["available"] is True
    assert body["global_ids"] == ["A", "B", "C"]
    assert body["total"] == 3


def test_group_type_scope_falls_back_to_name_only_without_a_type_global_id(api, monkeypatch):
    canonical = dict(CANONICAL_WITH_TYPE_AND_FAMILY)
    canonical["type"] = {"name": "DoorType_88x231", "global_id": None, "predefined_type": "DOOR"}
    _stub_entity(monkeypatch, canonical)
    seen = {}

    def _by_name(_s, model_id, name, limit):
        seen["name"] = name
        return _identity_result(["A"]), {"IfcDoor": 1}

    monkeypatch.setattr(entity_ops, "match_by_type_name", _by_name)
    body = _post_group(api, "type").json()
    assert seen["name"] == "DoorType_88x231"
    assert body["available"] is True


def test_group_type_unavailable_when_model_has_no_explicit_type(api, monkeypatch):
    _stub_entity(monkeypatch, CANONICAL_NO_TYPE_NO_FAMILY)
    body = _post_group(api, "type").json()

    assert body["available"] is False
    assert body["unavailable_reason"]
    assert body["global_ids"] == []
    assert body["total"] == 0


def test_group_family_uses_the_selected_entitys_own_stored_property(api, monkeypatch):
    _stub_entity(monkeypatch, CANONICAL_WITH_TYPE_AND_FAMILY)
    seen = {}

    def _by_family(_s, model_id, pset, prop, value, limit):
        seen.update(pset=pset, prop=prop, value=value)
        return _identity_result(["A", "B"]), {"IfcDoor": 2}

    monkeypatch.setattr(entity_ops, "match_by_family", _by_family)
    body = _post_group(api, "family").json()

    # Tied to explicit stored family data, never a name-derived guess.
    assert seen == {"pset": "Pset_DoorCommon", "prop": "Reference", "value": "88x231"}
    assert body["available"] is True
    assert body["total"] == 2


def test_group_family_unavailable_when_no_allowlisted_property_exists(api, monkeypatch):
    _stub_entity(monkeypatch, CANONICAL_NO_TYPE_NO_FAMILY)
    body = _post_group(api, "family").json()
    assert body["available"] is False
    assert body["unavailable_reason"]


def test_group_reports_exact_total_above_the_identity_cap(api, monkeypatch):
    """Truncation caps the returned identities but never the exact total
    (task13 §5)."""
    _stub_entity(monkeypatch, CANONICAL_WITH_TYPE_AND_FAMILY)
    capped = [f"GID-{i}" for i in range(2000)]
    monkeypatch.setattr(
        entity_ops,
        "match_by_type_global_id",
        lambda *_a: (_identity_result(capped, total=5000, truncated=True), {"IfcDoor": 5000}),
    )

    body = _post_group(api, "type").json()
    assert len(body["global_ids"]) == 2000
    assert body["total"] == 5000  # exact, not reduced by the cap
    assert body["truncated"] is True
    assert body["class_counts"] == {"IfcDoor": 5000}


def test_group_passes_the_configured_viewer_cap_as_the_limit(api, monkeypatch):
    _stub_entity(monkeypatch, CANONICAL_WITH_TYPE_AND_FAMILY)
    seen = {}

    def _by_gid(_s, model_id, type_gid, limit):
        seen["limit"] = limit
        return _identity_result(["A"]), {"IfcDoor": 1}

    monkeypatch.setattr(entity_ops, "match_by_type_global_id", _by_gid)
    _post_group(api, "type")
    assert seen["limit"] == 2000


def test_group_unknown_entity_is_404(api, monkeypatch):
    monkeypatch.setattr(entity_ops, "get_entity_canonical", lambda *_a: None)
    assert _post_group(api, "instance", gid="NOPE").status_code == 404


def test_group_rejects_an_unsupported_scope(api, monkeypatch):
    _stub_entity(monkeypatch, CANONICAL_WITH_TYPE_AND_FAMILY)
    assert _post_group(api, "everything").status_code == 422


# ---------------------------------------------------------------------------
# Allowlist unit behavior (task13 §4)
# ---------------------------------------------------------------------------


def test_family_lookup_is_deterministic_across_property_sets():
    canonical = {
        "property_sets": {
            "Pset_Z": {"Family": {"value": "Z-family"}},
            "Pset_A": {"FamilyName": {"value": "A-family"}},
        }
    }
    # Deterministic (pset, property) ordering -> Pset_A wins, every time.
    for _ in range(3):
        fact = detail_ops.find_family(canonical)
        assert fact.property_set == "Pset_A"
        assert fact.value == "A-family"


def test_family_lookup_ignores_non_allowlisted_property_names():
    canonical = {"property_sets": {"Pset_X": {"LooksLikeAFamily": {"value": "nope"}}}}
    assert detail_ops.find_family(canonical) is None


def test_string_values_are_length_bounded():
    long_value = "x" * 5000
    canonical = {"property_sets": {"Pset_X": {"Reference": {"value": long_value}}}}
    fact = detail_ops.find_family(canonical)
    assert len(fact.value) == detail_ops.MAX_STRING_LEN


def test_property_selection_is_count_bounded():
    props = {f"FireRating{i}": {"value": str(i)} for i in range(100)}
    props.update({"FireRating": {"value": "30"}, "IsExternal": {"value": True}})
    canonical = {"property_sets": {"Pset_X": props}}
    # Only allowlisted names count, and the result is bounded regardless.
    selected = detail_ops.select_properties(canonical)
    assert len(selected) <= detail_ops.MAX_PROPERTY_VALUES


def test_malformed_canonical_json_does_not_raise():
    for bad in ({}, {"property_sets": None}, {"type": "not-a-dict"}, {"materials": "nope"}):
        assert detail_ops.find_family(bad) is None
        assert detail_ops.find_type(bad) is None
        assert detail_ops.select_properties(bad) == []
        assert detail_ops.select_materials(bad) == []
