"""Schemas for the narrow frontend viewer contract (spec_v006 §10; Task 10).

Every field is allowlisted (`extra="forbid"`) and bounded so Task 11 can
generate reproducible TypeScript contracts from OpenAPI. No file path, canonical
JSON, credential, or ingestion internal ever appears on these models.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from app.shared.types import ViewerAssetStatus

MAX_RESOLVE_GLOBAL_IDS = 5


class ModelListItem(BaseModel):
    """One entry in the deterministic model selector (spec_v006 §10.1)."""

    model_config = ConfigDict(extra="forbid")

    source_model_id: int
    display_name: str
    # Opaque source fingerprint / asset version — used for cache-key and status,
    # not a filesystem path.
    source_fingerprint: str
    viewer_asset_status: ViewerAssetStatus


class ModelListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    models: list[ModelListItem] = Field(default_factory=list)


class ResolveEntitiesRequest(BaseModel):
    """Active-model-scoped GlobalId resolution request (spec_v006 §10.3)."""

    model_config = ConfigDict(extra="forbid")

    global_ids: list[str] = Field(min_length=1, max_length=MAX_RESOLVE_GLOBAL_IDS)


class ResolvedEntity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entity_id: int
    global_id: str
    ifc_class: str
    name: str | None = None


class ResolveEntitiesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_model_id: int
    resolved: list[ResolvedEntity] = Field(default_factory=list)
    unresolved: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Component details (task13 §4)
# ---------------------------------------------------------------------------


class DetailValue(BaseModel):
    """One allowlisted, length-bounded property/quantity value."""

    model_config = ConfigDict(extra="forbid")

    name: str
    value: str
    # The property/quantity set the value came from — shown for transparency.
    source_set: str | None = None
    unit: str | None = None


class InstanceDetails(BaseModel):
    """Always available for a valid entity (task13 §4)."""

    model_config = ConfigDict(extra="forbid")

    global_id: str
    ifc_class: str
    name: str | None = None
    description: str | None = None
    object_type: str | None = None
    predefined_type: str | None = None
    tag: str | None = None
    storey_name: str | None = None
    storey_global_id: str | None = None
    elevation: float | None = None
    materials: list[str] = Field(default_factory=list)
    quantities: list[DetailValue] = Field(default_factory=list)
    properties: list[DetailValue] = Field(default_factory=list)


class TypeDetails(BaseModel):
    """Present ONLY when the source IFC explicitly supplied type information
    that ingestion stored. Never inferred from name/class/material/LLM."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    global_id: str | None = None
    ifc_class: str | None = None
    predefined_type: str | None = None


class FamilyDetails(BaseModel):
    """Present ONLY when an allowlisted family-like property exists in a stored
    property set. The source set/property are returned for transparency."""

    model_config = ConfigDict(extra="forbid")

    value: str
    property_set: str
    property_name: str


class DetailAvailability(BaseModel):
    """Truthful availability of each deterministic group action (task13 §4)."""

    model_config = ConfigDict(extra="forbid")

    instance: bool = True
    same_type: bool = False
    same_family: bool = False
    # Concise reason the frontend can show on a disabled action.
    type_unavailable_reason: str | None = None
    family_unavailable_reason: str | None = None


class EntityDetailsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_model_id: int
    instance: InstanceDetails
    # Omitted entirely when the model has no explicit type/family data, so the
    # frontend renders nothing rather than an empty placeholder.
    type: TypeDetails | None = None
    family: FamilyDetails | None = None
    availability: DetailAvailability


# ---------------------------------------------------------------------------
# Deterministic instance/type/family group matching (task13 §5)
# ---------------------------------------------------------------------------


class HighlightScope(str, Enum):
    INSTANCE = "instance"
    TYPE = "type"
    FAMILY = "family"


class HighlightGroupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    selected_global_id: str = Field(min_length=1)
    scope: HighlightScope


class HighlightGroupResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_model_id: int
    scope: HighlightScope
    # False when the model has no explicit type/family data for this entity —
    # an expected, truthful result, not an error.
    available: bool
    unavailable_reason: str | None = None
    # Exact total matches, never reduced by the identity cap below.
    total: int = 0
    global_ids: list[str] = Field(default_factory=list)
    truncated: bool = False
    class_counts: dict[str, int] = Field(default_factory=dict)
