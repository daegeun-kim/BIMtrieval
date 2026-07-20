"""Model-independent storey-band resolution (Task 23 §1).

These tests use synthetic storey sets only — no model names, no per-model rules,
no database — so they prove the resolver depends purely on elevation structure.
"""

from __future__ import annotations

import pytest

from app.query.semantic.spatial import (
    Storey,
    build_bands,
    mentions_floor_concept,
)


def _storeys(*elevations: float) -> list[Storey]:
    return [
        Storey(global_id=f"gid{i}", name=f"name{i}", elevation=e)
        for i, e in enumerate(sorted(elevations))
    ]


def test_storeys_far_apart_are_separate_bands():
    bands = build_bands(_storeys(0.0, 3000.0, 6000.0))
    assert [len(b.storeys) for b in bands] == [1, 1, 1]


def test_clean_one_storey_per_floor_model_keeps_every_floor():
    """Regression: a model with uniform floor spacing and no sub-levels must NOT
    collapse into a single band. A median-gap rule fails exactly here, because
    its median gap IS a floor gap."""
    bands = build_bands(_storeys(0.0, 3000.0, 6000.0, 9000.0, 12000.0))
    assert len(bands) == 5


def test_irregular_floor_heights_still_separate():
    bands = build_bands(_storeys(0.0, 2800.0, 6200.0, 9100.0, 12500.0))
    assert len(bands) == 5


def test_double_height_space_does_not_merge_floors():
    bands = build_bands(_storeys(0.0, 3000.0, 6000.0, 12000.0))
    assert len(bands) == 4


def test_basement_is_its_own_band():
    bands = build_bands(_storeys(-3000.0, 0.0, 3000.0, 6000.0))
    assert len(bands) == 4


def test_sublevels_of_one_floor_collapse_into_one_band():
    """Finished level + underside-of-slab + underside-of-joist are ONE floor."""
    bands = build_bands(_storeys(0.0, 20.0, 130.0, 3000.0, 3020.0, 3140.0))
    assert len(bands) == 2
    assert [len(b.storeys) for b in bands] == [3, 3]


def test_multiple_wings_at_one_level_are_one_band_not_ambiguity():
    """Same floor across several buildings/wings -> one band, OR-ed together."""
    bands = build_bands(_storeys(0.0, 100.0, 250.0, 400.0, 4000.0, 4100.0))
    assert len(bands) == 2
    assert len(bands[0].storeys) == 4
    assert len(bands[0].global_ids) == 4


def test_banding_is_scale_free():
    """Identical structure in millimetres and in metres must band identically."""
    mm = build_bands(_storeys(0.0, 20.0, 130.0, 3000.0, 3020.0, 3140.0))
    m = build_bands(_storeys(0.0, 0.02, 0.13, 3.0, 3.02, 3.14))
    assert [len(b.storeys) for b in mm] == [len(b.storeys) for b in m]


def test_banding_is_independent_of_names():
    """Renaming every storey cannot change the derived structure."""
    a = build_bands(_storeys(0.0, 50.0, 3000.0))
    renamed = [
        Storey(global_id=s.global_id, name="totally different", elevation=s.elevation)
        for s in _storeys(0.0, 50.0, 3000.0)
    ]
    b = build_bands(renamed)
    assert [len(x.storeys) for x in a] == [len(x.storeys) for x in b]


def test_single_storey_model_is_one_band():
    assert len(build_bands(_storeys(0.0))) == 1


def test_no_storeys_yields_no_bands():
    assert build_bands([]) == []


def test_identical_elevations_form_one_band():
    bands = build_bands(_storeys(2500.0, 2500.0, 2500.0))
    assert len(bands) == 1
    assert len(bands[0].storeys) == 3


@pytest.mark.parametrize(
    "text,expected",
    [
        ("the second floor", True),
        ("level 3", True),
        ("top storey", True),
        ("fire rating", False),
        ("external walls", False),
    ],
)
def test_floor_concept_detection(text, expected):
    assert mentions_floor_concept(text) is expected
