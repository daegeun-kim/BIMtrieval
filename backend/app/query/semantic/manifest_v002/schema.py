"""Typed reader model for manifest v002 (task26 §5).

One flat namespace of selectable semantic records — capabilities, traversal
contracts, derived floor bands, profiles, and raw storeys — so an arbitrary
binder-selected ID validates against a single lookup. Applicability is kept per
subject class exactly as the artifact records it; nothing here re-aggregates
coverage across classes (§1.3 is the defect that would reintroduce).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

MANIFEST_SCHEMA_VERSION_V002 = "v002"

COVERAGE_PRESENT_COMPLETE = "present_complete"
COVERAGE_PRESENT_PARTIAL = "present_partial"
COVERAGE_CHECKED_ABSENT = "checked_absent"
COVERAGE_SOURCE_UNRESOLVABLE = "source_unresolvable"
COVERAGE_EXTRACTOR_UNSUPPORTED = "extractor_unsupported"
COVERAGE_EXTRACTION_FAILED = "extraction_failed"

#: States under which a capability must NOT be executed for the subject.
NON_QUERYABLE_COVERAGE = frozenset(
    {
        COVERAGE_SOURCE_UNRESOLVABLE,
        COVERAGE_EXTRACTOR_UNSUPPORTED,
        COVERAGE_EXTRACTION_FAILED,
    }
)


@dataclass(frozen=True)
class Applicability:
    """One (capability × subject class) coverage fact."""

    subject: str
    coverage: str
    known_count: int
    eligible_count: int
    distinct_value_count: int = 0
    unit_state: str = "not_applicable"
    unit: str | None = None
    can_prove_absence: bool = False

    @property
    def queryable(self) -> bool:
        return self.coverage not in NON_QUERYABLE_COVERAGE

    @property
    def complete(self) -> bool:
        return self.coverage == COVERAGE_PRESENT_COMPLETE


@dataclass(frozen=True)
class Capability:
    """One selectable capability record (class, field, spatial, derived)."""

    semantic_id: str
    kind: str
    label: str
    aliases: tuple[str, ...] = ()
    grain: str = "entity"
    uses: tuple[str, ...] = ()
    data_type: str | None = None
    operators: tuple[str, ...] = ()
    accessor: str = ""
    executable: bool = False
    limitation: str | None = None
    applicability: tuple[Applicability, ...] = ()
    value_policy: str = "none"
    values: tuple[tuple[str, int], ...] = ()
    provenance: tuple[str, ...] = ()
    #: Backend-only structured physical addressing (never projected):
    #: {"source": "property_sets"|"quantity_sets"|"attribute"|"type_fact"|
    #:  "materials"|"classifications", "set": ..., "field": ..., "path": [...]}.
    physical: dict[str, Any] | None = None

    def supports_use(self, use: str) -> bool:
        return use in self.uses

    def supports_operator(self, operator: str) -> bool:
        return not self.operators or operator in self.operators

    def applicability_for(self, subject: str) -> Applicability | None:
        return next((a for a in self.applicability if a.subject == subject), None)

    def subjects(self) -> tuple[str, ...]:
        return tuple(a.subject for a in self.applicability)

    def applies_to(self, subject: str) -> bool:
        """True when the capability is executable FOR this subject class.

        A subject absent from the applicability list is `checked_absent` when
        the capability can prove absence at all (the extractor scanned every
        row), and unknown otherwise — either way it is not a subject this
        capability can filter usefully, and validation treats selecting it as
        an applicability error (§9.1 layer 4).
        """
        return self.applicability_for(subject) is not None

    @property
    def ifc_class(self) -> str | None:
        """The IFC class of a `cls:` capability."""
        if self.kind == "class" and self.semantic_id.startswith("cls:"):
            return self.semantic_id[4:]
        return None

    @property
    def search_text(self) -> str:
        return " ".join((self.label, *self.aliases))


@dataclass(frozen=True)
class Traversal:
    """One typed relationship role-pair contract (§5.4)."""

    semantic_id: str
    relationship: str
    label: str
    aliases: tuple[str, ...] = ()
    from_role: str = ""
    to_role: str = ""
    direction: str = "outgoing"
    from_classes: tuple[str, ...] = ()
    to_classes: tuple[str, ...] = ()
    relationship_count: int = 0
    resolved_from_count: int = 0
    resolved_to_count: int = 0
    endpoint_fact_resolvable: bool = False
    endpoint_entity_resolvable: bool = False
    endpoint_viewer_hydratable: bool = False
    max_supported_hops: int = 1

    @property
    def search_text(self) -> str:
        return " ".join((self.label, *self.aliases))


@dataclass(frozen=True)
class FloorBand:
    """One derived elevation band with its occupancy classification (§5.5)."""

    semantic_id: str
    index: int
    occupiable_ordinal: int | None
    storey_global_ids: tuple[str, ...]
    storey_names: tuple[str | None, ...]
    elevation_min: float
    elevation_max: float
    classification: str
    confidence: str
    reasons: tuple[str, ...]
    evidence: dict[str, int]

    @property
    def occupiable(self) -> bool:
        return self.classification == "occupiable"

    @property
    def uncertain(self) -> bool:
        return self.classification == "uncertain"

    def describe(self) -> str:
        names = [n for n in self.storey_names if n]
        listed = ", ".join(names[:5]) + ("…" if len(names) > 5 else "")
        return (
            f"band {self.index + 1} ({self.classification}), elevation "
            f"{self.elevation_min:g}..{self.elevation_max:g}, "
            f"{len(self.storey_global_ids)} storey entities"
            + (f" ({listed})" if listed else "")
        )


@dataclass
class DerivedFloors:
    derivation_version: str = ""
    reference_index: int | None = None
    reference_basis: str = "none"
    interpretation_note: str = ""
    bands: list[FloorBand] = field(default_factory=list)

    def occupiable_bands(self) -> list[FloorBand]:
        return [b for b in self.bands if b.occupiable]

    def uncertain_bands(self) -> list[FloorBand]:
        return [b for b in self.bands if b.uncertain]

    def band_for_ordinal(self, ordinal: int) -> FloorBand | None:
        return next((b for b in self.bands if b.occupiable_ordinal == ordinal), None)

    def top_occupiable(self) -> FloorBand | None:
        occupiable = self.occupiable_bands()
        return occupiable[-1] if occupiable else None

    def band(self, semantic_id: str) -> FloorBand | None:
        return next((b for b in self.bands if b.semantic_id == semantic_id), None)


@dataclass(frozen=True)
class Profile:
    semantic_id: str
    label: str
    aliases: tuple[str, ...] = ()
    accessor: str = ""
    uses: tuple[str, ...] = ()

    @property
    def search_text(self) -> str:
        return " ".join((self.label, *self.aliases))


@dataclass(frozen=True)
class StoreyRecord:
    semantic_id: str
    global_id: str
    name: str | None
    elevation: float | None


@dataclass(frozen=True)
class SpatialClassSummary:
    ifc_class: str
    direct_count: int
    aggregated_count: int
    effective_count: int
    total_count: int


@dataclass
class ManifestV002:
    """A loaded, validated v002 manifest for one source model."""

    source_model_id: int
    file_fingerprint: str
    file_name: str
    ifc_schema: str | None
    extraction_version: str
    content_hash: str
    builder_version: str
    contract_version: str
    entity_total: int = 0
    class_inventory: dict[str, int] = field(default_factory=dict)
    capabilities: dict[str, Capability] = field(default_factory=dict)
    traversals: dict[str, Traversal] = field(default_factory=dict)
    floors: DerivedFloors = field(default_factory=DerivedFloors)
    profiles: dict[str, Profile] = field(default_factory=dict)
    storeys: dict[str, StoreyRecord] = field(default_factory=dict)
    spatial_by_class: dict[str, SpatialClassSummary] = field(default_factory=dict)

    # -- uniform lookup ------------------------------------------------------

    def get(self, semantic_id: str) -> Any | None:
        """Any selectable record by ID, across every namespace."""
        return (
            self.capabilities.get(semantic_id)
            or self.traversals.get(semantic_id)
            or self.profiles.get(semantic_id)
            or self.storeys.get(semantic_id)
            or self.floors.band(semantic_id)
        )

    def all_ids(self) -> set[str]:
        return (
            set(self.capabilities)
            | set(self.traversals)
            | set(self.profiles)
            | set(self.storeys)
            | {b.semantic_id for b in self.floors.bands}
        )

    def capabilities_of_kind(self, *kinds: str) -> list[Capability]:
        wanted = frozenset(kinds)
        return [c for c in self.capabilities.values() if c.kind in wanted]

    def class_capability(self, ifc_class: str) -> Capability | None:
        return self.capabilities.get(f"cls:{ifc_class}")

    def present_classes(self) -> frozenset[str]:
        return frozenset(self.class_inventory)

    def size_report(self) -> dict[str, int]:
        return {
            "capabilities": len(self.capabilities),
            "traversals": len(self.traversals),
            "floor_bands": len(self.floors.bands),
            "profiles": len(self.profiles),
            "storeys": len(self.storeys),
        }


# ---------------------------------------------------------------------------
# Document -> typed model
# ---------------------------------------------------------------------------


def parse_manifest_v002(document: dict[str, Any]) -> ManifestV002:
    identity = document["identity"]
    content = document["content"]

    manifest = ManifestV002(
        source_model_id=int(identity["source_model_id"]),
        file_fingerprint=identity["file_fingerprint"],
        file_name=identity.get("file_name", ""),
        ifc_schema=identity.get("ifc_schema"),
        extraction_version=identity.get("extraction_version", ""),
        content_hash=identity["content_hash"],
        builder_version=identity["builder_version"],
        contract_version=identity["contract_version"],
        entity_total=int(content.get("entity_total", 0)),
        class_inventory={
            r["ifc_class"]: int(r["count"]) for r in content.get("class_inventory", ())
        },
    )

    for record in content.get("capabilities", ()):
        capability = Capability(
            semantic_id=record["id"],
            kind=record["kind"],
            label=record.get("label", record["id"]),
            aliases=tuple(record.get("aliases", ())),
            grain=record.get("grain", "entity"),
            uses=tuple(record.get("uses", ())),
            data_type=record.get("data_type"),
            operators=tuple(record.get("operators", ())),
            accessor=record.get("accessor", ""),
            executable=bool(record.get("executable")),
            limitation=record.get("limitation"),
            applicability=tuple(
                Applicability(
                    subject=a["subject"],
                    coverage=a["coverage"],
                    known_count=int(a.get("known_count", 0)),
                    eligible_count=int(a.get("eligible_count", 0)),
                    distinct_value_count=int(a.get("distinct_value_count", 0)),
                    unit_state=a.get("unit_state", "not_applicable"),
                    unit=a.get("unit"),
                    can_prove_absence=bool(a.get("can_prove_absence")),
                )
                for a in record.get("applicability", ())
            ),
            value_policy=record.get("value_policy", "none"),
            values=tuple(
                (v["value"], int(v["count"])) for v in record.get("values", ())
            ),
            provenance=tuple(record.get("provenance", ())),
            physical=record.get("physical"),
        )
        manifest.capabilities[capability.semantic_id] = capability

    for record in content.get("traversals", ()):
        traversal = Traversal(
            semantic_id=record["id"],
            relationship=record["relationship"],
            label=record.get("label", record["id"]),
            aliases=tuple(record.get("aliases", ())),
            from_role=record["from_role"],
            to_role=record["to_role"],
            direction=record.get("direction", "outgoing"),
            from_classes=tuple(record.get("from_classes", ())),
            to_classes=tuple(record.get("to_classes", ())),
            relationship_count=int(record.get("relationship_count", 0)),
            resolved_from_count=int(record.get("resolved_from_count", 0)),
            resolved_to_count=int(record.get("resolved_to_count", 0)),
            endpoint_fact_resolvable=bool(record.get("endpoint_fact_resolvable")),
            endpoint_entity_resolvable=bool(record.get("endpoint_entity_resolvable")),
            endpoint_viewer_hydratable=bool(record.get("endpoint_viewer_hydratable")),
            max_supported_hops=int(record.get("max_supported_hops", 1)),
        )
        manifest.traversals[traversal.semantic_id] = traversal

    floors = content.get("derived_floors", {})
    manifest.floors = DerivedFloors(
        derivation_version=floors.get("derivation_version", ""),
        reference_index=floors.get("reference_index"),
        reference_basis=floors.get("reference_basis", "none"),
        interpretation_note=floors.get("interpretation_note", ""),
        bands=[
            FloorBand(
                semantic_id=band["id"],
                index=int(band["index"]),
                occupiable_ordinal=band.get("occupiable_ordinal"),
                storey_global_ids=tuple(band.get("storey_global_ids", ())),
                storey_names=tuple(band.get("storey_names", ())),
                elevation_min=float(band["elevation_min"]),
                elevation_max=float(band["elevation_max"]),
                classification=band["classification"],
                confidence=band.get("confidence", "low"),
                reasons=tuple(band.get("reasons", ())),
                evidence=dict(band.get("evidence", {})),
            )
            for band in floors.get("bands", ())
        ],
    )

    for record in content.get("profiles", ()):
        profile = Profile(
            semantic_id=record["id"],
            label=record.get("label", record["id"]),
            aliases=tuple(record.get("aliases", ())),
            accessor=record.get("accessor", ""),
            uses=tuple(record.get("uses", ())),
        )
        manifest.profiles[profile.semantic_id] = profile

    for record in content.get("storeys", ()):
        storey = StoreyRecord(
            semantic_id=record["id"],
            global_id=record["global_id"],
            name=record.get("name"),
            elevation=record.get("elevation"),
        )
        manifest.storeys[storey.semantic_id] = storey

    for record in content.get("spatial_membership", {}).get("by_class", ()):
        manifest.spatial_by_class[record["ifc_class"]] = SpatialClassSummary(
            ifc_class=record["ifc_class"],
            direct_count=int(record["direct_count"]),
            aggregated_count=int(record["aggregated_count"]),
            effective_count=int(record["effective_count"]),
            total_count=int(record["total_count"]),
        )

    return manifest
