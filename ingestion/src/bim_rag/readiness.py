"""Model readiness verification and minimal catalog setup (task26 §4.6).

A completed model must verify:

1. canonical entities and relationships;
2. normalized spatial memberships;
3. semantic manifest v002;
4. RAG documents and embeddings;
5. viewer artifact;
6. catalog metadata required for the model to appear in the app.

`verify_model_readiness` measures each check honestly — a model missing its
viewer artifact or catalog entry is REPORTED incomplete, never called
query-ready with the gap omitted. `ensure_catalog_entry` creates the minimal
deterministic entry from source metadata when one is missing.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from bim_rag.config import get_model_semantics_root


def _model_assets_root() -> Path:
    configured = os.environ.get("model_assets_root") or os.environ.get("MODEL_ASSETS_ROOT")
    if configured:
        return Path(configured)
    return get_model_semantics_root().parent / "model_assets"


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.casefold()).strip("_") or "model"


def ensure_catalog_entry(session: Session, source_model_id: int) -> dict[str, Any]:
    """Create the minimal deterministic catalog entry when missing (§4.6).

    Everything is derived from `ifc_source_models` — no invented metadata.
    Existing entries are never modified.
    """
    existing = session.execute(
        text(
            "SELECT id FROM source_model_catalog_entries WHERE source_model_id = :sid"
        ),
        {"sid": source_model_id},
    ).fetchone()
    if existing is not None:
        return {"created": False, "catalog_entry_id": existing[0]}

    source = session.execute(
        text("SELECT file_name, file_path FROM ifc_source_models WHERE id = :sid"),
        {"sid": source_model_id},
    ).fetchone()
    if source is None:
        raise ValueError(f"source model {source_model_id} does not exist")
    stem = Path(source[0]).stem
    family_key = _slug(stem)

    family = session.execute(
        text("SELECT id FROM model_families WHERE family_key = :key"), {"key": family_key}
    ).fetchone()
    if family is None:
        family_id = session.execute(
            text(
                "INSERT INTO model_families (family_key, display_name) "
                "VALUES (:key, :name) RETURNING id"
            ),
            {"key": family_key, "name": stem},
        ).scalar_one()
    else:
        family_id = family[0]

    entry_id = session.execute(
        text(
            "INSERT INTO source_model_catalog_entries "
            "(source_model_id, model_family_id, display_name, version_label, version_order, "
            " is_current, status, viewer_source_location, field_provenance) "
            "VALUES (:sid, :fid, :name, 'v1', 1, true, 'available', :src, "
            " CAST(:prov AS jsonb)) RETURNING id"
        ),
        {
            "sid": source_model_id,
            "fid": family_id,
            "name": stem,
            "src": source[1],
            "prov": (
                '{"status": "derived_exact", "is_current": "derived_exact", '
                '"display_name": "derived_exact", "version_label": "derived_exact", '
                '"version_order": "derived_exact", "viewer_source_location": "ifc_extracted"}'
            ),
        },
    ).scalar_one()
    return {"created": True, "catalog_entry_id": entry_id}


def verify_model_readiness(session: Session, source_model_id: int) -> dict[str, Any]:
    """Measure the six readiness facts for one model. Never raises for a gap."""
    from bim_rag.semantic_manifest.writer_v002 import manifest_path_v002, read_manifest_v002

    checks: dict[str, Any] = {}

    row = session.execute(
        text("SELECT file_fingerprint FROM ifc_source_models WHERE id = :sid"),
        {"sid": source_model_id},
    ).fetchone()
    fingerprint = row[0] if row else None

    entity_count = session.execute(
        text("SELECT count(*) FROM ifc_entities WHERE source_model_id = :sid"),
        {"sid": source_model_id},
    ).scalar()
    relationship_count = session.execute(
        text("SELECT count(*) FROM ifc_relationships WHERE source_model_id = :sid"),
        {"sid": source_model_id},
    ).scalar()
    checks["canonical_facts"] = {
        "ok": bool(entity_count),
        "entities": int(entity_count or 0),
        "relationships": int(relationship_count or 0),
    }

    membership_count = session.execute(
        text(
            "SELECT count(*) FROM entity_spatial_memberships WHERE source_model_id = :sid"
        ),
        {"sid": source_model_id},
    ).scalar()
    storey_count = session.execute(
        text(
            "SELECT count(*) FROM ifc_entities WHERE source_model_id = :sid "
            "AND ifc_class = 'IfcBuildingStorey'"
        ),
        {"sid": source_model_id},
    ).scalar()
    checks["spatial_memberships"] = {
        # A model with no storeys legitimately has no memberships.
        "ok": bool(membership_count) or not storey_count,
        "rows": int(membership_count or 0),
        "storeys": int(storey_count or 0),
    }

    manifest_ok = False
    manifest_info: dict[str, Any] = {}
    if fingerprint:
        path = manifest_path_v002(get_model_semantics_root(), source_model_id, fingerprint)
        if path.is_file():
            try:
                document = read_manifest_v002(path)
                manifest_ok = True
                manifest_info = {
                    "capabilities": len(document["content"]["capabilities"]),
                    "content_hash": document["identity"]["content_hash"][:16],
                }
            except Exception as exc:  # noqa: BLE001 - reported, not raised
                manifest_info = {"error": str(exc)[:200]}
    checks["semantic_manifest_v002"] = {"ok": manifest_ok, **manifest_info}

    rag = session.execute(
        text(
            "SELECT count(*), count(*) FILTER (WHERE embedding IS NOT NULL) "
            "FROM rag_documents WHERE source_model_id = :sid"
        ),
        {"sid": source_model_id},
    ).fetchone()
    checks["rag_documents"] = {
        "ok": bool(rag and rag[0] and rag[0] == rag[1]),
        "documents": int(rag[0] or 0) if rag else 0,
        "embedded": int(rag[1] or 0) if rag else 0,
    }

    asset_ok = False
    if fingerprint:
        asset = _model_assets_root() / str(source_model_id) / f"{fingerprint}.frag"
        asset_ok = asset.is_file()
    checks["viewer_artifact"] = {"ok": asset_ok}

    catalog = session.execute(
        text(
            "SELECT status FROM source_model_catalog_entries WHERE source_model_id = :sid"
        ),
        {"sid": source_model_id},
    ).fetchone()
    checks["catalog_entry"] = {
        "ok": bool(catalog and catalog[0] == "available"),
        "status": catalog[0] if catalog else None,
    }

    return {
        "source_model_id": source_model_id,
        "ready": all(c["ok"] for c in checks.values()),
        "checks": checks,
    }
