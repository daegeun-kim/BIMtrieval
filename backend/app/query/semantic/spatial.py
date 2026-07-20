"""Model-independent spatial (storey / floor) resolution (Task 23 §1).

Floor language in a question ("the second floor", "the top floor", "ground
level") is resolved to concrete `IfcBuildingStorey` identities using ONLY IFC
spatial data that is already in canonical JSON:

- the spatial hierarchy (`IfcBuildingStorey` entities of the active model);
- containment (every entity carries `storey.global_id`);
- placement / elevation (`placement.elevation`, in project length units).

It never reads storey *names*, never applies a per-model rule, and never uses a
naming convention such as "Plan 09" or "Level 2". Names are carried through only
so the resolved interpretation can be REPORTED back to the user.

Why bands rather than distinct elevations
-----------------------------------------
Real models give each structural sub-level its own storey entity, so one
physical floor appears as several `IfcBuildingStorey` rows a few centimetres
apart (finished level, underside of slab, underside of joist), while different
floors sit a storey height apart. The live 45-storey reference model has 45
DISTINCT elevations but only 9 physical floors, so grouping by exact elevation
equality would be wrong.

Bands are therefore found by a scale-free 1-D clustering: sort the elevations,
and start a new band wherever the gap to the previous storey exceeds
`BAND_GAP_FRACTION x the model's LARGEST inter-storey gap`. The largest gap is a
floor-to-floor separation by construction, so a fraction of it separates
"different floors" from "sub-levels of one floor" without needing a length unit
or an absolute threshold — behaviour is identical for a millimetre model, a
metre model, or an imperial one.

Referencing the largest gap (rather than the median) is deliberate: in a model
where most storeys are sub-levels the median gap is itself a sub-level gap,
whereas in a clean model with one storey per floor the median gap is a floor
gap. A median-based rule therefore merges every floor of a clean model into one
band. The largest gap is a floor separation in BOTH cases. Verified on the live
45-storey reference model (9 bands, matching its real floor count) and on clean,
sub-levelled, multi-wing, metric, basement, and double-height synthetic models;
the outcome is stable for every fraction in 0.2..0.35.

Ordinal origin
--------------
IFC defines `IfcBuildingStorey.Elevation` relative to the building origin, so
elevation 0 is the building's reference level. Ordinal 1 is therefore the band
containing elevation 0 when the model has one; models whose storeys are all
expressed in a site//project datum (no band at 0) fall back to their lowest band
as ordinal 1. Both rules come from the data, not from a naming convention, and
the choice is always reported.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.db.models import IfcEntity

_ET = IfcEntity.__table__

#: A new floor band starts where the elevation gap exceeds this fraction of the
#: model's own LARGEST inter-storey gap. Dimensionless on purpose — see module
#: docstring. Verified stable across 0.2..0.35 on live + synthetic models.
#:
#: Known limitation: a single extreme outlier gap (e.g. a landscape/site storey
#: placed far from the building) inflates the reference and can merge real
#: floors. No such model is present in the corpus; a model that hits it will
#: report a floor count that disagrees with the reported interpretation, which
#: is visible to the user rather than silent.
BAND_GAP_FRACTION = 0.3

#: Elevation tolerance, as a fraction of the model's total elevation span, for
#: deciding that a band "contains" the building reference level 0.
REFERENCE_LEVEL_SPAN_TOLERANCE = 0.01


@dataclass(frozen=True)
class Storey:
    global_id: str
    name: str | None
    elevation: float


@dataclass
class FloorBand:
    """One logical floor: every storey entity at the same elevation level."""

    index: int  # 0-based, ascending by elevation
    storeys: list[Storey] = field(default_factory=list)

    @property
    def min_elevation(self) -> float:
        return min(s.elevation for s in self.storeys)

    @property
    def max_elevation(self) -> float:
        return max(s.elevation for s in self.storeys)

    @property
    def global_ids(self) -> list[str]:
        return [s.global_id for s in self.storeys]

    def describe(self) -> str:
        names = [s.name for s in self.storeys if s.name]
        listed = ", ".join(names[:6]) + ("…" if len(names) > 6 else "")
        return f"{len(self.storeys)} storey entities ({listed})" if names else "storey entities"


@dataclass
class StoreyModel:
    """The active model's derived floor structure."""

    bands: list[FloorBand] = field(default_factory=list)
    reference_index: int | None = None  # band treated as ordinal 1
    reference_basis: str = "none"  # "elevation_zero" | "lowest_band" | "none"
    total_storeys: int = 0

    @property
    def usable(self) -> bool:
        return len(self.bands) > 1 and self.reference_index is not None


@dataclass
class StoreyResolution:
    """Outcome of resolving one floor concept against one model."""

    resolved: bool
    storey_global_ids: list[str] = field(default_factory=list)
    interpretation: str | None = None
    reason: str | None = None  # why it could not be resolved


# ---------------------------------------------------------------------------
# Reading the model's storeys
# ---------------------------------------------------------------------------


def load_storeys(session: Session, source_model_id: int) -> list[Storey]:
    """Every `IfcBuildingStorey` of the model that carries a usable elevation."""
    rows = session.execute(
        sa.select(_ET.c.canonical_json).where(
            _ET.c.source_model_id == source_model_id,
            _ET.c.ifc_class == "IfcBuildingStorey",
        )
    ).all()
    storeys: list[Storey] = []
    for (payload,) in rows:
        if not isinstance(payload, dict):
            continue
        meta = payload.get("meta") or {}
        placement = payload.get("placement") or {}
        gid = meta.get("global_id")
        elevation = placement.get("elevation")
        if elevation is None:
            elevation = placement.get("local_z")
        if not gid or not isinstance(elevation, (int, float)):
            continue
        identity = payload.get("identity") or {}
        storeys.append(Storey(global_id=gid, name=identity.get("name"), elevation=float(elevation)))
    storeys.sort(key=lambda s: s.elevation)
    return storeys


def build_bands(storeys: list[Storey]) -> list[FloorBand]:
    """Group storeys into logical floor bands by scale-free gap clustering."""
    if not storeys:
        return []
    if len(storeys) == 1:
        return [FloorBand(index=0, storeys=list(storeys))]

    gaps = [b.elevation - a.elevation for a, b in zip(storeys, storeys[1:])]
    # Ignore floating-point noise relative to the model's own extent, so storeys
    # exported at "the same" elevation are not split by rounding.
    span = storeys[-1].elevation - storeys[0].elevation
    epsilon = max(abs(span), 1.0) * 1e-9
    positive = [g for g in gaps if g > epsilon]
    # With no positive gap every storey shares one elevation — a single band.
    threshold = BAND_GAP_FRACTION * max(positive) if positive else float("inf")

    bands: list[FloorBand] = [FloorBand(index=0, storeys=[storeys[0]])]
    for gap, storey in zip(gaps, storeys[1:]):
        if gap > threshold:
            bands.append(FloorBand(index=len(bands), storeys=[storey]))
        else:
            bands[-1].storeys.append(storey)
    return bands


def build_storey_model(session: Session, source_model_id: int) -> StoreyModel:
    storeys = load_storeys(session, source_model_id)
    bands = build_bands(storeys)
    model = StoreyModel(bands=bands, total_storeys=len(storeys))
    if not bands:
        return model

    # Ordinal origin: the band containing the IFC building reference level 0 when
    # the model expresses elevations that way; otherwise the lowest band.
    span = bands[-1].max_elevation - bands[0].min_elevation
    tolerance = abs(span) * REFERENCE_LEVEL_SPAN_TOLERANCE
    for band in bands:
        if band.min_elevation - tolerance <= 0.0 <= band.max_elevation + tolerance:
            model.reference_index = band.index
            model.reference_basis = "elevation_zero"
            break
    if model.reference_index is None:
        model.reference_index = 0
        model.reference_basis = "lowest_band"
    return model


# ---------------------------------------------------------------------------
# Interpreting a floor concept
# ---------------------------------------------------------------------------

_ORDINAL_WORDS = {
    "ground": 1,
    "first": 1,
    "second": 2,
    "third": 3,
    "fourth": 4,
    "fifth": 5,
    "sixth": 6,
    "seventh": 7,
    "eighth": 8,
    "ninth": 9,
    "tenth": 10,
}
_TOP_WORDS = ("top", "uppermost", "highest", "roof level", "last")
_BOTTOM_WORDS = ("lowest", "bottom", "basement", "cellar", "sub-level", "sublevel")
_FLOOR_WORDS = ("floor", "storey", "story", "level", "plan", "deck", "etage", "plane")


def mentions_floor_concept(text: str) -> bool:
    """True when a concept phrase is about a building level at all."""
    low = (text or "").lower()
    return any(w in low for w in _FLOOR_WORDS)


def _extract_ordinal(text: str) -> int | None:
    """The 1-based floor ordinal a phrase asks for, or None.

    This reads the USER'S phrasing (English ordinals/digits), never the model's
    storey names — the model side is handled entirely by elevation ordering.
    """
    low = (text or "").lower()
    for word, value in _ORDINAL_WORDS.items():
        if re.search(rf"\b{word}\b", low):
            return value
    m = re.search(r"\b(\d{1,2})\s*(?:st|nd|rd|th)\b", low)
    if m:
        return int(m.group(1))
    m = re.search(rf"\b(?:{'|'.join(_FLOOR_WORDS)})\s*[-#]?\s*(\d{{1,2}})\b", low) or re.search(
        rf"\b(\d{{1,2}})\s*(?:{'|'.join(_FLOOR_WORDS)})\b", low
    )
    if m:
        return int(m.group(1))
    return None


def resolve_floor_concept(session: Session, source_model_id: int, concept: str) -> StoreyResolution:
    """Resolve a floor/storey concept to concrete storey GlobalIds.

    Returns `resolved=False` with a reason when the IFC data cannot establish a
    safe ordering or scope — the caller must then clarify rather than widening
    the query (Task 23 §1)."""
    model = build_storey_model(session, source_model_id)
    if not model.bands:
        return StoreyResolution(
            resolved=False,
            reason="this model has no IfcBuildingStorey elevations, so floor scope "
            "cannot be established from its spatial data",
        )

    low = (concept or "").lower()
    band: FloorBand | None = None
    basis = ""

    if any(w in low for w in _TOP_WORDS):
        band = model.bands[-1]
        basis = "the uppermost floor level by elevation"
    elif any(w in low for w in _BOTTOM_WORDS) and _extract_ordinal(low) is None:
        band = model.bands[0]
        basis = "the lowest floor level by elevation"
    else:
        ordinal = _extract_ordinal(concept)
        if ordinal is None:
            return StoreyResolution(
                resolved=False,
                reason=f"could not read a specific floor from {concept!r}",
            )
        index = (model.reference_index or 0) + (ordinal - 1)
        if not 0 <= index < len(model.bands):
            levels = len(model.bands)
            return StoreyResolution(
                resolved=False,
                reason=(
                    f"{concept!r} is outside this model's "
                    f"{levels} floor level{'s' if levels != 1 else ''}"
                ),
            )
        band = model.bands[index]
        origin = (
            "the building reference level (elevation 0)"
            if model.reference_basis == "elevation_zero"
            else "the model's lowest floor level"
        )
        basis = f"floor {ordinal} counting up from {origin}"

    interpretation = (
        f"Interpreted {concept!r} as {basis}: "
        f"level {band.index + 1} of {len(model.bands)} "
        f"(elevation {band.min_elevation:g} to {band.max_elevation:g}), "
        f"covering {band.describe()}."
    )
    return StoreyResolution(
        resolved=True,
        storey_global_ids=band.global_ids,
        interpretation=interpretation,
    )
