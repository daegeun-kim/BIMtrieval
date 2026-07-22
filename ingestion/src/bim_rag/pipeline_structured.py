"""Public structured-import API: ifc_to_db(ifc_path).

Imports one IFC file into the shared PostgreSQL schema (entities + relationships).
No vector generation. Safe to call for multiple IFC files — each is scoped
by its own source_model_id derived from its SHA-256 fingerprint.

Usage:
    from bim_rag.pipeline_structured import ifc_to_db
    result = ifc_to_db(r"path/to/model.ifc")
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from bim_rag.config import get_db_url, sanitize_db_error
from bim_rag.ifc_parser import (
    EXTRACTION_VERSION,
    extract_canonical_json,
    file_fingerprint,
    scan_model,
)
from bim_rag.rel_parser import (
    extract_member_rows,
    extract_relationship_canonical_json,
    resolve_members,
)
from bim_rag.reporting import build_unified_report
from bim_rag.schema.models import (
    Base,
    DbIfcRelationship,
    IfcEntity,
    IfcSourceModel,
    RelationshipMember,
)

_STAGE1_TABLES = [
    IfcSourceModel.__table__,
    IfcEntity.__table__,
    DbIfcRelationship.__table__,
    RelationshipMember.__table__,
]


def _build_manifest_phase(engine: Any, source_model_id: int) -> dict[str, Any]:
    """Generate this model's semantic manifest, never aborting the import.

    A manifest failure is reported (and suppresses "fully query-ready"), but the
    entities and relationships already committed stay valid so the pipeline can
    simply be rerun (§2.1).
    """
    from bim_rag.config import get_model_semantics_root
    from bim_rag.semantic_manifest import generate_manifest

    try:
        with Session(engine) as session:
            return generate_manifest(session, source_model_id, get_model_semantics_root())
    except Exception as exc:  # noqa: BLE001 - reported, never fatal to the import
        return {"validated": False, "error": sanitize_db_error(str(exc))[:300]}


def ifc_to_db(ifc_path: str | Path) -> dict[str, Any]:
    """Import one IFC file (entities + relationships) into the shared PostgreSQL schema.

    Returns a structured report dict. Raises RuntimeError on unrecoverable failures
    with credentials sanitized. Never displays db_url.

    Args:
        ifc_path: Absolute or relative path to the source IFC file.
    """
    ifc_path = Path(ifc_path)
    if not ifc_path.exists():
        raise FileNotFoundError(f"IFC source not found: {ifc_path}")

    print(f"[ifc_to_db] Source: {ifc_path.name}")
    print("[ifc_to_db] Computing fingerprint...")
    fp = file_fingerprint(ifc_path)
    print(f"[ifc_to_db] SHA-256: {fp[:16]}...")

    print("[ifc_to_db] Scanning IFC model...")
    scan = scan_model(ifc_path)
    ifc_model = scan["model"]
    eligible_entities = scan["eligible_entities"]
    relationship_entities = scan["relationship_entities"]

    print(
        f"[ifc_to_db] Schema={scan['ifc_schema']}  "
        f"Total={scan['total_entity_count']}  "
        f"Entities={scan['eligible_entity_count']}  "
        f"Relationships={scan['relationship_count']}"
    )

    print("[ifc_to_db] Connecting to database...")
    try:
        db_url = get_db_url()
        engine = create_engine(db_url, echo=False)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        print("[ifc_to_db] DB connection OK.")
    except Exception as exc:
        raise RuntimeError(sanitize_db_error(str(exc))) from None

    print("[ifc_to_db] Creating/verifying schema tables...")
    Base.metadata.create_all(engine, tables=_STAGE1_TABLES)

    # ------------------------------------------------------------------
    # Phase 1: entities
    # ------------------------------------------------------------------
    entities_new = 0
    entities_updated = 0
    entity_failures = 0
    all_warnings: list[str] = []

    print(f"[ifc_to_db] Importing {len(eligible_entities)} entities...")

    with Session(engine) as session:
        with session.begin():
            source_model = session.query(IfcSourceModel).filter_by(file_fingerprint=fp).first()
            if source_model is None:
                source_model = IfcSourceModel(
                    file_path=str(ifc_path),
                    file_name=ifc_path.name,
                    file_fingerprint=fp,
                    ifc_schema=scan["ifc_schema"],
                    total_entity_count=scan["total_entity_count"],
                    eligible_entity_count=scan["eligible_entity_count"],
                    excluded_relationship_count=scan["relationship_count"],
                    extraction_metadata={
                        "class_counts": scan["class_counts"],
                        "relationship_class_counts": scan.get("relationship_class_counts", {}),
                        "extraction_version": EXTRACTION_VERSION,
                    },
                )
                session.add(source_model)
                session.flush()
                print(f"[ifc_to_db] New source model id={source_model.id}")
            else:
                source_model.total_entity_count = scan["total_entity_count"]
                source_model.eligible_entity_count = scan["eligible_entity_count"]
                source_model.excluded_relationship_count = scan["relationship_count"]
                session.flush()
                print(f"[ifc_to_db] Existing source model id={source_model.id}")

            source_model_id = source_model.id

            for ent in eligible_entities:
                try:
                    canonical, warns = extract_canonical_json(ent, ifc_model)
                    if warns:
                        all_warnings.extend([f"[entity {ent.GlobalId}] {w}" for w in warns])

                    existing = (
                        session.query(IfcEntity)
                        .filter_by(
                            source_model_id=source_model_id,
                            global_id=ent.GlobalId,
                        )
                        .first()
                    )
                    if existing is None:
                        session.add(
                            IfcEntity(
                                source_model_id=source_model_id,
                                global_id=ent.GlobalId,
                                step_id=ent.id(),
                                ifc_class=ent.is_a(),
                                canonical_json=canonical,
                                extraction_warnings=warns or None,
                            )
                        )
                        entities_new += 1
                    else:
                        existing.canonical_json = canonical
                        existing.extraction_warnings = warns or None
                        entities_updated += 1
                except Exception as exc:
                    entity_failures += 1
                    all_warnings.append(f"[entity {getattr(ent, 'GlobalId', '?')}] failed: {exc}")

    print(
        f"[ifc_to_db] Entities new={entities_new}  updated={entities_updated}  "
        f"failures={entity_failures}"
    )

    # ------------------------------------------------------------------
    # Phase 2: build GlobalId → entity_id lookup (same-model only)
    # ------------------------------------------------------------------
    with Session(engine) as session:
        rows = (
            session.query(IfcEntity.global_id, IfcEntity.id)
            .filter_by(source_model_id=source_model_id)
            .all()
        )
    gid_to_entity_id: dict[str, int] = {r[0]: r[1] for r in rows}

    # ------------------------------------------------------------------
    # Phase 3: relationships + members
    # ------------------------------------------------------------------
    rels_new = 0
    rels_updated = 0
    members_total = 0
    members_resolved = 0
    rel_failures = 0

    print(f"[ifc_to_db] Importing {len(relationship_entities)} relationships...")

    BATCH = 200
    for batch_start in range(0, len(relationship_entities), BATCH):
        batch = relationship_entities[batch_start : batch_start + BATCH]
        with Session(engine) as session:
            with session.begin():
                for rel in batch:
                    try:
                        canonical, warns = extract_relationship_canonical_json(rel)
                        if warns:
                            all_warnings.extend([f"[rel {rel.GlobalId}] {w}" for w in warns])

                        existing_rel = (
                            session.query(DbIfcRelationship)
                            .filter_by(
                                source_model_id=source_model_id,
                                global_id=rel.GlobalId,
                            )
                            .first()
                        )

                        name_val = getattr(rel, "Name", None)
                        desc_val = getattr(rel, "Description", None)

                        if existing_rel is None:
                            db_rel = DbIfcRelationship(
                                source_model_id=source_model_id,
                                global_id=rel.GlobalId,
                                step_id=rel.id(),
                                ifc_class=rel.is_a(),
                                name=str(name_val) if name_val else None,
                                description=str(desc_val) if desc_val else None,
                                canonical_json=canonical,
                                extraction_warnings=warns or None,
                            )
                            session.add(db_rel)
                            session.flush()
                            db_rel_id = db_rel.id
                            rels_new += 1
                        else:
                            existing_rel.canonical_json = canonical
                            existing_rel.name = str(name_val) if name_val else None
                            existing_rel.description = str(desc_val) if desc_val else None
                            existing_rel.extraction_warnings = warns or None
                            db_rel_id = existing_rel.id
                            rels_updated += 1
                            # Delete old members for re-insertion
                            session.query(RelationshipMember).filter_by(
                                relationship_id=db_rel_id
                            ).delete()

                        # Insert members
                        raw_members = extract_member_rows(rel)
                        resolved = resolve_members(raw_members, gid_to_entity_id, source_model_id)
                        for m in resolved:
                            session.add(
                                RelationshipMember(
                                    relationship_id=db_rel_id,
                                    source_model_id=source_model_id,
                                    role=m["role"],
                                    member_order=m["member_order"],
                                    endpoint_step_id=m["endpoint_step_id"],
                                    endpoint_ifc_class=m["endpoint_ifc_class"],
                                    endpoint_global_id=m["endpoint_global_id"],
                                    endpoint_name=m["endpoint_name"],
                                    entity_id=m["entity_id"],
                                )
                            )
                            members_total += 1
                            if m["entity_id"] is not None:
                                members_resolved += 1

                    except Exception as exc:
                        rel_failures += 1
                        all_warnings.append(f"[rel {getattr(rel, 'GlobalId', '?')}] failed: {exc}")

        progress = min(batch_start + BATCH, len(relationship_entities))
        print(f"[ifc_to_db] Relationships {progress}/{len(relationship_entities)}...", end="\r")

    print()
    members_unresolved = members_total - members_resolved
    print(f"[ifc_to_db] Rels new={rels_new}  updated={rels_updated}  failures={rel_failures}")
    print(
        f"[ifc_to_db] Members total={members_total}  "
        f"resolved={members_resolved}  unresolved={members_unresolved}"
    )
    print("[ifc_to_db] Structured import complete.")

    # ------------------------------------------------------------------
    # Phase 3b: semantic manifest (task25 §2.1)
    #
    # Runs after entities, relationships, and members are committed — it reads
    # them — and before vector generation, so the artifact describing the model
    # exists by the time anything downstream consumes it.
    # ------------------------------------------------------------------
    print("[ifc_to_db] Building semantic manifest...")
    manifest_stats = _build_manifest_phase(engine, source_model_id)
    if manifest_stats.get("validated"):
        print(
            f"[ifc_to_db] Manifest OK  records={manifest_stats['semantic_record_count']}  "
            f"~{manifest_stats['estimated_tokens']} tokens  "
            f"hash={manifest_stats['content_hash'][:16]}..."
        )
    else:
        # §2.1: a failed manifest must not be reported as query-ready, but the
        # imported data is valid and idempotent ingestion can be rerun to
        # repair the artifact without re-importing anything.
        print(f"[ifc_to_db] Manifest FAILED: {manifest_stats.get('error')}")
        all_warnings.append(f"[manifest] {manifest_stats.get('error')}")

    # ------------------------------------------------------------------
    # Phase 4: Vector generation (pgvector + rag_documents)
    # ------------------------------------------------------------------
    from bim_rag.stage2_embed import run_vector_phase  # lazy: avoids loading torch at import

    print("[ifc_to_db] Starting vector phase (pgvector + rag_documents)...")
    vector_stats = run_vector_phase(engine, source_model_id)
    print("[ifc_to_db] Vector phase complete.")

    return build_unified_report(
        manifest_stats=manifest_stats,
        scan=scan,
        fingerprint=fp,
        source_model_id=source_model_id,
        entities_new=entities_new,
        entities_updated=entities_updated,
        relationships_new=rels_new,
        relationships_updated=rels_updated,
        members_total=members_total,
        members_resolved=members_resolved,
        members_unresolved=members_unresolved,
        entity_failures=entity_failures,
        rel_failures=rel_failures,
        vector_stats=vector_stats,
        warnings=all_warnings,
    )
