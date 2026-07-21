"""Deterministic building profile for broad model summaries (Task 24 §11.2).

A question like "give me a summary of this building" has no single subject, and
§11.2 forbids answering it "by executing every semantic candidate group or
sending the model vocabulary to the final LLM". Instead this builds one bounded,
cached, high-level profile from resources that already exist:

- logical floor count (the elevation-band model, NOT a storey-entity count —
  §11.4 keeps those distinct);
- major occurrence-family counts, taken from the cached vocabulary;
- major space categories, from observed values;
- directly recorded material/property summaries;
- explicit limitations relevant to a summary.

It issues no per-class `COUNT(*)`: every number here comes from the cached model
vocabulary, so a summary costs roughly one storey read rather than dozens of
counting queries (§10.3).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.config.settings import Settings, get_settings
from app.query.semantic.roles import SchemaRole, get_role_index
from app.query.semantic.spatial import build_storey_model
from app.query.semantic.vocabulary.cache import get_model_vocabulary

__all__ = ["BuildingProfile", "build_building_profile"]

#: How many families/categories a summary may name. A summary is a summary.
_MAX_FAMILIES = 12
_MAX_CATEGORIES = 8
_MAX_MATERIALS = 8


@dataclass
class BuildingProfile:
    source_model_id: int
    #: Logical floors (elevation bands), and the raw storey entities they group.
    #: Both are reported because they are different facts and a summary that
    #: conflated them would contradict every floor-scoped answer (§11.4).
    logical_floor_count: int = 0
    storey_entity_count: int = 0
    total_entity_count: int = 0
    #: (ifc_class, count) for the largest occurrence families.
    occurrence_families: list[tuple[str, int]] = field(default_factory=list)
    #: (value, count) for the most common space categories.
    space_categories: list[tuple[str, int]] = field(default_factory=list)
    #: (material, count) directly recorded on entities.
    materials: list[tuple[str, int]] = field(default_factory=list)
    #: What this model genuinely does not record, relevant to a summary.
    limitations: list[str] = field(default_factory=list)
    statement_count: int = 0

    def to_payload(self) -> dict:
        """Compact form for the answer packet — no vocabulary dump (§11.2)."""
        payload: dict = {
            "logical_floor_count": self.logical_floor_count,
            "storey_entity_count": self.storey_entity_count,
            "total_objects": self.total_entity_count,
            "major_families": [{"ifc_class": c, "count": n} for c, n in self.occurrence_families],
        }
        if self.space_categories:
            payload["space_categories"] = [
                {"category": v, "count": n} for v, n in self.space_categories
            ]
        if self.materials:
            payload["materials"] = [{"material": v, "count": n} for v, n in self.materials]
        if self.limitations:
            payload["limitations"] = self.limitations
        return payload


def build_building_profile(
    session: Session, source_model_id: int, settings: Settings | None = None
) -> BuildingProfile:
    """Bounded high-level profile of one model, from cached resources."""
    settings = settings or get_settings()
    vocab = get_model_vocabulary(session, source_model_id, settings)
    profile = BuildingProfile(source_model_id=source_model_id)

    storey_model = build_storey_model(session, source_model_id)
    profile.statement_count += 1
    profile.logical_floor_count = len(storey_model.bands)
    profile.storey_entity_count = storey_model.total_storeys

    try:
        role_index = get_role_index(vocab.ifc_schema or "IFC2X3")
    except Exception:  # noqa: BLE001 - degrade truthfully without roles
        role_index = None

    entity_profiles = [c for c in vocab.classes if c.kind == "entity"]
    profile.total_entity_count = sum(c.instance_count for c in entity_profiles)

    # Only genuine occurrence families belong in a summary: listing type
    # definitions or property definitions among "what the building contains"
    # would misdescribe the model (§3.2).
    families = [
        (c.ifc_class, c.instance_count)
        for c in entity_profiles
        if role_index is None or role_index.role(c.ifc_class) is SchemaRole.OCCURRENCE
    ]
    families.sort(key=lambda pair: (-pair[1], pair[0]))
    profile.occurrence_families = families[:_MAX_FAMILIES]

    profile.space_categories = _top_values(vocab, "object_type", "IfcSpace", _MAX_CATEGORIES)
    profile.materials = _top_values(vocab, "material", None, _MAX_MATERIALS)
    profile.limitations = _limitations(vocab, storey_model)
    return profile


def _top_values(vocab, fact_kind: str, ifc_class: str | None, limit: int) -> list[tuple[str, int]]:
    seen: dict[str, int] = {}
    for fact in vocab.facts:
        if fact.fact_kind != fact_kind:
            continue
        if ifc_class is not None and fact.ifc_class != ifc_class:
            continue
        seen[fact.observed_value] = seen.get(fact.observed_value, 0) + fact.occurrence_count
    return sorted(seen.items(), key=lambda pair: (-pair[1], pair[0]))[:limit]


def _limitations(vocab, storey_model) -> list[str]:
    """Only limitations a SUMMARY would misrepresent by omitting."""
    limitations: list[str] = []
    if not vocab.quantities:
        limitations.append(
            "this model records no quantity sets, so areas, volumes and other measured "
            "quantities cannot be reported"
        )
    if not any(f.fact_kind == "material" for f in vocab.facts):
        limitations.append("this model records no material assignments")
    if not storey_model.bands:
        limitations.append(
            "this model's storeys carry no elevations, so floor levels cannot be derived"
        )
    return limitations
