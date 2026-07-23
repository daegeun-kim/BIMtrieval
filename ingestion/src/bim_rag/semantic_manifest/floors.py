"""Derived physical floor bands with occupancy evidence (task26 §5.5).

Raw `IfcBuildingStorey` rows are not occupiable floors: real exports mix
ordinary levels with underside-of-slab sublevels, multi-wing duplicates, roof
references, and reference planes. This module derives elevation bands with the
scale-free gap clustering validated in the query backend (task23), then
classifies each band as `occupiable`, `non_occupiable_reference`, or
`uncertain` from evidence the model itself provides:

- effective spatial membership counts per architectural category (spaces,
  walls, doors, windows, furnishing, roofs/slabs);
- storey NAME evidence (roof/reference terminology in the languages of the
  corpus), which may contribute but never decides alone.

No model-specific names, IDs, elevations, or expected counts appear here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

FLOOR_DERIVATION_VERSION = "floors_v001"

#: A new band starts where the elevation gap exceeds this fraction of the
#: model's own largest inter-storey gap (task23-validated, dimensionless).
BAND_GAP_FRACTION = 0.3

#: Outlier guard (task26 §5.5 "robust outlier handling"): gaps beyond this
#: multiple of the median positive gap are excluded from the reference-gap
#: computation, so one detached site/landscape storey cannot inflate the
#: threshold and merge real floors.
OUTLIER_GAP_MULTIPLE = 10.0

#: Roof/reference terminology across the corpus languages (en/nl/sv/de/fr).
#: Generic architectural lexicon — evidence only, never sole authority.
_ROOF_TOKENS = ("roof", "dak", "tak", "dach", "toit", "takplan")
_REFERENCE_TOKENS = ("underside", "u.k.", "reference", "datum", "t.o.", "b.o.")

#: Architectural category by IFC class prefix (schema vocabulary, not model
#: vocabulary). Matching is prefix-based so subtypes count with their family.
_CATEGORY_PREFIXES: dict[str, tuple[str, ...]] = {
    "spaces": ("IfcSpace",),
    "walls": ("IfcWall", "IfcCurtainWall"),
    "doors": ("IfcDoor",),
    "windows": ("IfcWindow",),
    "furnishing": ("IfcFurnishingElement", "IfcFurniture", "IfcSystemFurniture"),
    "stairs": ("IfcStair", "IfcRamp"),
    "roofs": ("IfcRoof",),
    "slabs": ("IfcSlab", "IfcCovering", "IfcBeam", "IfcColumn", "IfcMember", "IfcPlate"),
}


@dataclass
class StoreyFact:
    global_id: str
    name: str | None
    elevation: float


@dataclass
class DerivedBand:
    index: int
    storeys: list[StoreyFact] = field(default_factory=list)
    evidence: dict[str, int] = field(default_factory=dict)
    classification: str = "uncertain"
    confidence: str = "low"
    reasons: list[str] = field(default_factory=list)
    occupiable_ordinal: int | None = None

    @property
    def elevation_min(self) -> float:
        return min(s.elevation for s in self.storeys)

    @property
    def elevation_max(self) -> float:
        return max(s.elevation for s in self.storeys)


def load_storeys(session: Session, source_model_id: int) -> list[StoreyFact]:
    rows = session.execute(
        text(
            "SELECT global_id, canonical_json->'identity'->>'name', "
            "COALESCE(canonical_json->'placement'->>'elevation', "
            "         canonical_json->'placement'->>'local_z') "
            "FROM ifc_entities WHERE source_model_id = :sid "
            "AND ifc_class = 'IfcBuildingStorey'"
        ),
        {"sid": source_model_id},
    ).fetchall()
    storeys = []
    for gid, name, elevation in rows:
        try:
            value = float(elevation)
        except (TypeError, ValueError):
            continue
        storeys.append(StoreyFact(global_id=gid, name=name, elevation=value))
    storeys.sort(key=lambda s: (s.elevation, s.global_id))
    return storeys


def build_bands(storeys: list[StoreyFact]) -> list[DerivedBand]:
    """Scale-free gap clustering with a robust reference gap."""
    if not storeys:
        return []
    if len(storeys) == 1:
        return [DerivedBand(index=0, storeys=list(storeys))]

    gaps = [b.elevation - a.elevation for a, b in zip(storeys, storeys[1:])]
    span = storeys[-1].elevation - storeys[0].elevation
    epsilon = max(abs(span), 1.0) * 1e-9
    positive = sorted(g for g in gaps if g > epsilon)
    if not positive:
        return [DerivedBand(index=0, storeys=list(storeys))]

    # Outlier-robust reference: the largest gap AFTER discarding gaps that are
    # extreme multiples of the median positive gap.
    median = positive[len(positive) // 2]
    usable = [g for g in positive if g <= median * OUTLIER_GAP_MULTIPLE] or positive
    threshold = BAND_GAP_FRACTION * max(usable)

    bands = [DerivedBand(index=0, storeys=[storeys[0]])]
    for gap, storey in zip(gaps, storeys[1:]):
        if gap > threshold:
            bands.append(DerivedBand(index=len(bands), storeys=[storey]))
        else:
            bands[-1].storeys.append(storey)
    return bands


def _category_of(ifc_class: str | None) -> str | None:
    if not ifc_class:
        return None
    for category, prefixes in _CATEGORY_PREFIXES.items():
        if any(ifc_class.startswith(p) for p in prefixes):
            return category
    return None


def _storey_category_counts(session: Session, source_model_id: int) -> dict[str, dict[str, int]]:
    """{storey_global_id: {category: distinct entity count}} from BOTH access
    paths — effective membership and the denormalized scalar — as a union."""
    counts: dict[str, dict[str, set[str]]] = {}

    membership = session.execute(
        text(
            "SELECT m.storey_global_id, e.ifc_class, m.entity_global_id "
            "FROM entity_spatial_memberships m "
            "LEFT JOIN ifc_entities e ON e.id = m.entity_id "
            "WHERE m.source_model_id = :sid"
        ),
        {"sid": source_model_id},
    ).fetchall()
    scalar = session.execute(
        text(
            "SELECT canonical_json->'storey'->>'global_id', ifc_class, global_id "
            "FROM ifc_entities WHERE source_model_id = :sid "
            "AND canonical_json->'storey'->>'global_id' IS NOT NULL"
        ),
        {"sid": source_model_id},
    ).fetchall()

    for storey_gid, ifc_class, entity_gid in [*membership, *scalar]:
        if not storey_gid or not entity_gid:
            continue
        per = counts.setdefault(storey_gid, {})
        per.setdefault("entities", set()).add(entity_gid)
        category = _category_of(ifc_class)
        if category:
            per.setdefault(category, set()).add(entity_gid)

    return {
        gid: {category: len(members) for category, members in per.items()}
        for gid, per in counts.items()
    }


def _band_evidence(band: DerivedBand, by_storey: dict[str, dict[str, int]]) -> dict[str, int]:
    evidence: dict[str, int] = {}
    for storey in band.storeys:
        for category, count in by_storey.get(storey.global_id, {}).items():
            evidence[category] = evidence.get(category, 0) + count
    return evidence


def _name_evidence(band: DerivedBand) -> tuple[bool, bool]:
    """(all storey names look roof-like, any name looks reference-like)."""
    names = [s.name.casefold() for s in band.storeys if s.name]
    if not names:
        return False, False
    roof_like = all(any(token in n for token in _ROOF_TOKENS) for n in names)
    reference_like = any(any(token in n for token in _REFERENCE_TOKENS) for n in names)
    return roof_like, reference_like


def classify_band(band: DerivedBand, by_storey: dict[str, dict[str, int]]) -> None:
    """Classify one band in place from occupancy and name evidence (§5.5)."""
    e = band.evidence = _band_evidence(band, by_storey)
    spaces = e.get("spaces", 0)
    walls = e.get("walls", 0)
    openings = e.get("doors", 0) + e.get("windows", 0)
    furnishing = e.get("furnishing", 0)
    structure_only = e.get("roofs", 0) + e.get("slabs", 0)
    total = e.get("entities", 0)
    roof_named, reference_named = _name_evidence(band)

    strong = (walls > 0 and (openings > 0 or furnishing > 0 or spaces > 0)) or (
        spaces > 0 and (openings > 0 or furnishing > 0)
    )
    weak = walls > 0 or furnishing > 0 or e.get("stairs", 0) > 0
    spaces_only = spaces > 0 and not weak and openings == 0

    if spaces_only and not strong:
        # Spaces with no architectural corroboration at all (no walls, doors,
        # windows, furnishing, stairs) describe a service/duct level or a data
        # artifact as plausibly as a usable floor — the boundary case §5.5
        # requires to stay honest rather than resolved by fiat.
        band.classification = "uncertain"
        band.confidence = "low"
        band.reasons.append(
            f"{spaces} spaces are assigned here but no walls, openings, or furnishing "
            "corroborate an occupiable floor"
        )
    elif strong and not roof_named:
        band.classification = "occupiable"
        band.confidence = "high"
        band.reasons.append(
            f"strong occupancy evidence: {spaces} spaces, {walls} walls, "
            f"{openings} doors/windows, {furnishing} furnishing"
        )
    elif strong and roof_named:
        band.classification = "uncertain"
        band.confidence = "low"
        band.reasons.append(
            "storey names suggest a roof level but the band carries occupancy evidence"
        )
    elif total == 0:
        band.classification = "non_occupiable_reference"
        band.confidence = "high"
        band.reasons.append("no entities are assigned to this band's storeys")
    elif roof_named or (structure_only > 0 and not weak):
        band.classification = "non_occupiable_reference"
        band.confidence = "high" if roof_named else "medium"
        band.reasons.append(
            "roof-named storeys" if roof_named else "only structural elements, no occupancy evidence"
        )
    elif reference_named and not weak:
        band.classification = "non_occupiable_reference"
        band.confidence = "medium"
        band.reasons.append("reference-level names and no occupancy evidence")
    elif weak:
        band.classification = "occupiable"
        band.confidence = "medium"
        band.reasons.append("architectural elements present without space/opening corroboration")
    else:
        band.classification = "uncertain"
        band.confidence = "low"
        band.reasons.append("evidence is too sparse to classify this band")


def derive_floors(session: Session, source_model_id: int) -> dict[str, Any]:
    """The manifest `derived_floors` block for one model."""
    storeys = load_storeys(session, source_model_id)
    bands = build_bands(storeys)
    by_storey = _storey_category_counts(session, source_model_id)
    for band in bands:
        classify_band(band, by_storey)

    # A single-band model resolves normally whatever its evidence (§5.5).
    if len(bands) == 1 and bands[0].classification == "uncertain":
        bands[0].classification = "occupiable"
        bands[0].confidence = "medium"
        bands[0].reasons.append("single-level model; resolved as the one usable floor")

    ordinal = 0
    for band in bands:
        if band.classification == "occupiable":
            ordinal += 1
            band.occupiable_ordinal = ordinal

    reference_index: int | None = None
    reference_basis = "none"
    if bands:
        span = bands[-1].elevation_max - bands[0].elevation_min
        tolerance = abs(span) * 0.01
        for band in bands:
            if band.elevation_min - tolerance <= 0.0 <= band.elevation_max + tolerance:
                reference_index = band.index
                reference_basis = "elevation_zero"
                break
        if reference_index is None:
            reference_index = 0
            reference_basis = "lowest_band"

    return {
        "derivation_version": FLOOR_DERIVATION_VERSION,
        "reference_index": reference_index,
        "reference_basis": reference_basis,
        "interpretation_note": (
            f"{len(bands)} elevation bands from {len(storeys)} IfcBuildingStorey rows; "
            f"{sum(1 for b in bands if b.classification == 'occupiable')} classified occupiable"
        ),
        "bands": [
            {
                "id": f"floor:band:{band.index}",
                "index": band.index,
                "occupiable_ordinal": band.occupiable_ordinal,
                "storey_global_ids": [s.global_id for s in band.storeys],
                "storey_names": [s.name for s in band.storeys],
                "elevation_min": band.elevation_min,
                "elevation_max": band.elevation_max,
                "classification": band.classification,
                "confidence": band.confidence,
                "reasons": band.reasons[:4],
                "evidence": dict(sorted(band.evidence.items())),
            }
            for band in bands
        ],
    }
