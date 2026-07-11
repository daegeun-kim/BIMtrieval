"""IFC relationship extraction: canonical JSON and member-row building.

Extracts direct, finite, non-recursive attributes from every IfcRelationship
with a valid GlobalId. Entity-valued attributes become relationship_members rows.
OwnerHistory is serialised as a lightweight reference but not as a member row.
"""

from __future__ import annotations

import json
import math
from typing import Any

import ifcopenshell

from bim_rag.ifc_parser import EXTRACTION_VERSION, _safe_scalar

# Attributes skipped for member-row extraction (administrative / identity fields)
_MEMBER_SKIP = {"id", "type", "GlobalId", "OwnerHistory", "Name", "Description"}


def _is_ifc_entity(obj: Any) -> bool:
    """Duck-type check for IfcOpenShell entity instances (works with mocks too)."""
    return (
        obj is not None
        and hasattr(obj, "is_a")
        and hasattr(obj, "id")
        and callable(getattr(obj, "id", None))
    )


# ---------------------------------------------------------------------------
# Endpoint summary (shallow — never recursed)
# ---------------------------------------------------------------------------


def _endpoint_summary(ent: ifcopenshell.entity_instance) -> dict[str, Any]:
    """Return a lightweight dict for one endpoint entity (no recursion)."""
    return {
        "step_id": ent.id(),
        "ifc_class": ent.is_a(),
        "global_id": _safe_scalar(getattr(ent, "GlobalId", None)),
        "name": _safe_scalar(getattr(ent, "Name", None)),
    }


# ---------------------------------------------------------------------------
# Canonical JSON for one relationship entity
# ---------------------------------------------------------------------------


def extract_relationship_canonical_json(
    rel: ifcopenshell.entity_instance,
) -> tuple[dict[str, Any], list[str]]:
    """Return (canonical_json, warnings) for one IfcRelationship entity."""
    warnings: list[str] = []

    meta = {
        "step_id": rel.id(),
        "global_id": rel.GlobalId,
        "ifc_class": rel.is_a(),
        "extraction_version": EXTRACTION_VERSION,
    }

    identity: dict[str, Any] = {}
    name = _safe_scalar(getattr(rel, "Name", None))
    desc = _safe_scalar(getattr(rel, "Description", None))
    if name is not None:
        identity["name"] = name
    if desc is not None:
        identity["description"] = desc

    scalars: dict[str, Any] = {}
    endpoints: dict[str, Any] = {}

    try:
        info = rel.get_info()
    except Exception as exc:
        warnings.append(f"get_info failed: {exc}")
        info = {}

    for attr_name, attr_val in info.items():
        if attr_name in ("id", "type", "GlobalId", "Name", "Description"):
            continue
        if attr_name == "OwnerHistory":
            if attr_val is not None and hasattr(attr_val, "id"):
                scalars["OwnerHistory_step_id"] = attr_val.id()
            continue

        try:
            if _is_ifc_entity(attr_val):
                endpoints[attr_name] = _endpoint_summary(attr_val)
            elif isinstance(attr_val, (list, tuple)):
                entity_items = []
                scalar_items = []
                for item in attr_val:
                    if _is_ifc_entity(item):
                        entity_items.append(_endpoint_summary(item))
                    else:
                        scalar_items.append(_safe_scalar(item))
                if entity_items:
                    endpoints[attr_name] = entity_items
                elif scalar_items:
                    scalars[attr_name] = scalar_items
            else:
                v = _safe_scalar(attr_val)
                if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                    v = None
                scalars[attr_name] = v
        except Exception as exc:
            warnings.append(f"attribute '{attr_name}' extraction failed: {exc}")

    canonical: dict[str, Any] = {
        "meta": meta,
        "identity": identity,
        "scalars": scalars,
        "endpoints": endpoints,
        "warnings": warnings,
    }

    try:
        json.dumps(canonical)
    except (TypeError, ValueError) as exc:
        warnings.append(f"JSON serialisation error: {exc}")
        canonical["_serialisation_error"] = str(exc)

    return canonical, warnings


# ---------------------------------------------------------------------------
# Member rows for relationship_members table
# ---------------------------------------------------------------------------


def extract_member_rows(rel: ifcopenshell.entity_instance) -> list[dict[str, Any]]:
    """Return list of raw member dicts (no entity_id resolved yet).

    Each dict has: role, member_order, endpoint_step_id, endpoint_ifc_class,
    endpoint_global_id, endpoint_name.
    """
    rows: list[dict[str, Any]] = []

    try:
        info = rel.get_info()
    except Exception:
        return rows

    for attr_name, attr_val in info.items():
        if attr_name in _MEMBER_SKIP:
            continue

        try:
            if _is_ifc_entity(attr_val):
                rows.append(
                    {
                        "role": attr_name,
                        "member_order": None,
                        "endpoint_step_id": attr_val.id(),
                        "endpoint_ifc_class": attr_val.is_a(),
                        "endpoint_global_id": _safe_scalar(getattr(attr_val, "GlobalId", None)),
                        "endpoint_name": _safe_scalar(getattr(attr_val, "Name", None)),
                    }
                )
            elif isinstance(attr_val, (list, tuple)):
                for i, item in enumerate(attr_val):
                    if _is_ifc_entity(item):
                        rows.append(
                            {
                                "role": attr_name,
                                "member_order": i,
                                "endpoint_step_id": item.id(),
                                "endpoint_ifc_class": item.is_a(),
                                "endpoint_global_id": _safe_scalar(getattr(item, "GlobalId", None)),
                                "endpoint_name": _safe_scalar(getattr(item, "Name", None)),
                            }
                        )
        except Exception:
            pass

    return rows


# ---------------------------------------------------------------------------
# Endpoint resolution
# ---------------------------------------------------------------------------


def resolve_members(
    raw_members: list[dict[str, Any]],
    global_id_to_entity_id: dict[str, int],
    source_model_id: int,
) -> list[dict[str, Any]]:
    """Enrich member dicts with resolved entity_id where possible.

    Resolution uses (source_model_id, GlobalId) — never name matching.
    Cross-model linking is impossible because global_id_to_entity_id is
    scoped to this source_model_id only.
    """
    resolved: list[dict[str, Any]] = []
    for m in raw_members:
        m_copy = dict(m)
        m_copy["source_model_id"] = source_model_id
        gid = m_copy.get("endpoint_global_id")
        if gid and gid in global_id_to_entity_id:
            m_copy["entity_id"] = global_id_to_entity_id[gid]
        else:
            m_copy["entity_id"] = None
        resolved.append(m_copy)
    return resolved
