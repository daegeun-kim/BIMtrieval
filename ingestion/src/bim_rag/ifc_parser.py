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

from bim_rag.measures import MeasurementExtractor

#: v002 (task27): supported length/area/volume values now carry their IFC
#: measure type and, when the source supplies one, an explicit unit override.
#: The invalid v001 normalisation (one project LENGTH factor applied to every
#: quantity, labelled `normalized_unit="m"` even for areas and volumes) is gone.
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


def _annotate_measure(
    entry: dict[str, Any],
    resolved: tuple[str, str | None] | None,
    measurements: MeasurementExtractor | None,
    provenance: str,
) -> None:
    """Attach measure type and an EXPLICIT unit override, or nothing at all.

    The model default is deliberately not copied onto every value (§2.2): the
    effective unit is `unit_override_key` otherwise the registry default for the
    measure type. Writing a null override key would make "no override" and
    "override to nothing" indistinguishable, so it is omitted entirely.
    """
    if resolved is None:
        return
    measure_type, override_key = resolved
    entry["measure_type"] = measure_type
    if override_key:
        entry["unit_override_key"] = override_key
    if measurements is not None:
        measurements.note_value(measure_type, provenance)


def _extract_psets(
    entity: ifcopenshell.entity_instance,
    measurements: MeasurementExtractor | None = None,
) -> dict[str, Any]:
    """Extract property sets as {pset_name: {prop_name: {value, type, measure_type?}}}."""
    psets: dict[str, Any] = {}
    try:
        measure_index = measurements.property_measures(entity) if measurements else {}
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
                _annotate_measure(
                    entry, measure_index.get((pset_name, prop_name)), measurements, "property"
                )
                psets[pset_name][prop_name] = entry
    except Exception as exc:
        psets["_extraction_error"] = str(exc)
    return psets


def _extract_qsets(
    entity: ifcopenshell.entity_instance,
    measurements: MeasurementExtractor | None = None,
) -> dict[str, Any]:
    """Extract quantity sets as {qset_name: {qty_name: {value, provenance, measure_type?}}}.

    v002 stores the RAW source value only. The v001 behaviour — multiplying
    every numeric quantity by one project LENGTH factor and labelling the result
    `normalized_unit="m"` — was invalid for areas and volumes and is removed
    (§2.3). No linear factor is applied to anything here.
    """
    qsets: dict[str, Any] = {}
    try:
        measure_index = measurements.quantity_measures(entity) if measurements else {}
        raw = ifc_util.get_psets(entity, qtos_only=True)
        for qset_name, qtys in (raw or {}).items():
            qsets[qset_name] = {}
            for qty_name, qty_val in qtys.items():
                if qty_name == "id":
                    continue
                entry: dict[str, Any] = {"value": _safe_scalar(qty_val), "provenance": "quantity"}
                _annotate_measure(
                    entry, measure_index.get((qset_name, qty_name)), measurements, "quantity"
                )
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
    measurements: MeasurementExtractor | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Return (canonical_json, warnings) for one eligible entity.

    `measurements` is the model-scoped measure/unit resolver (task27 §2). It is
    optional so that a caller with no IFC unit context still produces valid
    canonical JSON — such a document simply carries no measure metadata, which
    is the honest state rather than an assumed one.
    """
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
        psets = _extract_psets(entity, measurements)
    except Exception as e:
        warnings.append(f"pset extraction failed: {e}")

    qsets: dict[str, Any] = {}
    try:
        qsets = _extract_qsets(entity, measurements)
    except Exception as e:
        warnings.append(f"qset extraction failed: {e}")

    # The bounded measurement-attribute container (§2.2): direct IFC attributes
    # whose DECLARED schema type is a supported measure. Nothing else is copied
    # in, so this can never become a dumping ground for arbitrary attributes.
    measurement_attributes: dict[str, Any] = {}
    if measurements is not None:
        try:
            measurement_attributes = measurements.measurements_for(entity)
        except Exception as e:
            warnings.append(f"measurement attribute extraction failed: {e}")

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
        "measurements": measurement_attributes,
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
