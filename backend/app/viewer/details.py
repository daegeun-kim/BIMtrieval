"""Truthful, bounded component details + instance/type/family identity
(tasks/task13.md §4, §5).

Deterministic and LLM-free: everything here is read from the already-stored
`ifc_entities.canonical_json` that the ingestion pipeline wrote. No IFC parsing,
no embedding, no migration, no re-ingestion.

**Type/family semantics are mandatory (task13 §4).**

- Instance identity is always available for a valid entity.
- **Type** is available only when the source IFC explicitly supplied it and
  ingestion stored it at `canonical_json["type"]`.
- **Family is not a universal IFC concept.** It is available only when an
  explicitly allowlisted family-like property name exists in a stored property
  set, and it is always returned with its source property-set/property name so
  the user can see where it came from.
- Type/family are **never** inferred from the instance name, naming patterns,
  IFC class, material, or an LLM. Unavailable is a valid, expected result — the
  current Schependomlaan file has no useful `IfcRelDefinesByType` data.

The canonical JSON shape read here is written by `bim_rag.ifc_parser`:

    identity      {name, description, object_type, tag, ...}
    meta          {predefined_type, ...}
    storey        {name, global_id} | None
    type          {name, global_id, predefined_type} | None
    materials     [{name}, ...]
    property_sets {pset_name: {prop_name: {value, type}}}
    quantity_sets {qset_name: {qty_name: {value, provenance, unit?, ...}}}
    placement     {local_z?, elevation?}

Only allowlisted, length- and count-bounded values leave this module. Raw
canonical JSON, relationship expansion, geometry, vectors, prompts, SQL, paths,
and credentials never do.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# --- Bounds (task13 §4: "bounded by count/string length") -------------------
MAX_PROPERTY_VALUES = 24
MAX_QUANTITY_VALUES = 24
MAX_MATERIALS = 12
MAX_STRING_LEN = 120

# --- Family allowlist (task13 §4) -------------------------------------------
# Normalized (lower-cased) property names that explicitly carry a family-like
# value in stored property sets. Deliberately small and explicit: anything not
# listed here is NOT family data, and no name-shaped guess is ever substituted.
FAMILY_PROPERTY_NAMES: frozenset[str] = frozenset(
    {
        "family",
        "familyname",
        "familyandtype",
        "reference",
        "objecttypeoverride",
    }
)

# --- Property/quantity allowlists (task13 §4) -------------------------------
# Explicit and centralized. Property/quantity names are matched normalized.
PROPERTY_ALLOWLIST: frozenset[str] = frozenset(
    {
        "isexternal",
        "loadbearing",
        "firerating",
        "acousticrating",
        "thermaltransmittance",
        "combustible",
        "surfacespreadofflame",
        "compartmentation",
        "extendtostructure",
        "status",
        "reference",
    }
)

QUANTITY_ALLOWLIST: frozenset[str] = frozenset(
    {
        "width",
        "height",
        "length",
        "depth",
        "thickness",
        "nominalthickness",
        "perimeter",
        "area",
        "netarea",
        "grossarea",
        "netsidearea",
        "grosssidearea",
        "netfootprintarea",
        "grossfootprintarea",
        "netvolume",
        "grossvolume",
    }
)


def normalize_key(value: str) -> str:
    """Normalize a property/type name for allowlist and identity matching."""
    return value.strip().lower()


def normalize_value(value: str) -> str:
    """Normalize a stored family/type *value* for exact group matching.

    Case- and whitespace-insensitive only — never fuzzy, never partial.
    """
    return " ".join(value.split()).lower()


def safe_str(value: Any) -> str | None:
    """Bounded string form of a stored scalar. None stays None."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text[:MAX_STRING_LEN]


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


@dataclass(frozen=True)
class FamilyFact:
    """An explicit family value plus the stored property it came from."""

    value: str
    property_set: str
    property_name: str


@dataclass(frozen=True)
class TypeFact:
    name: str | None
    global_id: str | None
    predefined_type: str | None


@dataclass(frozen=True)
class NamedValue:
    name: str
    value: str
    source_set: str | None = None
    unit: str | None = None


def find_family(canonical: dict[str, Any]) -> FamilyFact | None:
    """Return the explicit family fact, or None when the model has none.

    Scans stored property sets for an allowlisted family-like property name and
    returns the first match in deterministic (property-set name, property name)
    order. Returns None rather than guessing — family is not a universal IFC
    concept, and absence is a truthful answer.
    """
    psets = _as_dict(canonical.get("property_sets"))
    for pset_name in sorted(psets):
        props = _as_dict(psets.get(pset_name))
        for prop_name in sorted(props):
            if normalize_key(prop_name) not in FAMILY_PROPERTY_NAMES:
                continue
            entry = _as_dict(props.get(prop_name))
            value = safe_str(entry.get("value"))
            if value:
                return FamilyFact(value=value, property_set=pset_name, property_name=prop_name)
    return None


def find_type(canonical: dict[str, Any]) -> TypeFact | None:
    """Return the explicitly stored IFC type fact, or None.

    Only reads `canonical_json["type"]`, which ingestion populates solely from
    real IFC type relationships. Never derived from the instance name or class.
    """
    type_info = canonical.get("type")
    if not isinstance(type_info, dict):
        return None
    name = safe_str(type_info.get("name"))
    global_id = safe_str(type_info.get("global_id"))
    predefined = safe_str(type_info.get("predefined_type"))
    if not (name or global_id):
        return None
    return TypeFact(name=name, global_id=global_id, predefined_type=predefined)


def select_properties(canonical: dict[str, Any]) -> list[NamedValue]:
    """Allowlisted, bounded property values in deterministic order."""
    out: list[NamedValue] = []
    psets = _as_dict(canonical.get("property_sets"))
    for pset_name in sorted(psets):
        props = _as_dict(psets.get(pset_name))
        for prop_name in sorted(props):
            if normalize_key(prop_name) not in PROPERTY_ALLOWLIST:
                continue
            entry = _as_dict(props.get(prop_name))
            value = safe_str(entry.get("value"))
            if value is None:
                continue
            out.append(NamedValue(name=prop_name, value=value, source_set=pset_name))
            if len(out) >= MAX_PROPERTY_VALUES:
                return out
    return out


def select_quantities(canonical: dict[str, Any]) -> list[NamedValue]:
    """Allowlisted, bounded quantity/dimension values in deterministic order.

    `DIMENSION` is a normalized view over quantity sets rather than its own
    storage (spec_v003 §8), so dimensions come from here too. The current model
    stores no quantity sets, which correctly yields an empty list.
    """
    out: list[NamedValue] = []
    qsets = _as_dict(canonical.get("quantity_sets"))
    for qset_name in sorted(qsets):
        qtys = _as_dict(qsets.get(qset_name))
        for qty_name in sorted(qtys):
            if normalize_key(qty_name) not in QUANTITY_ALLOWLIST:
                continue
            entry = _as_dict(qtys.get(qty_name))
            raw = entry.get("normalized_value", entry.get("value"))
            value = safe_str(raw)
            if value is None:
                continue
            unit = safe_str(entry.get("normalized_unit") or entry.get("unit"))
            out.append(NamedValue(name=qty_name, value=value, source_set=qset_name, unit=unit))
            if len(out) >= MAX_QUANTITY_VALUES:
                return out
    return out


def select_materials(canonical: dict[str, Any]) -> list[str]:
    """Bounded, de-duplicated material names."""
    names: list[str] = []
    raw = canonical.get("materials")
    if not isinstance(raw, list):
        return names
    for item in raw:
        name = safe_str(_as_dict(item).get("name"))
        if name and name not in names:
            names.append(name)
            if len(names) >= MAX_MATERIALS:
                break
    return names


def storey_of(canonical: dict[str, Any]) -> tuple[str | None, str | None]:
    storey = _as_dict(canonical.get("storey"))
    return safe_str(storey.get("name")), safe_str(storey.get("global_id"))


def elevation_of(canonical: dict[str, Any]) -> float | None:
    """Stored elevation when the IFC supplied one; otherwise None.

    Most product instances carry no `Elevation` attribute (it is a storey
    attribute), so None is the common, truthful result.
    """
    placement = _as_dict(canonical.get("placement"))
    value = placement.get("elevation")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None
