"""Narrow, deterministic, read-only viewer contracts (spec_v006 §10; Task 10).

Three capabilities the frontend needs, none of which invoke an LLM, parse IFC,
convert geometry, write the database, or expose a filesystem path:

    GET  /api/models                              -> bounded selector list
    GET  /api/models/{id}/viewer-asset            -> stream prepared artifact
    POST /api/models/{id}/entities/resolve        -> GlobalId -> compact identity

All database access is read-only through the backend's configured role and is
injected via `get_db` so it can be overridden in offline tests.
"""

from __future__ import annotations

from typing import Iterator

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.schemas.models import (
    ModelListItem,
    ModelListResponse,
    ResolvedEntity,
    ResolveEntitiesRequest,
    ResolveEntitiesResponse,
)
from app.config.settings import get_settings
from app.db.session import session_scope
from app.query.selection import normalize_global_ids
from app.query.sql import catalog as catalog_ops
from app.query.sql import entities as entity_ops
from app.shared.types import ViewerAssetStatus
from app.viewer.assets import (
    VIEWER_ASSET_SUFFIX,
    compute_asset_status,
    expected_asset_path,
    is_contained,
)

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
