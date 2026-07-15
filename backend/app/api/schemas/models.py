"""Schemas for the narrow frontend viewer contract (spec_v006 §10; Task 10).

Every field is allowlisted (`extra="forbid"`) and bounded so Task 11 can
generate reproducible TypeScript contracts from OpenAPI. No file path, canonical
JSON, credential, or ingestion internal ever appears on these models.
"""

from __future__ import annotations

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
