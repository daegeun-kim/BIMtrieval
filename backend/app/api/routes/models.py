"""Narrow, deterministic, read-only viewer contracts (spec_v006 §10; Tasks 10, 13).

Capabilities the frontend needs, none of which invoke an LLM, create an
embedding, parse IFC, convert geometry, write the database, mutate session
history, or expose a filesystem path:

    GET  /api/models                                       -> bounded selector list
    GET  /api/models/{id}/viewer-asset                     -> stream prepared artifact
    POST /api/models/{id}/entities/resolve                 -> GlobalId -> compact identity
    GET  /api/models/{id}/entities/{gid}/details           -> truthful bounded details
    POST /api/models/{id}/entities/highlight-group         -> instance/type/family matches

All database access is read-only through the backend's configured role and is
injected via `get_db` so it can be overridden in offline tests.
"""

from __future__ import annotations

from typing import Iterator

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.schemas.models import (
    DetailAvailability,
    DetailValue,
    EntityDetailsResponse,
    FamilyDetails,
    HighlightGroupRequest,
    HighlightGroupResponse,
    HighlightScope,
    InstanceDetails,
    ModelListItem,
    ModelListResponse,
    ResolvedEntity,
    ResolveEntitiesRequest,
    ResolveEntitiesResponse,
    TypeDetails,
)
from app.config.settings import get_settings
from app.db.session import session_scope
from app.query.selection import normalize_global_ids
from app.query.sql import catalog as catalog_ops
from app.query.sql import entities as entity_ops
from app.shared.types import ViewerAssetStatus
from app.viewer import details as detail_ops
from app.viewer.assets import (
    VIEWER_ASSET_SUFFIX,
    compute_asset_status,
    expected_asset_path,
    is_contained,
)

# Bounded, user-facing reasons for a disabled action. Deliberately generic: they
# describe the model's data, never internals.
_NO_TYPE_REASON = "This model has no explicit IFC type data for this object."
_NO_FAMILY_REASON = "This model has no explicit family property for this object."

router = APIRouter(prefix="/api/models", tags=["models"])

_CACHE_CONTROL = "private, max-age=0, must-revalidate"


def get_db() -> Iterator[Session]:
    """Yield a read-only session; overridable in tests via dependency_overrides."""
    with session_scope() as session:
        yield session


@router.get("", response_model=ModelListResponse)
def list_models(session: Session = Depends(get_db)) -> ModelListResponse:
    """Deterministic bounded model list for the display-name selector."""
    root = get_settings().get_viewer_asset_root()
    items: list[ModelListItem] = []
    for row in catalog_ops.list_selector_models(session):
        # Safe default display name when the editable name is null (Task 10 §1).
        display = row.display_name or f"Model {row.source_model_id}"
        status = compute_asset_status(
            root,
            row.source_model_id,
            row.source_fingerprint,
            catalog_status=row.status,
        )
        items.append(
            ModelListItem(
                source_model_id=row.source_model_id,
                display_name=display,
                source_fingerprint=row.source_fingerprint,
                viewer_asset_status=status,
            )
        )
    return ModelListResponse(models=items)


@router.get("/{source_model_id}/viewer-asset")
def viewer_asset(
    source_model_id: int,
    request: Request,
    session: Session = Depends(get_db),
) -> Response:
    """Stream the prepared viewer artifact for an existing model (spec_v006 §9.3).

    Verifies model existence, derives + contains the expected path, distinguishes
    missing/stale/unavailable with bounded responses, streams (never loads the
    whole file into memory), and supports fingerprint ETag / conditional GET.
    Never returns a server path in body, headers, or errors.
    """
    root = get_settings().get_viewer_asset_root()
    identity = catalog_ops.get_model_asset_identity(session, source_model_id)
    if identity is None:
        raise HTTPException(
            status_code=404,
            detail={"status": "unknown_model", "message": "model not found"},
        )

    status = compute_asset_status(
        root, source_model_id, identity.source_fingerprint, catalog_status=identity.status
    )

    if status is ViewerAssetStatus.MISSING:
        raise HTTPException(
            status_code=404,
            detail={"status": "missing", "message": "viewer asset not prepared"},
        )
    if status is ViewerAssetStatus.STALE:
        raise HTTPException(
            status_code=409,
            detail={"status": "stale", "message": "viewer asset is stale"},
        )
    if status is not ViewerAssetStatus.READY:
        raise HTTPException(
            status_code=503,
            detail={"status": "unavailable", "message": "viewer asset unavailable"},
        )

    path = expected_asset_path(root, source_model_id, identity.source_fingerprint)
    # Defense in depth: never serve anything outside the configured root.
    if not is_contained(root, path):
        raise HTTPException(
            status_code=503,
            detail={"status": "unavailable", "message": "viewer asset unavailable"},
        )

    etag = f'"{identity.source_fingerprint}"'
    if_none_match = request.headers.get("if-none-match")
    if if_none_match and etag in {tag.strip() for tag in if_none_match.split(",")}:
        return Response(
            status_code=304,
            headers={"ETag": etag, "Cache-Control": _CACHE_CONTROL},
        )

    # FileResponse streams in chunks and supports HTTP Range automatically; the
    # download filename is derived from the fingerprint, never a server path.
    return FileResponse(
        path,
        media_type="application/octet-stream",
        filename=f"{identity.source_fingerprint}{VIEWER_ASSET_SUFFIX}",
        headers={"ETag": etag, "Cache-Control": _CACHE_CONTROL},
    )


@router.post("/{source_model_id}/entities/resolve", response_model=ResolveEntitiesResponse)
def resolve_entities(
    source_model_id: int,
    payload: ResolveEntitiesRequest,
    session: Session = Depends(get_db),
) -> ResolveEntitiesResponse:
    """Active-model-scoped GlobalId -> compact identity (spec_v006 §10.3)."""
    if catalog_ops.get_model_asset_identity(session, source_model_id) is None:
        raise HTTPException(
            status_code=404,
            detail={"status": "unknown_model", "message": "model not found"},
        )

    gids = normalize_global_ids(payload.global_ids)
    if not gids:
        raise HTTPException(
            status_code=422,
            detail={"status": "invalid", "message": "no valid global_ids after trimming"},
        )

    rows = entity_ops.resolve_entities_by_global_ids(session, source_model_id, gids)
    by_gid = {row.global_id: row for row in rows}
    resolved = [
        ResolvedEntity(
            entity_id=by_gid[g].id,
            global_id=g,
            ifc_class=by_gid[g].ifc_class,
            name=by_gid[g].name,
        )
        for g in gids
        if g in by_gid
    ]
    unresolved = [g for g in gids if g not in by_gid]
    return ResolveEntitiesResponse(
        source_model_id=source_model_id, resolved=resolved, unresolved=unresolved
    )


# ---------------------------------------------------------------------------
# Component details (task13 §4)
# ---------------------------------------------------------------------------


def _require_entity(session: Session, source_model_id: int, global_id: str):
    """Load an entity scoped to the model, or 404 without leaking existence.

    A GlobalId belonging to another model produces the same bounded 404 as one
    that does not exist at all — the response never reveals cross-model
    existence (task13 §4).
    """
    gid = (global_id or "").strip()
    row = entity_ops.get_entity_canonical(session, source_model_id, gid) if gid else None
    if row is None:
        raise HTTPException(
            status_code=404,
            detail={"status": "unknown_entity", "message": "entity not found in this model"},
        )
    return row


def _detail_values(values) -> list[DetailValue]:
    return [
        DetailValue(name=v.name, value=v.value, source_set=v.source_set, unit=v.unit)
        for v in values
    ]


@router.get("/{source_model_id}/entities/{global_id}/details", response_model=EntityDetailsResponse)
def entity_details(
    source_model_id: int,
    global_id: str,
    session: Session = Depends(get_db),
) -> EntityDetailsResponse:
    """Truthful, bounded, allowlisted component details (task13 §4).

    Deterministic and LLM-free — no OpenAI call, no embedding, no IFC parse, no
    database write. Reads only the canonical JSON ingestion already stored.

    Type and family appear only when the source IFC explicitly supplied them;
    they are never inferred from the object's name, class, or material. For the
    current Schependomlaan model both are expected to be absent, and that is a
    valid result rather than an error.
    """
    row = _require_entity(session, source_model_id, global_id)
    canonical = row.canonical_json if isinstance(row.canonical_json, dict) else {}

    identity = canonical.get("identity") if isinstance(canonical.get("identity"), dict) else {}
    meta = canonical.get("meta") if isinstance(canonical.get("meta"), dict) else {}
    storey_name, storey_gid = detail_ops.storey_of(canonical)

    instance = InstanceDetails(
        global_id=row.global_id,
        ifc_class=row.ifc_class,
        name=detail_ops.safe_str(identity.get("name")),
        description=detail_ops.safe_str(identity.get("description")),
        object_type=detail_ops.safe_str(identity.get("object_type")),
        predefined_type=detail_ops.safe_str(meta.get("predefined_type")),
        tag=detail_ops.safe_str(identity.get("tag")),
        storey_name=storey_name,
        storey_global_id=storey_gid,
        elevation=detail_ops.elevation_of(canonical),
        materials=detail_ops.select_materials(canonical),
        quantities=_detail_values(detail_ops.select_quantities(canonical)),
        properties=_detail_values(detail_ops.select_properties(canonical)),
    )

    type_fact = detail_ops.find_type(canonical)
    type_details = None
    if type_fact is not None:
        # The type's own IFC class is reported only if that type object was
        # itself ingested as an entity in this model — never guessed.
        type_class = (
            entity_ops.get_ifc_class_for_global_id(session, source_model_id, type_fact.global_id)
            if type_fact.global_id
            else None
        )
        type_details = TypeDetails(
            name=type_fact.name,
            global_id=type_fact.global_id,
            ifc_class=type_class,
            predefined_type=type_fact.predefined_type,
        )

    family_fact = detail_ops.find_family(canonical)
    family_details = (
        FamilyDetails(
            value=family_fact.value,
            property_set=family_fact.property_set,
            property_name=family_fact.property_name,
        )
        if family_fact is not None
        else None
    )

    return EntityDetailsResponse(
        source_model_id=source_model_id,
        instance=instance,
        type=type_details,
        family=family_details,
        availability=DetailAvailability(
            instance=True,
            same_type=type_details is not None,
            same_family=family_details is not None,
            type_unavailable_reason=None if type_details is not None else _NO_TYPE_REASON,
            family_unavailable_reason=None if family_details is not None else _NO_FAMILY_REASON,
        ),
    )


# ---------------------------------------------------------------------------
# Deterministic instance/type/family group matching (task13 §5)
# ---------------------------------------------------------------------------


def _unavailable(
    source_model_id: int, scope: HighlightScope, reason: str
) -> HighlightGroupResponse:
    return HighlightGroupResponse(
        source_model_id=source_model_id,
        scope=scope,
        available=False,
        unavailable_reason=reason,
    )


@router.post("/{source_model_id}/entities/highlight-group", response_model=HighlightGroupResponse)
def highlight_group(
    source_model_id: int,
    payload: HighlightGroupRequest,
    session: Session = Depends(get_db),
) -> HighlightGroupResponse:
    """Deterministic instance/type/family match set for the component panel
    (task13 §5).

    Exists solely for the panel's buttons: it creates no chat message, calls no
    LLM, creates no embedding, and mutates no session history. Every lookup is
    scoped to the route model. Returns the exact total plus at most
    `max_viewer_match_ids` deterministically ordered GlobalIds.
    """
    row = _require_entity(session, source_model_id, payload.selected_global_id)
    canonical = row.canonical_json if isinstance(row.canonical_json, dict) else {}
    limit = get_settings().max_viewer_match_ids
    scope = payload.scope

    if scope is HighlightScope.INSTANCE:
        ident, class_counts = entity_ops.match_instance(
            session, source_model_id, row.global_id, limit
        )
    elif scope is HighlightScope.TYPE:
        type_fact = detail_ops.find_type(canonical)
        if type_fact is None:
            return _unavailable(source_model_id, scope, _NO_TYPE_REASON)
        # Prefer the exact explicit type GlobalId; fall back to the exact
        # normalized stored type name only when the IFC gave no GlobalId.
        if type_fact.global_id:
            ident, class_counts = entity_ops.match_by_type_global_id(
                session, source_model_id, type_fact.global_id, limit
            )
        elif type_fact.name:
            ident, class_counts = entity_ops.match_by_type_name(
                session, source_model_id, type_fact.name, limit
            )
        else:  # pragma: no cover - find_type guarantees name or global_id
            return _unavailable(source_model_id, scope, _NO_TYPE_REASON)
    else:
        family_fact = detail_ops.find_family(canonical)
        if family_fact is None:
            return _unavailable(source_model_id, scope, _NO_FAMILY_REASON)
        ident, class_counts = entity_ops.match_by_family(
            session,
            source_model_id,
            family_fact.property_set,
            family_fact.property_name,
            family_fact.value,
            limit,
        )

    return HighlightGroupResponse(
        source_model_id=source_model_id,
        scope=scope,
        available=True,
        total=ident.exact_total,
        global_ids=[r.global_id for r in ident.rows],
        truncated=ident.truncated,
        class_counts=class_counts,
    )
