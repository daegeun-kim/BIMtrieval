"""The one deterministic unit decision (task27 §4.3, §7.3).

Pure functions, no database access. These replace the v001 `mm`-normalization
tests: there is no longer a conversion to test, because values stay in the units
the IFC used and a request in another unit is refused instead of converted.
"""

from __future__ import annotations

import pytest

from app.query.semantic.units import decide_unit, normalize_unit_token, units_equivalent

# ---------------------------------------------------------------------------
# Spelling normalization — orthography only, never a magnitude change
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("written", "canonical"),
    [
        ("m", "m"),
        ("metre", "m"),
        ("metres", "m"),
        ("meter", "m"),
        ("Meters", "m"),
        ("m.", "m"),
        ("mm", "mm"),
        ("millimetre", "mm"),
        ("m2", "m²"),
        ("M²", "m²"),
        ("sq m", "m²"),
        ("square metres", "m²"),
        ("m3", "m³"),
        ("cubic meter", "m³"),
        ("square foot", "square foot"),
        ("sqft", "square foot"),
        ("FT2", "square foot"),
        ("feet", "foot"),
    ],
)
def test_spelling_variants_fold_onto_one_canonical_unit(written, canonical):
    assert normalize_unit_token(written) == canonical


def test_different_units_never_fold_together():
    # The whole point of the table: it groups SPELLINGS, not scales. If `cm`
    # ever folded onto `m`, a request would execute with a 100x wrong magnitude.
    assert normalize_unit_token("cm") != normalize_unit_token("m")
    assert normalize_unit_token("mm") != normalize_unit_token("m")
    assert normalize_unit_token("m²") != normalize_unit_token("m³")
    assert normalize_unit_token("foot") != normalize_unit_token("square foot")


def test_an_unknown_unit_is_kept_comparable_rather_than_dropped():
    assert normalize_unit_token("furlongs") == "furlongs"
    assert units_equivalent("furlongs", "m") is False


def test_units_equivalent_needs_both_sides():
    assert units_equivalent(None, "m") is False
    assert units_equivalent("m", None) is False


# ---------------------------------------------------------------------------
# The decision itself
# ---------------------------------------------------------------------------


def _uniform(requested=None, unit="mm", measure="length"):
    return decide_unit(
        requested_unit=requested,
        effective_unit=unit,
        unit_state="uniform",
        measure_type=measure,
        label="Qto_WallBaseQuantities.Width",
    )


def test_a_unitless_number_uses_the_fields_own_unit_and_discloses_it():
    decision = _uniform()
    assert decision.ok is True
    assert decision.unit == "mm"
    assert "mm" in decision.note


def test_the_same_unit_spelled_differently_executes():
    decision = _uniform(requested="millimetres")
    assert decision.ok is True
    assert decision.unit == "mm"
    # The normalization is reported, so the user can see how it was read.
    assert decision.note is not None


def test_an_identical_spelling_needs_no_note():
    assert _uniform(requested="mm").note is None


def test_a_different_unit_is_refused_rather_than_converted():
    decision = _uniform(requested="m")
    assert decision.ok is False
    # The refusal must name the unit the model actually uses, or the user
    # cannot tell what to ask for instead.
    assert "mm" in decision.reason
    assert "not converted" in decision.reason


def test_a_mixed_unit_field_cannot_be_compared():
    decision = decide_unit(
        requested_unit=None,
        effective_unit=None,
        unit_state="mixed",
        measure_type="area",
        label="Pset_Test.NetArea",
        unit_limitation="recorded in 2 different units in this model",
    )
    assert decision.ok is False
    assert "2 different units" in decision.reason


def test_an_unknown_unit_field_cannot_be_compared():
    decision = decide_unit(
        requested_unit=None,
        effective_unit=None,
        unit_state="unknown",
        measure_type="volume",
        label="Pset_Test.NetVolume",
    )
    assert decision.ok is False
    assert decision.unit is None


def test_a_uniform_state_without_a_symbol_is_not_treated_as_uniform():
    decision = decide_unit(
        requested_unit=None,
        effective_unit=None,
        unit_state="uniform",
        measure_type="length",
        label="Pset_Test.Width",
    )
    assert decision.ok is False


def test_a_non_dimensional_number_compares_without_a_unit():
    decision = decide_unit(
        requested_unit=None,
        effective_unit=None,
        unit_state=None,
        measure_type=None,
        label="Pset_Test.NumberOfRisers",
    )
    assert decision.ok is True
    assert decision.unit is None
    assert decision.note is None


def test_a_unit_requested_against_a_non_dimensional_number_is_refused():
    decision = decide_unit(
        requested_unit="mm",
        effective_unit=None,
        unit_state=None,
        measure_type=None,
        label="Pset_Test.AreaLike",
    )
    assert decision.ok is False
    assert "no IFC measure type" in decision.reason
