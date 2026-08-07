"""Logical floor bands for the viewer's floor-plan control (task28 §2.1, §8.1).

Offline: the DB session dependency is overridden and the storey loader is
monkeypatched with synthetic `IfcBuildingStorey` rows, so no PostgreSQL, IFC
parse, viewer-asset read, OpenAI call, or embedding call occurs.

The endpoint must expose one record per existing logical `FloorBand` — never
one per raw storey — and its labels must use the same reference band the
natural-language floor interpretation counts from.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.api.app import app
from app.api.routes import models as models_route
from app.query.semantic import spatial as spatial_ops
from app.query.sql import catalog as catalog_ops

MODEL_ID = 7
FLOORS_URL = f"/api/models/{MODEL_ID}/floors"


@pytest.fixture()
def api(monkeypatch):
    app.dependency_overrides[models_route.get_db] = lambda: object()
    monkeypatch.setattr(
        catalog_ops,
        "get_model_asset_identity",
        lambda _s, mid: (
            SimpleNamespace(source_fingerprint="fp", status="available")
            if mid == MODEL_ID
            else None
        ),
    )
    yield TestClient(app)
    app.dependency_overrides.pop(models_route.get_db, None)


def _storeys(monkeypatch, *specs: tuple[str, str | None, float]) -> None:
    """Install synthetic storeys as (global_id, name, elevation) triples."""
    rows = [spatial_ops.Storey(global_id=g, name=n, elevation=e) for g, n, e in specs]
    rows.sort(key=lambda s: s.elevation)
    monkeypatch.setattr(spatial_ops, "load_storeys", lambda _s, _m: rows)


# ---------------------------------------------------------------------------
# Scoping, read-only guarantees, contract shape
# ---------------------------------------------------------------------------


def test_unknown_model_is_a_bounded_404(api, monkeypatch):
    _storeys(monkeypatch, ("A", "Level 0", 0.0))
    resp = api.get("/api/models/999/floors")
    assert resp.status_code == 404
    assert resp.json()["detail"]["status"] == "unknown_model"


def test_response_is_allowlisted_and_model_scoped(api, monkeypatch):
    _storeys(monkeypatch, ("A", "Level 0", 0.0), ("B", "Level 1", 3.0))
    body = api.get(FLOORS_URL).json()
    assert body["source_model_id"] == MODEL_ID
    assert set(body) == {
        "source_model_id",
        "available",
        "unavailable_reason",
        "reference_band_index",
        "reference_basis",
        "total_storeys",
        "floors",
    }
    assert set(body["floors"][0]) == {
        "band_index",
        "label",
        "is_reference",
        "storey_global_ids",
        "storey_names",
        "min_elevation",
        "max_elevation",
    }


def test_endpoint_is_read_only_and_llm_free(api, monkeypatch):
    """No IFC parse, viewer-asset read, LLM call, embedding, or DB write.

    Asserted structurally: `models.py`'s floor path reaches exactly two
    collaborators (the catalog identity lookup and the storey model), and the
    session object it is handed is an inert sentinel with no usable methods, so
    any statement or write would raise.
    """

    class Inert:
        def __getattr__(self, name):  # pragma: no cover - must never be reached
            raise AssertionError(f"the floors endpoint touched session.{name}")

    app.dependency_overrides[models_route.get_db] = lambda: Inert()
    _storeys(monkeypatch, ("A", None, 0.0))
    assert api.get(FLOORS_URL).status_code == 200


def test_get_only_no_mutating_verbs(api, monkeypatch):
    _storeys(monkeypatch, ("A", None, 0.0))
    for verb in (api.post, api.put, api.patch, api.delete):
        assert verb(FLOORS_URL).status_code == 405


# ---------------------------------------------------------------------------
# One record per LOGICAL band, not per raw storey
# ---------------------------------------------------------------------------


def test_sublevel_storeys_at_nearby_elevations_stay_one_floor(api, monkeypatch):
    """Three structural sub-levels a few centimetres apart are ONE button."""
    _storeys(
        monkeypatch,
        ("G-A", "01 ground - finish", 0.0),
        ("G-B", "01 ground - slab", -0.08),
        ("G-C", "01 ground - joist", -0.15),
        ("G-D", "02 first - finish", 3.0),
        ("G-E", "02 first - slab", 2.92),
    )
    body = api.get(FLOORS_URL).json()
    assert body["total_storeys"] == 5  # raw storeys
    assert len(body["floors"]) == 2  # logical floors
    assert body["floors"][0]["storey_global_ids"] == ["G-C", "G-B", "G-A"]
    assert body["floors"][1]["storey_global_ids"] == ["G-E", "G-D"]


def test_multi_wing_storeys_at_the_same_elevation_stay_one_floor(api, monkeypatch):
    _storeys(
        monkeypatch,
        ("W-N", "Level 1 North wing", 4.0),
        ("W-S", "Level 1 South wing", 4.0),
        ("W-E", "Level 1 East wing", 4.0),
        ("T", "Level 2", 8.0),
        ("Z", "Level 0", 0.0),
    )
    floors = api.get(FLOORS_URL).json()["floors"]
    assert len(floors) == 3
    assert sorted(floors[1]["storey_global_ids"]) == ["W-E", "W-N", "W-S"]


def test_bands_are_ordered_by_elevation_not_by_name(api, monkeypatch):
    """Names deliberately sort in the opposite order to the elevations."""
    _storeys(
        monkeypatch,
        ("A", "ZZZ lowest", 0.0),
        ("B", "MMM middle", 3.2),
        ("C", "AAA highest", 6.4),
    )
    floors = api.get(FLOORS_URL).json()["floors"]
    assert [f["band_index"] for f in floors] == [0, 1, 2]
    assert [f["storey_global_ids"] for f in floors] == [["A"], ["B"], ["C"]]
    assert [f["min_elevation"] for f in floors] == [0.0, 3.2, 6.4]


def test_a_single_logical_floor_remains_available(api, monkeypatch):
    _storeys(monkeypatch, ("ONLY", "Plan 00", 0.0))
    body = api.get(FLOORS_URL).json()
    assert body["available"] is True
    assert len(body["floors"]) == 1
    assert body["floors"][0]["label"] == "Floor 1"


# ---------------------------------------------------------------------------
# Labels use the SAME reference band as query floor interpretation
# ---------------------------------------------------------------------------


def test_labels_count_up_from_the_elevation_zero_reference_band(api, monkeypatch):
    _storeys(
        monkeypatch,
        ("R", "begane grond", 0.0),
        ("U1", "verdieping 1", 3.0),
        ("U2", "verdieping 2", 6.0),
    )
    body = api.get(FLOORS_URL).json()
    assert body["reference_basis"] == "elevation_zero"
    assert body["reference_band_index"] == 0
    assert [f["label"] for f in body["floors"]] == ["Floor 1", "Floor 2", "Floor 3"]
    assert [f["is_reference"] for f in body["floors"]] == [True, False, False]


def test_bands_below_the_reference_get_neutral_lower_level_labels(api, monkeypatch):
    _storeys(
        monkeypatch,
        ("D2", "kelder -2", -6.0),
        ("D1", "kelder -1", -3.0),
        ("R", "begane grond", 0.0),
        ("U1", "verdieping 1", 3.0),
    )
    body = api.get(FLOORS_URL).json()
    labels = [f["label"] for f in body["floors"]]
    assert labels == ["Lower level 2", "Lower level 1", "Floor 1", "Floor 2"]
    # No invented basement designation anywhere in the response.
    assert not any("asement" in label or "ellar" in label for label in labels)


def test_a_lowest_band_reference_labels_every_band_floor_1_upward(api, monkeypatch):
    """Site/project-datum elevations: no band at 0, so the lowest band is Floor 1."""
    _storeys(
        monkeypatch,
        ("A", "Plan 09", 11.4),
        ("B", "Plan 10", 14.6),
        ("C", "Plan 11", 17.8),
    )
    body = api.get(FLOORS_URL).json()
    assert body["reference_basis"] == "lowest_band"
    assert body["reference_band_index"] == 0
    assert [f["label"] for f in body["floors"]] == ["Floor 1", "Floor 2", "Floor 3"]


def test_labels_agree_with_the_natural_language_floor_interpretation(api, monkeypatch):
    """ "the second floor" and the button labelled "Floor 2" are the same band."""
    _storeys(
        monkeypatch,
        ("D1", "kelder", -3.2),
        ("R", "begane grond", 0.0),
        ("U1", "verdieping 1", 3.2),
    )
    body = api.get(FLOORS_URL).json()
    by_label = {f["label"]: f["storey_global_ids"] for f in body["floors"]}

    resolution = spatial_ops.resolve_floor_concept(object(), MODEL_ID, "the second floor")
    assert resolution.resolved is True
    assert by_label["Floor 2"] == resolution.storey_global_ids


# ---------------------------------------------------------------------------
# Honest unavailable state + descriptive-only storey names
# ---------------------------------------------------------------------------


def test_no_usable_storey_elevations_returns_an_honest_empty_state(api, monkeypatch):
    _storeys(monkeypatch)  # load_storeys drops rows without a numeric elevation
    body = api.get(FLOORS_URL).json()
    assert body["available"] is False
    assert body["floors"] == []
    assert body["reference_band_index"] is None
    assert body["reference_basis"] == "none"
    assert "IfcBuildingStorey" in (body["unavailable_reason"] or "")


def test_source_storey_names_are_descriptive_only_and_bounded(api, monkeypatch):
    """Names are carried for tooltips; they never label, group, or order."""
    _storeys(
        monkeypatch,
        *[(f"S{i}", f"sub-level {i}", i * 0.02) for i in range(12)],
        ("UP", "Level 2", 3.5),
    )
    floors = api.get(FLOORS_URL).json()["floors"]
    from app.api.schemas.models import MAX_FLOOR_STOREY_NAMES

    assert len(floors[0]["storey_global_ids"]) == 12  # every identity kept
    assert len(floors[0]["storey_names"]) == MAX_FLOOR_STOREY_NAMES  # names bounded
    assert floors[0]["label"] == "Floor 1"  # not "sub-level 0"


def test_unnamed_storeys_do_not_break_the_contract(api, monkeypatch):
    _storeys(monkeypatch, ("A", None, 0.0), ("B", None, 3.0))
    floors = api.get(FLOORS_URL).json()["floors"]
    assert [f["storey_names"] for f in floors] == [[], []]
    assert [f["label"] for f in floors] == ["Floor 1", "Floor 2"]


# ---------------------------------------------------------------------------
# The shared label helper itself
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("band_index", "reference_index", "expected"),
    [
        (0, 0, "Floor 1"),
        (1, 0, "Floor 2"),
        (9, 0, "Floor 10"),
        (2, 2, "Floor 1"),
        (3, 2, "Floor 2"),
        (1, 2, "Lower level 1"),
        (0, 2, "Lower level 2"),
        (0, None, "Floor 1"),
    ],
)
def test_band_label_is_pure_and_reference_relative(band_index, reference_index, expected):
    assert spatial_ops.band_label(band_index, reference_index) == expected
