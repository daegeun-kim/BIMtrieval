"""IFC-native dimensional measure types and unit registry (task27 §1, §2).

Scope is deliberately three families — **length**, **area**, **volume** — and the
authority for all three is the IFC schema and the IFC unit graph, never a field
name. A `float` is not a measure; `IfcLengthMeasure` is.

Three source facts are recognised, and only these:

- a direct entity attribute whose SCHEMA-DECLARED type resolves to a supported
  measure (`IfcDoor.OverallHeight` is an `IfcPositiveLengthMeasure`);
- an `IfcPropertySingleValue` whose wrapped `NominalValue` is a supported
  measure type;
- an `IfcPhysicalSimpleQuantity` subtype for length, area, or volume.

Anything else — `IfcReal`, `IfcInteger`, a string, a plain Python number — keeps
its raw value and gets NO measure type and NO unit, however dimensional its name
sounds. That is the correct standards-based outcome (§1.2), and it is what stops
a flattened exporter bag from being mistaken for measured data.

Units are PRESERVED, not converted (§2). The model's own unit definitions are
stored once per source model; a value records only its measure type plus an
explicit occurrence override when the IFC actually supplies one. The effective
unit of a value is therefore::

    unit_override_key   otherwise   defaults[measure_type]

No linear factor is applied to anything, and an area is never derived by
squaring a length unit — that invalid normalisation is what §2.3 removes.
"""

from __future__ import annotations

import math
import re
from typing import Any, Iterable, Iterator

import ifcopenshell
import ifcopenshell.util.element as ifc_util

__all__ = [
    "MEASURE_AREA",
    "MEASURE_LENGTH",
    "MEASURE_VOLUME",
    "SUPPORTED_MEASURE_TYPES",
    "UNIT_CONTRACT_VERSION",
    "MeasurementExtractor",
    "UnitRegistry",
    "build_unit_registry",
    "measure_type_for_value_type",
]

#: Bump when the SHAPE of the stored unit registry changes.
UNIT_CONTRACT_VERSION = "v001"

MEASURE_LENGTH = "length"
MEASURE_AREA = "area"
MEASURE_VOLUME = "volume"

#: Exactly the families this task supports. A later task may add another one;
#: nothing here is written so that adding one requires rewriting the rest.
SUPPORTED_MEASURE_TYPES: tuple[str, ...] = (MEASURE_LENGTH, MEASURE_AREA, MEASURE_VOLUME)

#: The IFC unit type that carries each family's project default.
IFC_UNIT_TYPE_BY_MEASURE: dict[str, str] = {
    MEASURE_LENGTH: "LENGTHUNIT",
    MEASURE_AREA: "AREAUNIT",
    MEASURE_VOLUME: "VOLUMEUNIT",
}

#: IFC defined measure types, by family. These are schema type names, so the
#: mapping is a property of IFC itself rather than of any model or exporter.
_MEASURE_BY_VALUE_TYPE: dict[str, str] = {
    "IfcLengthMeasure": MEASURE_LENGTH,
    "IfcPositiveLengthMeasure": MEASURE_LENGTH,
    "IfcNonNegativeLengthMeasure": MEASURE_LENGTH,
    "IfcAreaMeasure": MEASURE_AREA,
    "IfcPositiveAreaMeasure": MEASURE_AREA,
    "IfcVolumeMeasure": MEASURE_VOLUME,
    "IfcPositiveVolumeMeasure": MEASURE_VOLUME,
}

#: `IfcPhysicalSimpleQuantity` subtypes, by family. Count, weight, and time
#: quantities are deliberately absent — they are other measure families (§1.3).
_MEASURE_BY_QUANTITY_CLASS: dict[str, str] = {
    "IfcQuantityLength": MEASURE_LENGTH,
    "IfcQuantityArea": MEASURE_AREA,
    "IfcQuantityVolume": MEASURE_VOLUME,
}

#: SI base-unit display symbols for the supported families.
_SI_UNIT_SYMBOLS: dict[str, str] = {
    "METRE": "m",
    "METER": "m",
    "SQUARE_METRE": "m²",
    "SQUARE_METER": "m²",
    "CUBIC_METRE": "m³",
    "CUBIC_METER": "m³",
}

#: SI prefix display symbols, exactly as the IFC `IfcSIPrefix` enumeration.
_SI_PREFIX_SYMBOLS: dict[str, str] = {
    "EXA": "E",
    "PETA": "P",
    "TERA": "T",
    "GIGA": "G",
    "MEGA": "M",
    "KILO": "k",
    "HECTO": "h",
    "DECA": "da",
    "DECI": "d",
    "CENTI": "c",
    "MILLI": "m",
    "MICRO": "µ",
    "NANO": "n",
    "PICO": "p",
    "FEMTO": "f",
    "ATTO": "a",
}

_WHITESPACE = re.compile(r"\s+")
#: Guard: a pathological schema loop must not hang extraction.
_MAX_TYPE_CHAIN = 12


# ---------------------------------------------------------------------------
# Measure-type resolution
# ---------------------------------------------------------------------------


def measure_type_for_value_type(ifc_type_name: str | None) -> str | None:
    """The supported family for an IFC value type name, or None.

    `None` is the answer for every generic scalar. `IfcReal` named `NetArea` is
    still `None`: §1.2 forbids promoting an untyped number by its name.
    """
    if not ifc_type_name:
        return None
    return _MEASURE_BY_VALUE_TYPE.get(ifc_type_name)


def _measure_type_of_wrapped(value: Any) -> str | None:
    """The family declared by a wrapped IFC value (`NominalValue`, etc.)."""
    is_a = getattr(value, "is_a", None)
    if not callable(is_a):
        return None
    try:
        return _MEASURE_BY_VALUE_TYPE.get(is_a())
    except Exception:  # noqa: BLE001 - a value we cannot type is simply untyped
        return None


def _measure_type_of_attribute(attribute: Any) -> str | None:
    """The family declared by a schema attribute, by walking its type chain.

    `IfcDoor.OverallHeight` declares `IfcPositiveLengthMeasure`, which declares
    `IfcLengthMeasure`, which declares a real. Walking the chain means a model
    using either spelling resolves identically, and an aggregation or entity
    reference resolves to nothing rather than being guessed at.
    """
    try:
        node = attribute.type_of_attribute()
    except Exception:  # noqa: BLE001
        return None
    for _ in range(_MAX_TYPE_CHAIN):
        if node is None:
            return None
        name_fn = getattr(node, "name", None)
        if callable(name_fn):
            try:
                family = _MEASURE_BY_VALUE_TYPE.get(name_fn())
            except Exception:  # noqa: BLE001
                family = None
            if family:
                return family
        declared = getattr(node, "declared_type", None)
        if not callable(declared):
            return None
        try:
            node = declared()
        except Exception:  # noqa: BLE001
            return None
    return None


# ---------------------------------------------------------------------------
# Unit registry
# ---------------------------------------------------------------------------


def _clean_label(value: Any) -> str | None:
    if value is None:
        return None
    text = _WHITESPACE.sub(" ", str(value)).strip()
    return text or None


def _si_symbol(prefix: str | None, name: str | None) -> str | None:
    base = _SI_UNIT_SYMBOLS.get((name or "").upper())
    if base is None:
        return None
    if not prefix:
        return base
    prefix_symbol = _SI_PREFIX_SYMBOLS.get(prefix.upper())
    if prefix_symbol is None:
        return None
    return f"{prefix_symbol}{base}"


def _numeric(value: Any) -> float | None:
    inner = getattr(value, "wrappedValue", value)
    if isinstance(inner, bool) or not isinstance(inner, (int, float)):
        return None
    if isinstance(inner, float) and (math.isnan(inner) or math.isinf(inner)):
        return None
    return float(inner)


def _unit_definition(unit: Any) -> dict[str, Any] | None:
    """A source-faithful, JSON-safe description of one IFC unit.

    Carries enough to identify and display the unit without guessing: the IFC
    unit type, its SI / conversion-based identity, the prefix and name as
    written, and a deterministic display symbol. A unit whose symbol cannot be
    derived is recorded with `resolved: false` rather than given a made-up one.
    """
    is_a = getattr(unit, "is_a", None)
    if not callable(is_a):
        return None

    unit_type = _clean_label(getattr(unit, "UnitType", None))

    if unit.is_a("IfcSIUnit"):
        prefix = _clean_label(getattr(unit, "Prefix", None))
        name = _clean_label(getattr(unit, "Name", None))
        symbol = _si_symbol(prefix, name)
        definition: dict[str, Any] = {
            "unit_kind": "si",
            "ifc_unit_type": unit_type,
            "si_name": name,
            "resolved": symbol is not None,
        }
        if prefix:
            definition["prefix"] = prefix
        if symbol is not None:
            definition["symbol"] = symbol
        return definition

    if unit.is_a("IfcConversionBasedUnit"):
        name = _clean_label(getattr(unit, "Name", None))
        definition = {
            "unit_kind": "conversion_based",
            "ifc_unit_type": unit_type,
            "name": name,
            "resolved": name is not None,
        }
        if name is not None:
            # Source-faithful display: the IFC's own name, whitespace-collapsed
            # and case-folded. No exporter-specific or model-specific mapping.
            definition["symbol"] = name.casefold()
        factor = getattr(unit, "ConversionFactor", None)
        if factor is not None:
            value = _numeric(getattr(factor, "ValueComponent", None))
            component = getattr(factor, "UnitComponent", None)
            conversion: dict[str, Any] = {}
            if value is not None:
                conversion["value"] = value
            component_definition = _unit_definition(component) if component is not None else None
            if component_definition is not None:
                conversion["unit_symbol"] = component_definition.get("symbol")
                conversion["unit_kind"] = component_definition.get("unit_kind")
            if conversion:
                definition["conversion"] = conversion
        return definition

    if unit.is_a("IfcContextDependentUnit"):
        return {
            "unit_kind": "context_dependent",
            "ifc_unit_type": unit_type,
            "name": _clean_label(getattr(unit, "Name", None)),
            "resolved": False,
        }

    if unit.is_a("IfcDerivedUnit"):
        return {
            "unit_kind": "derived",
            "ifc_unit_type": unit_type,
            "name": _clean_label(getattr(unit, "UserDefinedType", None)),
            "resolved": False,
        }

    if unit.is_a("IfcMonetaryUnit"):
        return None

    return None


def _definition_slug(definition: dict[str, Any]) -> str:
    unit_type = (definition.get("ifc_unit_type") or "unit").lower()
    symbol = definition.get("symbol") or definition.get("name") or "unresolved"
    return f"{unit_type}:{str(symbol).casefold()}"


class UnitRegistry:
    """De-duplicated unit definitions for ONE source model (§2.1).

    Definitions are stored once and referenced by a stable internal key, so a
    per-value record never repeats a whole unit definition.
    """

    def __init__(self) -> None:
        self._definitions: dict[str, dict[str, Any]] = {}
        self._key_by_instance: dict[int, str | None] = {}
        self.defaults: dict[str, str | None] = dict.fromkeys(SUPPORTED_MEASURE_TYPES, None)
        self.unresolved_defaults: dict[str, str] = {}

    # -- registration ------------------------------------------------------

    def register(self, unit: Any) -> str | None:
        """Register `unit` and return its stable key, or None if unusable."""
        if unit is None:
            return None
        instance_id = None
        try:
            instance_id = unit.id()
        except Exception:  # noqa: BLE001 - a unit without an id still resolves below
            instance_id = None
        if instance_id is not None and instance_id in self._key_by_instance:
            return self._key_by_instance[instance_id]

        definition = _unit_definition(unit)
        key = self._register_definition(definition) if definition is not None else None
        if instance_id is not None:
            self._key_by_instance[instance_id] = key
        return key

    def _register_definition(self, definition: dict[str, Any]) -> str:
        slug = _definition_slug(definition)
        candidate = slug
        suffix = 1
        while candidate in self._definitions:
            if self._definitions[candidate] == definition:
                return candidate
            suffix += 1
            candidate = f"{slug}#{suffix}"
        self._definitions[candidate] = definition
        return candidate

    def set_default(self, measure_type: str, unit: Any) -> str | None:
        key = self.register(unit)
        if key is None:
            self.unresolved_defaults[measure_type] = (
                f"the {IFC_UNIT_TYPE_BY_MEASURE[measure_type]} declared by "
                "IfcProject.UnitsInContext could not be resolved to a usable unit definition"
            )
            return None
        self.defaults[measure_type] = key
        return key

    def mark_default_unavailable(self, measure_type: str, reason: str) -> None:
        self.defaults[measure_type] = None
        self.unresolved_defaults[measure_type] = reason

    # -- lookup ------------------------------------------------------------

    def definition(self, key: str | None) -> dict[str, Any] | None:
        return self._definitions.get(key) if key else None

    def symbol(self, key: str | None) -> str | None:
        definition = self.definition(key)
        return definition.get("symbol") if definition else None

    def effective_key(self, measure_type: str | None, override_key: str | None) -> str | None:
        """`override_key` otherwise the model default. Never a guess."""
        if override_key:
            return override_key
        if measure_type is None:
            return None
        return self.defaults.get(measure_type)

    # -- serialization -----------------------------------------------------

    def to_json(self) -> dict[str, Any]:
        """The registry as stored in `ifc_source_models.extraction_metadata`.

        Deterministic: every mapping is key-sorted so two runs over the same IFC
        produce byte-identical metadata.
        """
        payload: dict[str, Any] = {
            "contract_version": UNIT_CONTRACT_VERSION,
            "defaults": {m: self.defaults[m] for m in SUPPORTED_MEASURE_TYPES},
            "definitions": {k: self._definitions[k] for k in sorted(self._definitions)},
        }
        if self.unresolved_defaults:
            payload["unresolved_defaults"] = {
                k: self.unresolved_defaults[k] for k in sorted(self.unresolved_defaults)
            }
        return payload


def build_unit_registry(ifc_model: ifcopenshell.file) -> UnitRegistry:
    """Read `IfcProject.UnitsInContext` into a de-duplicated unit registry.

    A model that declares no project, no unit assignment, or no unit for a
    family gets an explicit unavailable state for it — never a substituted or
    assumed default (§2.1).
    """
    registry = UnitRegistry()

    projects = []
    try:
        projects = ifc_model.by_type("IfcProject")
    except Exception:  # noqa: BLE001 - a model without IfcProject degrades below
        projects = []

    assignment = None
    if projects:
        # Deterministic: lowest STEP id wins if a file declares several.
        project = sorted(projects, key=lambda p: p.id())[0]
        assignment = getattr(project, "UnitsInContext", None)

    if assignment is None:
        for measure_type in SUPPORTED_MEASURE_TYPES:
            registry.mark_default_unavailable(
                measure_type,
                "this model declares no IfcProject.UnitsInContext, so no project default "
                f"{IFC_UNIT_TYPE_BY_MEASURE[measure_type]} is available",
            )
        return registry

    units = list(getattr(assignment, "Units", None) or [])
    by_unit_type: dict[str, Any] = {}
    for unit in units:
        unit_type = _clean_label(getattr(unit, "UnitType", None))
        if unit_type and unit_type not in by_unit_type:
            by_unit_type[unit_type] = unit

    for measure_type in SUPPORTED_MEASURE_TYPES:
        unit = by_unit_type.get(IFC_UNIT_TYPE_BY_MEASURE[measure_type])
        if unit is None:
            registry.mark_default_unavailable(
                measure_type,
                "IfcProject.UnitsInContext declares no "
                f"{IFC_UNIT_TYPE_BY_MEASURE[measure_type]}, so this model has no project "
                f"default {measure_type} unit",
            )
            continue
        registry.set_default(measure_type, unit)

    return registry


# ---------------------------------------------------------------------------
# Per-entity measurement extraction
# ---------------------------------------------------------------------------


def _property_definitions(relating: Any) -> Iterator[Any]:
    """`RelatingPropertyDefinition` is a single object in IFC2X3 and may be a
    set in IFC4. Both shapes yield the same definitions."""
    if relating is None:
        return
    if isinstance(relating, (list, tuple)):
        for item in relating:
            yield item
        return
    yield relating


class MeasurementExtractor:
    """Model-scoped resolver for supported measure types and their units.

    Built ONCE per IFC file: the unit registry and the per-class schema
    attribute map are both model-wide, and rebuilding them per entity would
    dominate import time on a large model.
    """

    def __init__(self, ifc_model: ifcopenshell.file) -> None:
        self.model = ifc_model
        self.registry = build_unit_registry(ifc_model)
        self._schema = _load_schema(ifc_model)
        self._attribute_fields: dict[str, tuple[tuple[str, str], ...]] = {}
        self._container_cache: dict[int, dict[str, tuple[str, str | None]]] = {}
        #: Counts for the ingestion report, by (measure_type, provenance).
        self.typed_value_counts: dict[tuple[str, str], int] = {}

    # -- direct attributes -------------------------------------------------

    def attribute_measure_fields(self, ifc_class: str) -> tuple[tuple[str, str], ...]:
        """Schema-declared supported measure attributes for one class."""
        cached = self._attribute_fields.get(ifc_class)
        if cached is not None:
            return cached
        fields: list[tuple[str, str]] = []
        if self._schema is not None:
            try:
                declaration = self._schema.declaration_by_name(ifc_class)
                for attribute in declaration.all_attributes():
                    family = _measure_type_of_attribute(attribute)
                    if family:
                        fields.append((attribute.name(), family))
            except Exception:  # noqa: BLE001 - an unbundled schema degrades to none
                fields = []
        result = tuple(sorted(fields))
        self._attribute_fields[ifc_class] = result
        return result

    def measurements_for(self, entity: ifcopenshell.entity_instance) -> dict[str, Any]:
        """The bounded measurement-attribute container for one entity (§2.2).

        Only direct attributes with a declared supported IFC measure type appear
        here. Arbitrary entity attributes are never copied in.
        """
        out: dict[str, Any] = {}
        for attribute_name, measure_type in self.attribute_measure_fields(entity.is_a()):
            try:
                raw = getattr(entity, attribute_name, None)
            except Exception:  # noqa: BLE001
                continue
            value = _numeric(raw)
            if value is None:
                continue
            out[attribute_name] = {
                "value": value,
                "measure_type": measure_type,
                "provenance": "attribute",
            }
            self._count(measure_type, "attribute")
        return out

    # -- property / quantity containers ------------------------------------

    def property_measures(
        self, entity: ifcopenshell.entity_instance
    ) -> dict[tuple[str, str], tuple[str, str | None]]:
        """`(pset_name, property_name) -> (measure_type, unit_override_key)`."""
        return self._container_measures(entity, "IfcPropertySet")

    def quantity_measures(
        self, entity: ifcopenshell.entity_instance
    ) -> dict[tuple[str, str], tuple[str, str | None]]:
        """`(qset_name, quantity_name) -> (measure_type, unit_override_key)`."""
        return self._container_measures(entity, "IfcElementQuantity")

    def _container_measures(
        self, entity: ifcopenshell.entity_instance, wanted: str
    ) -> dict[tuple[str, str], tuple[str, str | None]]:
        out: dict[tuple[str, str], tuple[str, str | None]] = {}
        # Type-level containers first, so an occurrence's own container wins —
        # the same precedence `ifcopenshell.util.element.get_psets` applies.
        for definition in self._iter_containers(entity, wanted):
            name = _clean_label(getattr(definition, "Name", None))
            if not name:
                continue
            for field_name, resolved in self._container_fields(definition, wanted).items():
                out[(name, field_name)] = resolved
        return out

    def _iter_containers(self, entity: ifcopenshell.entity_instance, wanted: str) -> Iterable[Any]:
        containers: list[Any] = []
        try:
            type_object = ifc_util.get_type(entity)
        except Exception:  # noqa: BLE001
            type_object = None
        if type_object is not None:
            for definition in getattr(type_object, "HasPropertySets", None) or []:
                if definition is not None and definition.is_a(wanted):
                    containers.append(definition)
        for rel in getattr(entity, "IsDefinedBy", None) or []:
            try:
                if not rel.is_a("IfcRelDefinesByProperties"):
                    continue
            except Exception:  # noqa: BLE001
                continue
            for definition in _property_definitions(
                getattr(rel, "RelatingPropertyDefinition", None)
            ):
                if definition is not None and definition.is_a(wanted):
                    containers.append(definition)
        return containers

    def _container_fields(self, definition: Any, wanted: str) -> dict[str, tuple[str, str | None]]:
        """Supported measure fields of one container instance, cached by STEP id.

        Type-level containers are shared by every occurrence of the type, so
        caching here is what keeps this proportional to the number of distinct
        containers rather than to entities x containers.
        """
        try:
            instance_id = definition.id()
        except Exception:  # noqa: BLE001
            instance_id = None
        if instance_id is not None:
            cached = self._container_cache.get(instance_id)
            if cached is not None:
                return cached

        fields: dict[str, tuple[str, str | None]] = {}
        if wanted == "IfcPropertySet":
            for prop in getattr(definition, "HasProperties", None) or []:
                resolved = self._single_value_measure(prop)
                if resolved is None:
                    continue
                name = _clean_label(getattr(prop, "Name", None))
                if name:
                    fields[name] = resolved
        else:
            for quantity in getattr(definition, "Quantities", None) or []:
                resolved = self._quantity_measure(quantity)
                if resolved is None:
                    continue
                name = _clean_label(getattr(quantity, "Name", None))
                if name:
                    fields[name] = resolved

        if instance_id is not None:
            self._container_cache[instance_id] = fields
        return fields

    def _single_value_measure(self, prop: Any) -> tuple[str, str | None] | None:
        try:
            if not prop.is_a("IfcPropertySingleValue"):
                return None
        except Exception:  # noqa: BLE001
            return None
        measure_type = _measure_type_of_wrapped(getattr(prop, "NominalValue", None))
        if measure_type is None:
            return None
        override = self.registry.register(getattr(prop, "Unit", None))
        return measure_type, override

    def _quantity_measure(self, quantity: Any) -> tuple[str, str | None] | None:
        try:
            measure_type = _MEASURE_BY_QUANTITY_CLASS.get(quantity.is_a())
        except Exception:  # noqa: BLE001
            return None
        if measure_type is None:
            return None
        override = self.registry.register(getattr(quantity, "Unit", None))
        return measure_type, override

    # -- diagnostics -------------------------------------------------------

    def _count(self, measure_type: str, provenance: str) -> None:
        key = (measure_type, provenance)
        self.typed_value_counts[key] = self.typed_value_counts.get(key, 0) + 1

    def note_value(self, measure_type: str, provenance: str) -> None:
        """Record one typed value for the ingestion report's diagnostics."""
        self._count(measure_type, provenance)

    def diagnostics(self) -> dict[str, Any]:
        """Bounded measurement diagnostics for the ingestion report (§5)."""
        by_measure: dict[str, int] = {m: 0 for m in SUPPORTED_MEASURE_TYPES}
        by_provenance: dict[str, int] = {}
        for (measure_type, provenance), count in self.typed_value_counts.items():
            by_measure[measure_type] = by_measure.get(measure_type, 0) + count
            by_provenance[provenance] = by_provenance.get(provenance, 0) + count
        return {
            "unit_contract_version": UNIT_CONTRACT_VERSION,
            "defaults": {
                measure_type: self.registry.symbol(self.registry.defaults[measure_type])
                for measure_type in SUPPORTED_MEASURE_TYPES
            },
            "unresolved_defaults": dict(sorted(self.registry.unresolved_defaults.items())),
            "typed_values_by_measure_type": dict(sorted(by_measure.items())),
            "typed_values_by_provenance": dict(sorted(by_provenance.items())),
            "unit_definition_count": len(self.registry.to_json()["definitions"]),
        }


def _load_schema(ifc_model: ifcopenshell.file) -> Any:
    """The parsed IFC schema declaration set, or None when unavailable."""
    try:
        from ifcopenshell import ifcopenshell_wrapper

        identifier = getattr(ifc_model, "schema_identifier", None) or ifc_model.schema
        return ifcopenshell_wrapper.schema_by_name(identifier)
    except Exception:  # noqa: BLE001 - degrade to no attribute measures
        return None
