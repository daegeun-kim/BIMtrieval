"""IFC-native measure types and unit registry (task27 §1, §2, §7.1).

Every model here is SYNTHETIC and built in memory. No production filename,
source-model id, exporter name, project name, or expected production count
appears anywhere — §1.2 forbids conditioning behaviour on any of them, and a
test that used one could not tell the difference between correct behaviour and a
model-specific special case.
"""

from __future__ import annotations

import json

import ifcopenshell
import pytest

from bim_rag.ifc_parser import EXTRACTION_VERSION, extract_canonical_json
from bim_rag.measures import (
    SUPPORTED_MEASURE_TYPES,
    MeasurementExtractor,
    build_unit_registry,
    measure_type_for_value_type,
)

_GID = iter(range(1, 10_000))


def _gid() -> str:
    """A syntactically valid, unique GlobalId. Content is irrelevant here."""
    return f"{next(_GID):022d}"


# ---------------------------------------------------------------------------
# Synthetic model builders
# ---------------------------------------------------------------------------


def _model(units: list | None = None, *, with_project: bool = True) -> ifcopenshell.file:
    f = ifcopenshell.file(schema="IFC4")
    if with_project:
        assignment = (
            f.create_entity("IfcUnitAssignment", Units=units) if units is not None else None
        )
        f.create_entity("IfcProject", GlobalId=_gid(), Name="P", UnitsInContext=assignment)
    return f


def _si(f, unit_type: str, name: str, prefix: str | None = None):
    return f.create_entity("IfcSIUnit", UnitType=unit_type, Prefix=prefix, Name=name)


def _imperial(f, unit_type: str, name: str, factor: float, component):
    conversion = f.create_entity(
        "IfcMeasureWithUnit",
        ValueComponent=f.create_entity("IfcLengthMeasure", factor),
        UnitComponent=component,
    )
    return f.create_entity(
        "IfcConversionBasedUnit",
        Dimensions=f.create_entity("IfcDimensionalExponents", 1, 0, 0, 0, 0, 0, 0),
        UnitType=unit_type,
        Name=name,
        ConversionFactor=conversion,
    )


def _mixed_default_model() -> ifcopenshell.file:
    """Defaults that deliberately DIFFER by family: mm, m², m³.

    This is the ordinary real-world case and the one the removed v001
    normalisation got wrong — it applied the LENGTH factor to areas and volumes
    and labelled the result metres.
    """
    f = _model([])
    units = [
        _si(f, "LENGTHUNIT", "METRE", "MILLI"),
        _si(f, "AREAUNIT", "SQUARE_METRE"),
        _si(f, "VOLUMEUNIT", "CUBIC_METRE"),
    ]
    f.by_type("IfcProject")[0].UnitsInContext.Units = units
    return f


def _attach_pset(f, element, set_name: str, properties: list) -> None:
    pset = f.create_entity(
        "IfcPropertySet", GlobalId=_gid(), Name=set_name, HasProperties=properties
    )
    f.create_entity(
        "IfcRelDefinesByProperties",
        GlobalId=_gid(),
        RelatedObjects=[element],
        RelatingPropertyDefinition=pset,
    )


def _attach_qset(f, element, set_name: str, quantities: list) -> None:
    qset = f.create_entity(
        "IfcElementQuantity", GlobalId=_gid(), Name=set_name, Quantities=quantities
    )
    f.create_entity(
        "IfcRelDefinesByProperties",
        GlobalId=_gid(),
        RelatedObjects=[element],
        RelatingPropertyDefinition=qset,
    )


def _single_value(f, name: str, value_type: str, value, unit=None):
    return f.create_entity(
        "IfcPropertySingleValue",
        Name=name,
        NominalValue=f.create_entity(value_type, value),
        Unit=unit,
    )


# ---------------------------------------------------------------------------
# Unit registry
# ---------------------------------------------------------------------------


def test_defaults_may_differ_by_measure_type():
    registry = build_unit_registry(_mixed_default_model())
    assert registry.symbol(registry.defaults["length"]) == "mm"
    assert registry.symbol(registry.defaults["area"]) == "m²"
    assert registry.symbol(registry.defaults["volume"]) == "m³"


def test_an_area_unit_is_never_derived_by_squaring_the_length_unit():
    """A millimetre model whose areas are square METRES must say so.

    Deriving `mm²` from the length default is the exact invalid inference §2.3
    removes, and it silently multiplies every area by a million.
    """
    registry = build_unit_registry(_mixed_default_model())
    assert registry.symbol(registry.defaults["area"]) == "m²"
    assert registry.symbol(registry.defaults["area"]) != "mm²"
    assert registry.symbol(registry.defaults["volume"]) != "mm³"


def test_imperial_unit_definitions_are_preserved_source_faithfully():
    f = _model([])
    inch = _si(f, "LENGTHUNIT", "METRE", "MILLI")
    units = [
        _imperial(f, "LENGTHUNIT", "FOOT", 304.8, inch),
        _imperial(f, "AREAUNIT", "SQUARE FOOT", 92903.04, inch),
        _imperial(f, "VOLUMEUNIT", "CUBIC FOOT", 28316846.6, inch),
    ]
    f.by_type("IfcProject")[0].UnitsInContext.Units = units

    registry = build_unit_registry(f)
    assert registry.symbol(registry.defaults["length"]) == "foot"
    assert registry.symbol(registry.defaults["area"]) == "square foot"
    assert registry.symbol(registry.defaults["volume"]) == "cubic foot"

    definition = registry.definition(registry.defaults["length"])
    assert definition["unit_kind"] == "conversion_based"
    assert definition["name"] == "FOOT"
    # The conversion factor is kept for identification only. Nothing in this
    # task converts with it — it is what lets a unit be told apart from another
    # unit that happens to share a name.
    assert definition["conversion"]["value"] == pytest.approx(304.8)


def test_a_missing_project_default_is_reported_as_unavailable():
    f = _model([])
    f.by_type("IfcProject")[0].UnitsInContext.Units = [_si(f, "LENGTHUNIT", "METRE", "MILLI")]
    registry = build_unit_registry(f)

    assert registry.defaults["length"] is not None
    assert registry.defaults["area"] is None
    assert registry.defaults["volume"] is None
    # An explicit unavailable state, not silence and not a substituted default.
    assert "AREAUNIT" in registry.unresolved_defaults["area"]
    assert "VOLUMEUNIT" in registry.unresolved_defaults["volume"]


def test_a_model_with_no_unit_assignment_has_no_defaults_at_all():
    f = _model(units=None)
    registry = build_unit_registry(f)
    assert all(registry.defaults[m] is None for m in SUPPORTED_MEASURE_TYPES)
    assert set(registry.unresolved_defaults) == set(SUPPORTED_MEASURE_TYPES)


def test_a_model_with_no_project_degrades_without_raising():
    registry = build_unit_registry(_model(with_project=False))
    assert all(registry.defaults[m] is None for m in SUPPORTED_MEASURE_TYPES)


def test_unit_keys_are_deterministic_and_definitions_de_duplicated():
    first = build_unit_registry(_mixed_default_model()).to_json()
    second = build_unit_registry(_mixed_default_model()).to_json()
    assert first == second
    # One definition per referenced unit — a per-value record refers to the key.
    assert len(first["definitions"]) == 3
    assert set(first["defaults"].values()) <= set(first["definitions"])


def test_the_registry_serializes_with_sorted_keys():
    payload = build_unit_registry(_mixed_default_model()).to_json()
    assert list(payload["definitions"]) == sorted(payload["definitions"])
    assert json.dumps(payload, sort_keys=True) == json.dumps(payload, sort_keys=True)


# ---------------------------------------------------------------------------
# Measure-type resolution
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("ifc_type", "expected"),
    [
        ("IfcLengthMeasure", "length"),
        ("IfcPositiveLengthMeasure", "length"),
        ("IfcNonNegativeLengthMeasure", "length"),
        ("IfcAreaMeasure", "area"),
        ("IfcVolumeMeasure", "volume"),
        # Other measure families are explicitly out of scope (§1.3).
        ("IfcMassMeasure", None),
        ("IfcPlaneAngleMeasure", None),
        ("IfcThermalTransmittanceMeasure", None),
        # Generic scalars are not measures, whatever they are named.
        ("IfcReal", None),
        ("IfcInteger", None),
        ("IfcLabel", None),
        (None, None),
    ],
)
def test_measure_type_comes_from_the_ifc_value_type(ifc_type, expected):
    assert measure_type_for_value_type(ifc_type) == expected


def test_typed_direct_attributes_are_captured_with_their_measure_type():
    f = _mixed_default_model()
    door = f.create_entity(
        "IfcDoor", GlobalId=_gid(), Name="D", OverallHeight=2100.0, OverallWidth=900.0
    )
    canonical, _ = extract_canonical_json(door, f, MeasurementExtractor(f))

    assert canonical["measurements"]["OverallHeight"] == {
        "value": 2100.0,
        "measure_type": "length",
        "provenance": "attribute",
    }
    assert canonical["measurements"]["OverallWidth"]["measure_type"] == "length"


def test_only_declared_measure_attributes_reach_the_measurement_container():
    """The container is bounded by the SCHEMA, not by a copy-everything rule."""
    f = _mixed_default_model()
    door = f.create_entity("IfcDoor", GlobalId=_gid(), Name="D", Tag="T-1", OverallHeight=2100.0)
    canonical, _ = extract_canonical_json(door, f, MeasurementExtractor(f))
    assert set(canonical["measurements"]) == {"OverallHeight"}


def test_typed_property_values_carry_their_measure_type():
    f = _mixed_default_model()
    wall = f.create_entity("IfcWall", GlobalId=_gid(), Name="W")
    _attach_pset(
        f,
        wall,
        "Pset_Anything",
        [
            _single_value(f, "SomeLength", "IfcPositiveLengthMeasure", 200.0),
            _single_value(f, "SomeArea", "IfcAreaMeasure", 12.5),
            _single_value(f, "SomeVolume", "IfcVolumeMeasure", 2.5),
        ],
    )
    canonical, _ = extract_canonical_json(wall, f, MeasurementExtractor(f))
    fields = canonical["property_sets"]["Pset_Anything"]

    assert fields["SomeLength"]["measure_type"] == "length"
    assert fields["SomeArea"]["measure_type"] == "area"
    assert fields["SomeVolume"]["measure_type"] == "volume"
    # Raw values are preserved exactly — nothing is scaled.
    assert fields["SomeArea"]["value"] == 12.5
    assert fields["SomeVolume"]["value"] == 2.5


def test_typed_physical_quantities_carry_their_measure_type():
    f = _mixed_default_model()
    slab = f.create_entity("IfcSlab", GlobalId=_gid(), Name="S")
    _attach_qset(
        f,
        slab,
        "Qto_Anything",
        [
            f.create_entity("IfcQuantityLength", Name="Perimeter", LengthValue=4200.0),
            f.create_entity("IfcQuantityArea", Name="GrossArea", AreaValue=18.0),
            f.create_entity("IfcQuantityVolume", Name="NetVolume", VolumeValue=3.6),
            # Out of scope: a count is not one of the three supported families.
            f.create_entity("IfcQuantityCount", Name="Pieces", CountValue=4.0),
        ],
    )
    canonical, _ = extract_canonical_json(slab, f, MeasurementExtractor(f))
    fields = canonical["quantity_sets"]["Qto_Anything"]

    assert fields["Perimeter"]["measure_type"] == "length"
    assert fields["GrossArea"]["measure_type"] == "area"
    assert fields["NetVolume"]["measure_type"] == "volume"
    assert "measure_type" not in fields["Pieces"]


def test_no_linear_factor_is_applied_to_an_area_or_a_volume():
    """The values stored are exactly the values the IFC holds.

    v001 multiplied every numeric quantity by one project LENGTH factor and
    emitted `normalized_unit="m"`. For an area or a volume that was simply
    wrong, so neither the scaling nor the label may survive anywhere.
    """
    f = _mixed_default_model()
    slab = f.create_entity("IfcSlab", GlobalId=_gid(), Name="S")
    _attach_qset(
        f,
        slab,
        "Qto_Anything",
        [
            f.create_entity("IfcQuantityArea", Name="GrossArea", AreaValue=18.0),
            f.create_entity("IfcQuantityVolume", Name="NetVolume", VolumeValue=3.6),
        ],
    )
    canonical, _ = extract_canonical_json(slab, f, MeasurementExtractor(f))
    fields = canonical["quantity_sets"]["Qto_Anything"]

    assert fields["GrossArea"]["value"] == 18.0
    assert fields["NetVolume"]["value"] == 3.6
    serialized = json.dumps(canonical)
    assert "normalized_value" not in serialized
    assert "normalized_unit" not in serialized
    assert "project_unit" not in serialized


def test_an_explicit_occurrence_unit_override_is_recorded():
    f = _mixed_default_model()
    override = _si(f, "LENGTHUNIT", "METRE")  # metres where the model default is mm
    wall = f.create_entity("IfcWall", GlobalId=_gid(), Name="W")
    _attach_pset(
        f,
        wall,
        "Pset_Anything",
        [_single_value(f, "SomeLength", "IfcLengthMeasure", 3.2, unit=override)],
    )
    extractor = MeasurementExtractor(f)
    canonical, _ = extract_canonical_json(wall, f, extractor)
    entry = canonical["property_sets"]["Pset_Anything"]["SomeLength"]

    assert entry["measure_type"] == "length"
    assert extractor.registry.symbol(entry["unit_override_key"]) == "m"


def test_no_override_key_is_written_when_there_is_no_override():
    """The default is not copied onto every value, and neither is a null.

    "no override" and "overridden to nothing" must stay distinguishable (§2.2).
    """
    f = _mixed_default_model()
    wall = f.create_entity("IfcWall", GlobalId=_gid(), Name="W")
    _attach_pset(
        f,
        wall,
        "Pset_Anything",
        [_single_value(f, "SomeLength", "IfcLengthMeasure", 3200.0)],
    )
    entry = extract_canonical_json(wall, f, MeasurementExtractor(f))[0]["property_sets"][
        "Pset_Anything"
    ]["SomeLength"]
    assert "unit_override_key" not in entry


@pytest.mark.parametrize("property_name", ["NetArea", "Width", "Height", "Volume", "Colour"])
def test_a_generic_real_stays_untyped_however_dimensional_its_name_reads(property_name):
    """§1.2: a `float` is not a measure, and a name is not evidence.

    Both spellings matter — a dimension-like name must not be promoted, and an
    unrelated name must not be either. If the rule were name-based, only the
    first of these would fail.
    """
    f = _mixed_default_model()
    wall = f.create_entity("IfcWall", GlobalId=_gid(), Name="W")
    _attach_pset(f, wall, "Pset_Anything", [_single_value(f, property_name, "IfcReal", 7.0)])
    entry = extract_canonical_json(wall, f, MeasurementExtractor(f))[0]["property_sets"][
        "Pset_Anything"
    ][property_name]

    assert entry["value"] == 7.0  # the raw value is still preserved
    assert "measure_type" not in entry
    assert "unit_override_key" not in entry


def test_extraction_is_deterministic_for_an_unchanged_model():
    f = _mixed_default_model()
    door = f.create_entity(
        "IfcDoor", GlobalId=_gid(), Name="D", OverallHeight=2100.0, OverallWidth=900.0
    )
    _attach_pset(
        f,
        door,
        "Pset_Anything",
        [_single_value(f, "SomeArea", "IfcAreaMeasure", 1.89)],
    )
    first = extract_canonical_json(door, f, MeasurementExtractor(f))[0]
    second = extract_canonical_json(door, f, MeasurementExtractor(f))[0]
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def test_the_extraction_version_is_carried_on_every_document():
    f = _mixed_default_model()
    wall = f.create_entity("IfcWall", GlobalId=_gid(), Name="W")
    canonical, _ = extract_canonical_json(wall, f, MeasurementExtractor(f))
    assert canonical["meta"]["extraction_version"] == EXTRACTION_VERSION
    assert EXTRACTION_VERSION != "v001"


def test_extraction_without_a_measure_context_produces_no_measure_metadata():
    """Honest absence, not an assumed default."""
    f = _mixed_default_model()
    wall = f.create_entity("IfcWall", GlobalId=_gid(), Name="W")
    _attach_pset(
        f,
        wall,
        "Pset_Anything",
        [_single_value(f, "SomeArea", "IfcAreaMeasure", 1.89)],
    )
    canonical, _ = extract_canonical_json(wall, f)
    assert canonical["measurements"] == {}
    assert "measure_type" not in canonical["property_sets"]["Pset_Anything"]["SomeArea"]


def test_diagnostics_count_typed_values_by_measure_type_and_provenance():
    f = _mixed_default_model()
    door = f.create_entity("IfcDoor", GlobalId=_gid(), Name="D", OverallHeight=2100.0)
    _attach_pset(f, door, "Pset_Anything", [_single_value(f, "SomeArea", "IfcAreaMeasure", 1.89)])
    _attach_qset(
        f,
        door,
        "Qto_Anything",
        [f.create_entity("IfcQuantityVolume", Name="NetVolume", VolumeValue=0.4)],
    )
    extractor = MeasurementExtractor(f)
    extract_canonical_json(door, f, extractor)
    diagnostics = extractor.diagnostics()

    assert diagnostics["typed_values_by_measure_type"] == {"area": 1, "length": 1, "volume": 1}
    assert diagnostics["typed_values_by_provenance"] == {
        "attribute": 1,
        "property": 1,
        "quantity": 1,
    }
    assert diagnostics["defaults"] == {"length": "mm", "area": "m²", "volume": "m³"}
