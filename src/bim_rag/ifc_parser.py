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

EXTRACTION_VERSION = "v001"
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
# Property set extraction
# ---------------------------------------------------------------------------


def _extract_psets(entity: ifcopenshell.entity_instance) -> dict[str, Any]:
    """Extract property sets as {pset_name: {prop_name: {value, type}}}."""
    psets: dict[str, Any] = {}
    try:
        raw = ifc_util.get_psets(entity, psets_only=True)
        for pset_name, props in (raw or {}).items():
            psets[pset_name] = {}
            for prop_name, prop_val in props.items():
                if prop_name == "id":
                    continue
                psets[pset_name][prop_name] = {
                    "value": _safe_scalar(prop_val),
                    "type": type(prop_val).__name__,
                }
    except Exception as exc:
        psets["_extraction_error"] = str(exc)
    return psets


def _extract_qsets(
    entity: ifcopenshell.entity_instance, ifc_model: ifcopenshell.file
) -> dict[str, Any]:
    """Extract quantity sets as {qset_name: {qty_name: {value, unit, ...}}}."""
    qsets: dict[str, Any] = {}
    try:
        unit_scale = _get_project_length_unit(ifc_model)
        raw = ifc_util.get_psets(entity, qtos_only=True)
        for qset_name, qtys in (raw or {}).items():
            qsets[qset_name] = {}
            for qty_name, qty_val in qtys.items():
                if qty_name == "id":
                    continue
                entry: dict[str, Any] = {"value": _safe_scalar(qty_val), "provenance": "quantity"}
                if isinstance(qty_val, (int, float)) and unit_scale:
                    entry["unit"] = "project_unit"
                    try:
                        entry["normalized_value"] = round(float(qty_val) * unit_scale["factor"], 6)
                        entry["normalized_unit"] = unit_scale["unit"]
                    except Exception:
                        pass
                qsets[qset_name][qty_name] = entry
    except Exception as exc:
        qsets["_extraction_error"] = str(exc)
    return qsets


def _get_project_length_unit(ifc_model: ifcopenshell.file) -> dict[str, Any] | None:
    """Return {factor, unit} to convert project length to metres."""
    try:
        unit = ifc_unit_util.get_project_unit(ifc_model, "LENGTHUNIT")
        if unit is None:
            return None
        prefix = getattr(unit, "Prefix", None) or ""
        si_name = getattr(getattr(unit, "Name", None), "value", None) or getattr(unit, "Name", None)
        factor_map = {
            ("MILLI", "METRE"): (0.001, "m"),
            ("", "METRE"): (1.0, "m"),
            ("CENTI", "METRE"): (0.01, "m"),
            ("MILLI", "METER"): (0.001, "m"),
            ("", "METER"): (1.0, "m"),
        }
        key = (str(prefix).upper(), str(si_name).upper() if si_name else "")
        if key in factor_map:
            f, u = factor_map[key]
            return {"factor": f, "unit": u}
        if si_name and "FOOT" in str(si_name).upper():
            return {"factor": 0.3048, "unit": "m"}
        if si_name and "INCH" in str(si_name).upper():
            return {"factor": 0.0254, "unit": "m"}
    except Exception:
        pass
    return None


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

    psets: dict[str, Any] = {}
    try:
        psets = _extract_psets(entity)
    except Exception as e:
        warnings.append(f"pset extraction failed: {e}")

    qsets: dict[str, Any] = {}
    try:
        qsets = _extract_qsets(entity, ifc_model)
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
