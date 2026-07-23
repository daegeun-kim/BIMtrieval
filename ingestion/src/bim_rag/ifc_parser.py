"""IFC parsing: eligibility filtering and canonical JSON extraction.

Information boundary (spec §6):
- Include only intrinsic/resolved facts (storey name, type name, material name, etc.)
- Exclude relationship entity IDs, adjacency lists, containment lists
- Prevent cycles via a visited-entity guard
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

import ifcopenshell
import ifcopenshell.util.element as ifc_util
import ifcopenshell.util.unit as ifc_unit_util

EXTRACTION_VERSION = "v002"
_MAX_DEPTH = 3  # max traversal depth for type/material resolution


# ---------------------------------------------------------------------------
# Eligibility
# ---------------------------------------------------------------------------


def is_ifcrelationship(entity: ifcopenshell.entity_instance) -> bool:
    return entity.is_a("IfcRelationship")


def is_eligible(entity: ifcopenshell.entity_instance) -> bool:
    """Return True if entity should be imported and vectorised (spec §5)."""
    if not entity.is_a("IfcRoot"):
        return False
    if not getattr(entity, "GlobalId", None):
        return False
    if is_ifcrelationship(entity):
        return False
    return True


# ---------------------------------------------------------------------------
# IFC file fingerprint
# ---------------------------------------------------------------------------


def file_fingerprint(path: Path) -> str:
    """SHA-256 of the IFC file bytes."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Safe value serialisation helpers
# ---------------------------------------------------------------------------


def _safe_scalar(v: Any) -> Any:
    """Convert IFC scalar to a JSON-safe Python value."""
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            return None
        return v
    if isinstance(v, str):
        return v.strip()
    if hasattr(v, "wrappedValue"):
        return _safe_scalar(v.wrappedValue)
    return str(v)


def _ifc_value_and_unit(v: Any) -> dict[str, Any]:
    """Return {value, unit, normalized_value, normalized_unit} or {value} for plain scalars."""
    if v is None:
        return {"value": None}
    if hasattr(v, "wrappedValue"):
        inner = v.wrappedValue
        return {"value": _safe_scalar(inner)}
    return {"value": _safe_scalar(v)}


# ---------------------------------------------------------------------------
# Resolved attribute helpers (traverse relationships without storing rel IDs)
# ---------------------------------------------------------------------------


def _resolve_storey(entity: ifcopenshell.entity_instance) -> dict[str, Any] | None:
    """Return {name, global_id} of the containing storey (if any)."""
    try:
        storey = ifc_util.get_container(entity)
        while storey and not storey.is_a("IfcBuildingStorey"):
            storey = ifc_util.get_container(storey)
        if storey:
            return {
                "name": _safe_scalar(getattr(storey, "Name", None)),
                "global_id": storey.GlobalId,
            }
    except Exception:
        pass
    return None


def _resolve_type(entity: ifcopenshell.entity_instance) -> dict[str, Any] | None:
    """Return {name, global_id} of the related type object (if any)."""
    try:
        t = ifc_util.get_type(entity)
        if t:
            return {
                "name": _safe_scalar(getattr(t, "Name", None)),
                "global_id": t.GlobalId,
                "predefined_type": _safe_scalar(getattr(t, "PredefinedType", None)),
            }
    except Exception:
        pass
    return None


def _resolve_materials(entity: ifcopenshell.entity_instance) -> list[dict[str, Any]]:
    """Return list of {name} dicts for assigned materials."""
    results: list[dict[str, Any]] = []
    try:
        mats = ifc_util.get_materials(entity, should_inherit=True)
        for m in mats or []:
            name = _safe_scalar(getattr(m, "Name", None))
            if name:
                results.append({"name": name})
    except Exception:
        pass
    return results


def _resolve_classifications(entity: ifcopenshell.entity_instance) -> list[dict[str, Any]]:
    """Return list of {system, code, description} classification refs."""
    results: list[dict[str, Any]] = []
    try:
        for rel in getattr(entity, "HasAssociations", []) or []:
            if rel.is_a("IfcRelAssociatesClassification"):
                ref = rel.RelatingClassification
                if ref:
                    src = getattr(ref, "ReferencedSource", None)
                    code = getattr(ref, "ItemReference", None) or getattr(
                        ref, "Identification", None
                    )
                    results.append(
                        {
                            "system": _safe_scalar(getattr(src, "Name", None)),
                            "code": _safe_scalar(code),
                            "description": _safe_scalar(getattr(ref, "Name", None)),
                        }
                    )
    except Exception:
        pass
    return results


# ---------------------------------------------------------------------------
# Deterministic unit registry (task26 §4.3)
# ---------------------------------------------------------------------------

#: SI prefix multipliers (the subset IFC declares).
_SI_PREFIX = {
    "EXA": 1e18,
    "PETA": 1e15,
    "TERA": 1e12,
    "GIGA": 1e9,
    "MEGA": 1e6,
    "KILO": 1e3,
    "HECTO": 1e2,
    "DECA": 1e1,
    "": 1.0,
    "DECI": 1e-1,
    "CENTI": 1e-2,
    "MILLI": 1e-3,
    "MICRO": 1e-6,
    "NANO": 1e-9,
}

#: Canonical output unit per IFC unit type.
_CANONICAL_UNIT = {
    "LENGTHUNIT": "m",
    "AREAUNIT": "m2",
    "VOLUMEUNIT": "m3",
    "MASSUNIT": "kg",
    "PLANEANGLEUNIT": "rad",
    "TIMEUNIT": "s",
}

#: Dimension exponent for SI-prefixed derived units (area scales prefix^2, ...).
_DIMENSION_EXPONENT = {"LENGTHUNIT": 1, "AREAUNIT": 2, "VOLUMEUNIT": 3}

#: Conversion factors for common imperial units, to the canonical unit.
_CONVERSION_NAMES = {
    ("LENGTHUNIT", "FOOT"): 0.3048,
    ("LENGTHUNIT", "INCH"): 0.0254,
    ("AREAUNIT", "SQUARE FOOT"): 0.09290304,
    ("VOLUMEUNIT", "CUBIC FOOT"): 0.028316846592,
    ("MASSUNIT", "POUND"): 0.45359237,
}

#: IFC measure class -> unit type (None: unitless numeric).
_MEASURE_UNIT_TYPE = {
    "IfcLengthMeasure": "LENGTHUNIT",
    "IfcPositiveLengthMeasure": "LENGTHUNIT",
    "IfcNonNegativeLengthMeasure": "LENGTHUNIT",
    "IfcAreaMeasure": "AREAUNIT",
    "IfcVolumeMeasure": "VOLUMEUNIT",
    "IfcMassMeasure": "MASSUNIT",
    "IfcPlaneAngleMeasure": "PLANEANGLEUNIT",
    "IfcTimeMeasure": "TIMEUNIT",
    "IfcCountMeasure": None,
    "IfcNumericMeasure": None,
    "IfcReal": None,
    "IfcInteger": None,
    "IfcRatioMeasure": None,
    "IfcPositiveRatioMeasure": None,
    "IfcNormalisedRatioMeasure": None,
}

_unit_registry_cache: dict[int, dict[str, dict[str, Any]]] = {}


def _named_unit_factor(unit: Any, unit_type: str) -> float | None:
    """Deterministic factor from one project IfcNamedUnit to the canonical unit."""
    if unit is None:
        return None
    try:
        if unit.is_a("IfcSIUnit"):
            prefix = str(getattr(unit, "Prefix", None) or "").upper()
            multiplier = _SI_PREFIX.get(prefix)
            if multiplier is None:
                return None
            return multiplier ** _DIMENSION_EXPONENT.get(unit_type, 1)
        if unit.is_a("IfcConversionBasedUnit"):
            name = str(getattr(unit, "Name", "") or "").upper()
            if (unit_type, name) in _CONVERSION_NAMES:
                return _CONVERSION_NAMES[(unit_type, name)]
            # Resolve through the declared conversion factor when it is itself
            # SI-based — deterministic, no guessing.
            factor = getattr(unit, "ConversionFactor", None)
            if factor is not None:
                magnitude = _safe_scalar(getattr(factor, "ValueComponent", None))
                base = getattr(factor, "UnitComponent", None)
                base_factor = _named_unit_factor(base, unit_type) if base is not None else None
                if isinstance(magnitude, (int, float)) and base_factor is not None:
                    return float(magnitude) * base_factor
    except Exception:
        return None
    return None


def build_unit_registry(ifc_model: ifcopenshell.file) -> dict[str, dict[str, Any]]:
    """{unit_type: {factor, unit}} for every project unit provably convertible.

    A unit type absent from this registry means its numeric values keep an
    UNKNOWN unit state: still stored, never normalized, never compared
    cross-unit (task26 §4.3).
    """
    cached = _unit_registry_cache.get(id(ifc_model))
    if cached is not None:
        return cached
    registry: dict[str, dict[str, Any]] = {}
    for unit_type, canonical in _CANONICAL_UNIT.items():
        try:
            unit = ifc_unit_util.get_project_unit(ifc_model, unit_type)
        except Exception:
            unit = None
        factor = _named_unit_factor(unit, unit_type)
        if factor is not None:
            registry[unit_type] = {"factor": factor, "unit": canonical}
    _unit_registry_cache[id(ifc_model)] = registry
    return registry


def _annotate_measure(
    entry: dict[str, Any],
    measure: str | None,
    registry: dict[str, dict[str, Any]],
) -> None:
    """Attach unit metadata to one numeric property/quantity entry.

    States (task26 §4.3): `known` (normalized magnitude + canonical unit),
    `unitless` (a genuine ratio/count), `unknown` (numeric, but no provable
    unit contract — stored, never converted or aggregated cross-unit).
    """
    value = entry.get("value")
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return
    if measure:
        entry["measure"] = measure
    unit_type = _MEASURE_UNIT_TYPE.get(measure or "")
    if measure and unit_type is None and measure in _MEASURE_UNIT_TYPE:
        entry["unit_state"] = "unitless"
        return
    scale = registry.get(unit_type or "")
    if unit_type and scale:
        entry["unit_state"] = "known"
        entry["normalized_value"] = round(float(value) * scale["factor"], 6)
        entry["normalized_unit"] = scale["unit"]
    else:
        entry["unit_state"] = "unknown"


# ---------------------------------------------------------------------------
# Property set extraction
# ---------------------------------------------------------------------------


def _property_measures(
    entity: ifcopenshell.entity_instance,
) -> dict[tuple[str, str], str]:
    """{(pset_name, prop_name): IFC measure class} for single-value properties.

    Walks the entity's own property sets and its type's, so the measure type
    declared by the exporter is preserved rather than collapsed to a Python
    float (task26 §4.3).
    """
    measures: dict[tuple[str, str], str] = {}

    def _walk_pset(pset: Any) -> None:
        if pset is None or not pset.is_a("IfcPropertySet"):
            return
        pset_name = _safe_scalar(getattr(pset, "Name", None))
        if not pset_name:
            return
        for prop in getattr(pset, "HasProperties", None) or []:
            try:
                if not prop.is_a("IfcPropertySingleValue"):
                    continue
                nominal = getattr(prop, "NominalValue", None)
                prop_name = _safe_scalar(getattr(prop, "Name", None))
                if nominal is not None and prop_name:
                    measures.setdefault((pset_name, prop_name), nominal.is_a())
            except Exception:
                continue

    try:
        for rel in getattr(entity, "IsDefinedBy", None) or []:
            if rel.is_a("IfcRelDefinesByProperties"):
                _walk_pset(getattr(rel, "RelatingPropertyDefinition", None))
        entity_type = ifc_util.get_type(entity)
        for pset in getattr(entity_type, "HasPropertySets", None) or []:
            _walk_pset(pset)
    except Exception:
        pass
    return measures


def _extract_psets(
    entity: ifcopenshell.entity_instance,
    registry: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Extract property sets as {pset_name: {prop_name: {value, type, ...}}}.

    Numeric entries additionally carry `measure`/`unit_state` and, when the
    unit contract is provable, `normalized_value`/`normalized_unit`.
    """
    psets: dict[str, Any] = {}
    registry = registry or {}
    try:
        measures = _property_measures(entity)
        raw = ifc_util.get_psets(entity, psets_only=True)
        for pset_name, props in (raw or {}).items():
            psets[pset_name] = {}
            for prop_name, prop_val in props.items():
                if prop_name == "id":
                    continue
                entry: dict[str, Any] = {
                    "value": _safe_scalar(prop_val),
                    "type": type(prop_val).__name__,
                }
                _annotate_measure(entry, measures.get((pset_name, prop_name)), registry)
                psets[pset_name][prop_name] = entry
    except Exception as exc:
        psets["_extraction_error"] = str(exc)
    return psets


#: IfcPhysicalQuantity subclass -> (value attribute, unit type).
_QUANTITY_KINDS = {
    "IfcQuantityLength": ("LengthValue", "LENGTHUNIT"),
    "IfcQuantityArea": ("AreaValue", "AREAUNIT"),
    "IfcQuantityVolume": ("VolumeValue", "VOLUMEUNIT"),
    "IfcQuantityWeight": ("WeightValue", "MASSUNIT"),
    "IfcQuantityCount": ("CountValue", None),
    "IfcQuantityTime": ("TimeValue", "TIMEUNIT"),
}


def _quantity_kinds(
    entity: ifcopenshell.entity_instance,
) -> dict[tuple[str, str], str]:
    """{(qset_name, qty_name): quantity class} from the actual quantity rows."""
    kinds: dict[tuple[str, str], str] = {}
    try:
        for rel in getattr(entity, "IsDefinedBy", None) or []:
            if not rel.is_a("IfcRelDefinesByProperties"):
                continue
            qset = getattr(rel, "RelatingPropertyDefinition", None)
            if qset is None or not qset.is_a("IfcElementQuantity"):
                continue
            qset_name = _safe_scalar(getattr(qset, "Name", None))
            if not qset_name:
                continue
            for qty in getattr(qset, "Quantities", None) or []:
                qty_name = _safe_scalar(getattr(qty, "Name", None))
                if qty_name:
                    kinds.setdefault((qset_name, qty_name), qty.is_a())
    except Exception:
        pass
    return kinds


def _extract_qsets(
    entity: ifcopenshell.entity_instance,
    ifc_model: ifcopenshell.file,
    registry: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Extract quantity sets as {qset_name: {qty_name: {value, unit, ...}}}."""
    qsets: dict[str, Any] = {}
    registry = build_unit_registry(ifc_model) if registry is None else registry
    try:
        kinds = _quantity_kinds(entity)
        raw = ifc_util.get_psets(entity, qtos_only=True)
        for qset_name, qtys in (raw or {}).items():
            qsets[qset_name] = {}
            for qty_name, qty_val in qtys.items():
                if qty_name == "id":
                    continue
                entry: dict[str, Any] = {"value": _safe_scalar(qty_val), "provenance": "quantity"}
                qty_class = kinds.get((qset_name, qty_name))
                measure = None
                if qty_class in _QUANTITY_KINDS:
                    unit_type = _QUANTITY_KINDS[qty_class][1]
                    # Reuse the measure annotation by mapping the quantity kind
                    # onto its measure equivalent.
                    measure = next(
                        (m for m, t in _MEASURE_UNIT_TYPE.items() if t == unit_type), None
                    ) if unit_type else "IfcCountMeasure"
                _annotate_measure(entry, measure, registry)
                if qty_class:
                    entry["quantity_class"] = qty_class
                qsets[qset_name][qty_name] = entry
    except Exception as exc:
        qsets["_extraction_error"] = str(exc)
    return qsets


# ---------------------------------------------------------------------------
# Representation metadata (no geometry serialisation)
# ---------------------------------------------------------------------------


def _extract_representation_meta(entity: ifcopenshell.entity_instance) -> dict[str, Any]:
    rep: dict[str, Any] = {}
    try:
        shape = getattr(entity, "Representation", None)
        if shape:
            rep["has_geometry"] = True
            rep_types = []
            for sub in getattr(shape, "Representations", []) or []:
                rt = _safe_scalar(getattr(sub, "RepresentationType", None))
                if rt:
                    rep_types.append(rt)
            if rep_types:
                rep["representation_types"] = list(dict.fromkeys(rep_types))
    except Exception:
        pass
    return rep


# ---------------------------------------------------------------------------
# Placement / elevation
# ---------------------------------------------------------------------------


def _extract_placement(entity: ifcopenshell.entity_instance) -> dict[str, Any]:
    placement: dict[str, Any] = {}
    try:
        loc = getattr(entity, "ObjectPlacement", None)
        if loc and loc.is_a("IfcLocalPlacement"):
            rel = getattr(loc, "RelativePlacement", None)
            if rel:
                loc_pt = getattr(rel, "Location", None)
                if loc_pt and hasattr(loc_pt, "Coordinates"):
                    coords = loc_pt.Coordinates
                    if coords and len(coords) >= 3:
                        placement["local_z"] = _safe_scalar(coords[2])
        elevation = getattr(entity, "Elevation", None)
        if elevation is not None:
            placement["elevation"] = _safe_scalar(elevation)
    except Exception:
        pass
    return placement


# ---------------------------------------------------------------------------
# Canonical JSON builder
# ---------------------------------------------------------------------------


def extract_canonical_json(
    entity: ifcopenshell.entity_instance,
    ifc_model: ifcopenshell.file,
) -> tuple[dict[str, Any], list[str]]:
    """Return (canonical_json, warnings) for one eligible entity."""
    warnings: list[str] = []

    meta = {
        "step_id": entity.id(),
        "global_id": entity.GlobalId,
        "ifc_class": entity.is_a(),
        "predefined_type": _safe_scalar(getattr(entity, "PredefinedType", None)),
        "extraction_version": EXTRACTION_VERSION,
    }

    identity = {
        "name": _safe_scalar(getattr(entity, "Name", None)),
        "description": _safe_scalar(getattr(entity, "Description", None)),
        "object_type": _safe_scalar(getattr(entity, "ObjectType", None)),
        "tag": _safe_scalar(getattr(entity, "Tag", None)),
        "long_name": _safe_scalar(getattr(entity, "LongName", None)),
        "composition_type": _safe_scalar(getattr(entity, "CompositionType", None)),
    }

    # Resolved facts (traversal allowed, but store only descriptive facts)
    storey = None
    try:
        storey = _resolve_storey(entity)
    except Exception as e:
        warnings.append(f"storey resolution failed: {e}")

    type_info = None
    try:
        type_info = _resolve_type(entity)
    except Exception as e:
        warnings.append(f"type resolution failed: {e}")

    materials: list[dict[str, Any]] = []
    try:
        materials = _resolve_materials(entity)
    except Exception as e:
        warnings.append(f"material resolution failed: {e}")

    classifications: list[dict[str, Any]] = []
    try:
        classifications = _resolve_classifications(entity)
    except Exception as e:
        warnings.append(f"classification resolution failed: {e}")

    registry = {}
    try:
        registry = build_unit_registry(ifc_model)
    except Exception as e:
        warnings.append(f"unit registry failed: {e}")

    psets: dict[str, Any] = {}
    try:
        psets = _extract_psets(entity, registry)
    except Exception as e:
        warnings.append(f"pset extraction failed: {e}")

    qsets: dict[str, Any] = {}
    try:
        qsets = _extract_qsets(entity, ifc_model, registry)
    except Exception as e:
        warnings.append(f"qset extraction failed: {e}")

    placement = {}
    try:
        placement = _extract_placement(entity)
    except Exception as e:
        warnings.append(f"placement extraction failed: {e}")

    rep_meta = {}
    try:
        rep_meta = _extract_representation_meta(entity)
    except Exception as e:
        warnings.append(f"representation extraction failed: {e}")

    canonical: dict[str, Any] = {
        "meta": meta,
        "identity": {k: v for k, v in identity.items() if v is not None},
        "storey": storey,
        "type": type_info,
        "materials": materials,
        "classifications": classifications,
        "property_sets": psets,
        "quantity_sets": qsets,
        "placement": placement,
        "representation": rep_meta,
        "warnings": warnings,
    }

    # Verify serializability (catches cycles or non-serialisable values)
    try:
        json.dumps(canonical)
    except (TypeError, ValueError) as e:
        warnings.append(f"canonical JSON serialisation error: {e}")
        canonical["_serialisation_error"] = str(e)

    return canonical, warnings


# ---------------------------------------------------------------------------
# Model-level scanning
# ---------------------------------------------------------------------------


def scan_model(ifc_path: Path) -> dict[str, Any]:
    """Open the IFC file and return a validation report dict (no DB writes)."""
    model = ifcopenshell.open(str(ifc_path))
    schema = model.schema

    all_entities = list(model)
    total = len(all_entities)
    with_global_id = [e for e in all_entities if getattr(e, "GlobalId", None)]
    roots_with_gid = [e for e in with_global_id if e.is_a("IfcRoot")]
    relationships = [e for e in roots_with_gid if is_ifcrelationship(e)]
    eligible = [e for e in roots_with_gid if is_eligible(e)]

    class_counts: dict[str, int] = {}
    for e in eligible:
        cls = e.is_a()
        class_counts[cls] = class_counts.get(cls, 0) + 1

    rel_class_counts: dict[str, int] = {}
    for e in relationships:
        cls = e.is_a()
        rel_class_counts[cls] = rel_class_counts.get(cls, 0) + 1

    # Check for duplicate GlobalIds among eligible entities
    gids = [e.GlobalId for e in eligible]
    seen: set[str] = set()
    duplicates: list[str] = []
    for g in gids:
        if g in seen:
            duplicates.append(g)
        seen.add(g)

    return {
        "ifc_schema": schema,
        "total_entity_count": total,
        "entities_with_global_id": len(with_global_id),
        "root_entities_with_global_id": len(roots_with_gid),
        "eligible_entity_count": len(eligible),
        "relationship_count": len(relationships),
        "excluded_relationship_count": len(relationships),  # kept for backwards compat
        "class_counts": class_counts,
        "relationship_class_counts": rel_class_counts,
        "duplicate_global_ids": duplicates,
        "model": model,
        "eligible_entities": eligible,
        "relationship_entities": relationships,
    }
