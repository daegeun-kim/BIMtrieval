"""Unit-normalization mechanism (spec_v002 §9.1, spec_v003 §10). Pure function,
no database access — exercised against synthetic quantity_sets entries since
the currently-ingested model has none populated (see query_live tests for the
live 'absent' confirmation)."""

from __future__ import annotations

from app.query.sql.field_registry import normalize_quantity_value


def test_mm_conversion_from_normalized_meters():
    value, warning = normalize_quantity_value(
        {"normalized_unit": "m", "normalized_value": 0.9}, "mm"
    )
    assert value == 900.0
    assert warning is None


def test_mm_conversion_missing_normalized_value_reports_reason_not_zero():
    value, warning = normalize_quantity_value({"value": 900}, "mm")
    assert value is None
    assert warning is not None


def test_mm_conversion_wrong_normalized_unit_reports_reason():
    value, warning = normalize_quantity_value(
        {"normalized_unit": "ft", "normalized_value": 3.0}, "mm"
    )
    assert value is None
    assert warning is not None


def test_area_conversion_honestly_unsupported():
    """Ingestion only computes a linear length factor — squaring/cubing it
    would be mathematically wrong, so this must not fabricate a value."""
    value, warning = normalize_quantity_value(
        {"normalized_unit": "m", "normalized_value": 4.0}, "mm2"
    )
    assert value is None
    assert "not available" in warning


def test_volume_conversion_honestly_unsupported():
    value, warning = normalize_quantity_value(
        {"normalized_unit": "m", "normalized_value": 4.0}, "mm3"
    )
    assert value is None
    assert "not available" in warning


def test_degrees_conversion_honestly_unsupported():
    value, warning = normalize_quantity_value(
        {"normalized_unit": "m", "normalized_value": 1.5}, "degrees"
    )
    assert value is None
    assert warning is not None


def test_unsupported_target_unit():
    value, warning = normalize_quantity_value(
        {"normalized_unit": "m", "normalized_value": 1.0}, "furlongs"
    )
    assert value is None
    assert "unsupported" in warning
