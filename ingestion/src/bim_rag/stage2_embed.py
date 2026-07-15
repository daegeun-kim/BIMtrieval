"""Stage 2: Enable pgvector, generate BAAI/bge-m3 embeddings, populate rag_documents.

Entry point: `bim-stage2` — runs complete pipeline via ifc_to_db().
Internal helper: run_vector_phase() — called by pipeline_structured.ifc_to_db().

Do NOT run without Task 02-1 complete for the target source model.

CLOCK_WATCHDOG_TIMEOUT (0x101) recovery mitigations (tasks/task03.md):
  - CUDA batch size is fixed at config.CUDA_BATCH_SIZE (4); 64 is rejected
    by config.validate_batch_size().
  - Every document is tokenized with the real BAAI/bge-m3 tokenizer and
    trimmed to text_limits.MAX_TOKENS before encode().
  - PyTorch/tokenizer thread counts are capped (config.THREAD_LIMIT).
  - Rows whose source_hash/text_hash/template/model/dim already match a
    stored, valid embedding are skipped without re-encoding, so a rerun
    after a crash resumes instead of restarting the whole corpus.
  - Each batch is CUDA-synchronized; a device/CUDA exception stops the run
    immediately with the failing offset — no automatic retry.
"""

from __future__ import annotations

import hashlib
import json
import math
import sys
from typing import Any

import torch
from sentence_transformers import SentenceTransformer
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from bim_rag.config import (
    CUDA_BATCH_SIZE,
    IFC_SOURCE_PATH,
    THREAD_LIMIT,
    sanitize_db_error,
    validate_batch_size,
)
from bim_rag.rel_templates import (
    DOCUMENT_TYPE as REL_DOCUMENT_TYPE,
)
from bim_rag.rel_templates import (
    TEMPLATE_VERSION as REL_TEMPLATE_VERSION,
)
from bim_rag.rel_templates import (
    generate_rel_text,
)
from bim_rag.reporting import print_report
from bim_rag.schema.models import (
    Base,
    DbIfcRelationship,
    IfcEntity,
    IfcSourceModel,
    RagDocument,
)
from bim_rag.templates import (
    DOCUMENT_TYPE as ENTITY_DOCUMENT_TYPE,
)
from bim_rag.templates import (
    TEMPLATE_VERSION as ENTITY_TEMPLATE_VERSION,
)
from bim_rag.templates import (
    generate_text,
)
from bim_rag.text_limits import MAX_TOKENS

EMBEDDING_MODEL_NAME = "BAAI/bge-m3"
EMBEDDING_DIM = 1024

_RAG_TABLES = [RagDocument.__table__]


# ---------------------------------------------------------------------------
# Utilities (kept for import by tests and other callers)
# ---------------------------------------------------------------------------


def _detect_device() -> tuple[torch.device, str]:
    if torch.cuda.is_available():
        dev = torch.device("cuda")
        name = torch.cuda.get_device_name(0)
        return dev, f"CUDA ({name})"
    return torch.device("cpu"), "CPU (CUDA unavailable)"


def _normalize(vec: list[float]) -> list[float]:
    """L2-normalize so cosine similarity = dot product."""
    norm = math.sqrt(sum(x * x for x in vec))
    if norm == 0:
        return vec
    return [x / norm for x in vec]


def _hash_json(obj: Any) -> str:
    """Deterministic sha256 over a JSON-serializable structure (source-content hash)."""
    blob = json.dumps(obj, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def _hash_text(s: str) -> str:
    """Deterministic sha256 over generated document text."""
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _validate_vector(vec: list[float], dim: int) -> bool:
    if len(vec) != dim:
        return False
    return not any(math.isnan(x) or math.isinf(x) for x in vec)


def _check_stage1_precondition(session: Session) -> tuple[int, int]:
    """Raise if Stage 1 tables are absent or empty. Returns (model_id, entity_count)."""
    try:
        model = session.query(IfcSourceModel).first()
    except Exception as exc:
        raise RuntimeError("Stage 1 ifc_source_models table not found. Run Stage 1 first.") from exc

    if model is None:
        raise RuntimeError(
            "Stage 1 has not been run: no rows in ifc_source_models. "
            "Run Stage 1 (bim-stage1) before Stage 2."
        )

    count = session.query(IfcEntity).filter_by(source_model_id=model.id).count()
    if count == 0:
        raise RuntimeError(
            f"Stage 1 source model id={model.id} has no entities. Stage 1 import may have failed."
        )
    return model.id, count


# ---------------------------------------------------------------------------
# Element-vectors migration safety
# ---------------------------------------------------------------------------


def _check_element_vectors_migration(engine: Engine) -> dict[str, Any]:
    """Check the obsolete element_vectors table state. Drop only if empty."""
    insp = inspect(engine)
    exists = insp.has_table("element_vectors")
    if not exists:
        return {"element_vectors_found": False, "element_vectors_empty": True}

    with engine.connect() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM element_vectors")).scalar()

    if count > 0:
        print(
            f"[Stage 2] WARNING: element_vectors table exists with {count} rows. "
            "Will not drop populated table. Continuing with rag_documents."
        )
        return {"element_vectors_found": True, "element_vectors_empty": False}

    # Empty: safe to drop
    with engine.connect() as conn:
        conn.execute(text("DROP TABLE IF EXISTS element_vectors"))
        conn.commit()
    print("[Stage 2] Dropped empty obsolete element_vectors table.")
    return {"element_vectors_found": True, "element_vectors_empty": True}


def _add_rag_document_hash_columns(engine: Engine) -> None:
    """Additive, idempotent migration: hash/token columns for resumable skip logic.

    rag_documents may already exist and hold rows (e.g. from an interrupted
    run), so new columns must be added rather than relying on create_all().
    """
    statements = [
        "ALTER TABLE rag_documents ADD COLUMN IF NOT EXISTS source_hash TEXT",
        "ALTER TABLE rag_documents ADD COLUMN IF NOT EXISTS text_hash TEXT",
        "ALTER TABLE rag_documents ADD COLUMN IF NOT EXISTS original_token_count INTEGER",
        "ALTER TABLE rag_documents ADD COLUMN IF NOT EXISTS encoded_token_count INTEGER",
    ]
    with engine.connect() as conn:
        for stmt in statements:
            conn.execute(text(stmt))
        conn.commit()


# ---------------------------------------------------------------------------
# CUDA-safe batch encoding
# ---------------------------------------------------------------------------


def _encode_batch(
    st_model: SentenceTransformer,
    texts: list[str],
    *,
    source_kind: str,
    batch_offset: int,
) -> Any:
    """Encode one batch with explicit inference-mode + CUDA sync/error boundaries.

    Any device/CUDA exception is re-raised immediately (batch offset + kind
    included) instead of retried — per the 0x101 recovery requirement to
    stop rather than keep hammering an unstable device.
    """
    try:
        with torch.inference_mode():
            embeddings = st_model.encode(
                texts,
                batch_size=len(texts),
                show_progress_bar=False,
                convert_to_numpy=True,
                normalize_embeddings=True,
            )
        if st_model.device.type == "cuda":
            torch.cuda.synchronize()
    except Exception as exc:
        raise RuntimeError(
            f"Device error encoding {source_kind} batch at offset {batch_offset} "
            f"(size={len(texts)}): {exc}. Stopping — no automatic retry after a "
            "device-stability failure."
        ) from exc
    return embeddings


def _upsert_rag_document(
    session: Session,
    *,
    source_model_id: int,
    source_kind: str,
    entity_id: int | None,
    relationship_id: int | None,
    document_type: str,
    template_version: str,
    text_value: str,
    truncated: bool,
    source_hash: str,
    text_hash: str,
    original_token_count: int | None,
    encoded_token_count: int | None,
    vec_list: list[float],
    metadata: dict[str, Any],
) -> bool:
    """Insert-or-update one rag_documents row. Returns True if newly inserted.

    Shared by the production batch loops and smoke_test.py so every write
    path enforces the same uniqueness/upsert semantics.
    """
    existing = (
        session.query(RagDocument)
        .filter_by(
            entity_id=entity_id,
            relationship_id=relationship_id,
            document_type=document_type,
            text_template_version=template_version,
            embedding_model=EMBEDDING_MODEL_NAME,
        )
        .first()
    )

    if existing is None:
        session.add(
            RagDocument(
                source_model_id=source_model_id,
                source_kind=source_kind,
                entity_id=entity_id,
                relationship_id=relationship_id,
                document_type=document_type,
                document_text=text_value,
                text_truncated=truncated,
                text_template_version=template_version,
                embedding_model=EMBEDDING_MODEL_NAME,
                embedding_dim=EMBEDDING_DIM,
                embedding=vec_list,
                source_hash=source_hash,
                text_hash=text_hash,
                original_token_count=original_token_count,
                encoded_token_count=encoded_token_count,
                generation_metadata=metadata,
            )
        )
        return True

    existing.document_text = text_value
    existing.text_truncated = truncated
    existing.embedding = vec_list
    existing.source_hash = source_hash
    existing.text_hash = text_hash
    existing.original_token_count = original_token_count
    existing.encoded_token_count = encoded_token_count
    return False


# ---------------------------------------------------------------------------
# Core vector phase
# ---------------------------------------------------------------------------


def run_vector_phase(engine: Engine, source_model_id: int) -> dict[str, Any]:
    """Generate entity + relationship embeddings into rag_documents.

    Args:
        engine: SQLAlchemy engine with established DB connection.
        source_model_id: ID from ifc_source_models scoping all work.

    Returns:
        Stats dict consumed by build_unified_report().
    """
    warnings: list[str] = []

    # Step 1: Enable pgvector
    print("[Stage 2] Enabling pgvector extension...")
    with engine.connect() as conn:
        try:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            conn.commit()
            print("[Stage 2] pgvector extension enabled.")
        except Exception as exc:
            raise RuntimeError(
                f"Failed to enable pgvector: {sanitize_db_error(str(exc))}. "
                "Check pgvector binaries are installed and the role has CREATE EXTENSION privilege."
            ) from None

    # Step 2: Create rag_documents schema (HNSW index excluded from initial create_all
    #         because pgvector HNSW requires the extension active first)
    print("[Stage 2] Creating rag_documents table...")
    non_hnsw_tables = [RagDocument.__table__]
    Base.metadata.create_all(engine, tables=non_hnsw_tables)

    # Create HNSW index separately (safe if it already exists)
    with engine.connect() as conn:
        try:
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_rag_documents_embedding_cosine "
                    "ON rag_documents USING hnsw (embedding vector_cosine_ops)"
                )
            )
            conn.commit()
        except Exception as exc:
            warnings.append(f"HNSW index creation skipped: {sanitize_db_error(str(exc))}")

    # Step 2b: Additive hash/token columns (idempotent; table may pre-exist with rows)
    print("[Stage 2] Applying additive rag_documents column migration...")
    _add_rag_document_hash_columns(engine)

    # Step 3: Migration safety check
    migration_info = _check_element_vectors_migration(engine)

    # Step 4: Detect device, apply thread limits, load model
    print("[Stage 2] Detecting execution device...")
    device, device_str = _detect_device()
    print(f"[Stage 2] Execution device: {device_str}")

    torch.set_num_threads(THREAD_LIMIT)
    batch_size = validate_batch_size(CUDA_BATCH_SIZE)
    print(
        f"[Stage 2] CUDA batch size: {batch_size}  thread limit: {THREAD_LIMIT}  "
        f"token limit: {MAX_TOKENS}"
    )

    print(f"[Stage 2] Loading embedding model: {EMBEDDING_MODEL_NAME} ...")
    st_model = SentenceTransformer(EMBEDDING_MODEL_NAME, device=str(device))
    tokenizer = st_model.tokenizer
    print("[Stage 2] Model loaded.")

    last_attempted_batch: dict[str, Any] = {}

    # Step 5: Entity documents
    entity_docs_new = 0
    entity_docs_updated = 0
    entity_docs_skipped_valid = 0
    entity_truncated = 0
    entity_embed_failures = 0

    with Session(engine) as session:
        entities = (
            session.query(IfcEntity)
            .filter_by(source_model_id=source_model_id)
            .order_by(IfcEntity.id)
            .all()
        )
        existing_entity_hashes = {
            r.entity_id: (r.source_hash, r.text_hash, r.embedding_dim, r.embedding is not None)
            for r in session.query(
                RagDocument.entity_id,
                RagDocument.source_hash,
                RagDocument.text_hash,
                RagDocument.embedding_dim,
                RagDocument.embedding,
            ).filter_by(
                source_model_id=source_model_id,
                source_kind="entity",
                document_type=ENTITY_DOCUMENT_TYPE,
                text_template_version=ENTITY_TEMPLATE_VERSION,
                embedding_model=EMBEDDING_MODEL_NAME,
            )
        }

    total_entities = len(entities)
    print(f"[Stage 2] Preparing entity_description docs for {total_entities} entities...")

    entity_to_process: list[dict[str, Any]] = []
    for entity in entities:
        try:
            t, trunc, orig_tok, enc_tok = generate_text(entity.canonical_json, tokenizer=tokenizer)
        except Exception as exc:
            entity_embed_failures += 1
            warnings.append(f"[entity {entity.global_id}] text gen failed: {exc}")
            continue

        source_hash = _hash_json(entity.canonical_json)
        text_hash = _hash_text(t)
        prior = existing_entity_hashes.get(entity.id)
        if (
            prior is not None
            and prior[0] == source_hash
            and prior[1] == text_hash
            and prior[2] == EMBEDDING_DIM
            and prior[3]
        ):
            entity_docs_skipped_valid += 1
            continue

        if trunc:
            entity_truncated += 1
            warnings.append(f"[entity {entity.global_id}] text truncated")

        entity_to_process.append(
            {
                "entity": entity,
                "text": t,
                "truncated": trunc,
                "source_hash": source_hash,
                "text_hash": text_hash,
                "original_token_count": orig_tok,
                "encoded_token_count": enc_tok,
            }
        )

    print(
        f"[Stage 2] Entities to (re)generate: {len(entity_to_process)}  "
        f"skipped (valid): {entity_docs_skipped_valid}"
    )

    for batch_start in range(0, len(entity_to_process), batch_size):
        batch = entity_to_process[batch_start : batch_start + batch_size]
        texts = [b["text"] for b in batch]
        last_attempted_batch = {"source_kind": "entity", "offset": batch_start, "size": len(batch)}

        raw_embeddings = _encode_batch(
            st_model, texts, source_kind="entity", batch_offset=batch_start
        )

        with Session(engine) as session:
            with session.begin():
                for item, raw_vec in zip(batch, raw_embeddings):
                    entity = item["entity"]
                    vec_list = raw_vec.tolist()
                    if not _validate_vector(vec_list, EMBEDDING_DIM):
                        entity_embed_failures += 1
                        warnings.append(
                            f"[entity {entity.global_id}] invalid embedding (dim/NaN/Inf)"
                        )
                        continue

                    inserted = _upsert_rag_document(
                        session,
                        source_model_id=source_model_id,
                        source_kind="entity",
                        entity_id=entity.id,
                        relationship_id=None,
                        document_type=ENTITY_DOCUMENT_TYPE,
                        template_version=ENTITY_TEMPLATE_VERSION,
                        text_value=item["text"],
                        truncated=item["truncated"],
                        source_hash=item["source_hash"],
                        text_hash=item["text_hash"],
                        original_token_count=item["original_token_count"],
                        encoded_token_count=item["encoded_token_count"],
                        vec_list=vec_list,
                        metadata={"ifc_class": entity.ifc_class, "global_id": entity.global_id},
                    )
                    if inserted:
                        entity_docs_new += 1
                    else:
                        entity_docs_updated += 1

        progress = min(batch_start + batch_size, len(entity_to_process))
        print(
            f"[Stage 2] Entity docs {progress}/{len(entity_to_process)} "
            f"(of {total_entities} total, {entity_docs_skipped_valid} skipped)...",
            end="\r",
        )

    print(
        f"\n[Stage 2] Entity docs: new={entity_docs_new} updated={entity_docs_updated} "
        f"skipped_valid={entity_docs_skipped_valid} truncated={entity_truncated} "
        f"failures={entity_embed_failures}"
    )

    # Step 6: Relationship documents
    rel_docs_new = 0
    rel_docs_updated = 0
    rel_docs_skipped_valid = 0
    rel_truncated = 0
    rel_embed_failures = 0

    with Session(engine) as session:
        relationships = (
            session.query(DbIfcRelationship)
            .filter_by(source_model_id=source_model_id)
            .order_by(DbIfcRelationship.id)
            .all()
        )
        # Build member lookup: relationship_id → sorted member dicts
        from bim_rag.schema.models import RelationshipMember  # local import avoids circular

        all_members = (
            session.query(RelationshipMember)
            .filter_by(source_model_id=source_model_id)
            .order_by(
                RelationshipMember.relationship_id,
                RelationshipMember.role,
                RelationshipMember.member_order,
            )
            .all()
        )
        existing_rel_hashes = {
            r.relationship_id: (
                r.source_hash,
                r.text_hash,
                r.embedding_dim,
                r.embedding is not None,
            )
            for r in session.query(
                RagDocument.relationship_id,
                RagDocument.source_hash,
                RagDocument.text_hash,
                RagDocument.embedding_dim,
                RagDocument.embedding,
            ).filter_by(
                source_model_id=source_model_id,
                source_kind="relationship",
                document_type=REL_DOCUMENT_TYPE,
                text_template_version=REL_TEMPLATE_VERSION,
                embedding_model=EMBEDDING_MODEL_NAME,
            )
        }

    total_rels = len(relationships)
    print(f"[Stage 2] Preparing relationship_description docs for {total_rels} relationships...")

    # Group members by relationship_id
    members_by_rel: dict[int, list[dict[str, Any]]] = {}
    for m in all_members:
        members_by_rel.setdefault(m.relationship_id, []).append(
            {
                "role": m.role,
                "member_order": m.member_order,
                "endpoint_step_id": m.endpoint_step_id,
                "endpoint_ifc_class": m.endpoint_ifc_class,
                "endpoint_global_id": m.endpoint_global_id,
                "endpoint_name": m.endpoint_name,
                "entity_id": m.entity_id,
            }
        )

    rel_to_process: list[dict[str, Any]] = []
    for rel in relationships:
        mems = members_by_rel.get(rel.id, [])
        try:
            t, trunc, orig_tok, enc_tok = generate_rel_text(
                rel.canonical_json, members=mems, tokenizer=tokenizer
            )
        except Exception as exc:
            rel_embed_failures += 1
            warnings.append(f"[rel {rel.global_id}] text gen failed: {exc}")
            continue

        source_hash = _hash_json({"canonical": rel.canonical_json, "members": mems})
        text_hash = _hash_text(t)
        prior = existing_rel_hashes.get(rel.id)
        if (
            prior is not None
            and prior[0] == source_hash
            and prior[1] == text_hash
            and prior[2] == EMBEDDING_DIM
            and prior[3]
        ):
            rel_docs_skipped_valid += 1
            continue

        if trunc:
            rel_truncated += 1
            warnings.append(f"[rel {rel.global_id}] text truncated")

        rel_to_process.append(
            {
                "rel": rel,
                "text": t,
                "truncated": trunc,
                "source_hash": source_hash,
                "text_hash": text_hash,
                "original_token_count": orig_tok,
                "encoded_token_count": enc_tok,
            }
        )

    print(
        f"[Stage 2] Relationships to (re)generate: {len(rel_to_process)}  "
        f"skipped (valid): {rel_docs_skipped_valid}"
    )

    for batch_start in range(0, len(rel_to_process), batch_size):
        batch = rel_to_process[batch_start : batch_start + batch_size]
        texts_r = [b["text"] for b in batch]
        last_attempted_batch = {
            "source_kind": "relationship",
            "offset": batch_start,
            "size": len(batch),
        }

        raw_embeddings_r = _encode_batch(
            st_model, texts_r, source_kind="relationship", batch_offset=batch_start
        )

        with Session(engine) as session:
            with session.begin():
                for item, raw_vec in zip(batch, raw_embeddings_r):
                    rel = item["rel"]
                    vec_list = raw_vec.tolist()
                    if not _validate_vector(vec_list, EMBEDDING_DIM):
                        rel_embed_failures += 1
                        warnings.append(f"[rel {rel.global_id}] invalid embedding (dim/NaN/Inf)")
                        continue

                    inserted = _upsert_rag_document(
                        session,
                        source_model_id=source_model_id,
                        source_kind="relationship",
                        entity_id=None,
                        relationship_id=rel.id,
                        document_type=REL_DOCUMENT_TYPE,
                        template_version=REL_TEMPLATE_VERSION,
                        text_value=item["text"],
                        truncated=item["truncated"],
                        source_hash=item["source_hash"],
                        text_hash=item["text_hash"],
                        original_token_count=item["original_token_count"],
                        encoded_token_count=item["encoded_token_count"],
                        vec_list=vec_list,
                        metadata={"ifc_class": rel.ifc_class},
                    )
                    if inserted:
                        rel_docs_new += 1
                    else:
                        rel_docs_updated += 1

        progress = min(batch_start + batch_size, len(rel_to_process))
        print(
            f"[Stage 2] Rel docs {progress}/{len(rel_to_process)} "
            f"(of {total_rels} total, {rel_docs_skipped_valid} skipped)...",
            end="\r",
        )

    print(
        f"\n[Stage 2] Rel docs: new={rel_docs_new} updated={rel_docs_updated} "
        f"skipped_valid={rel_docs_skipped_valid} truncated={rel_truncated} "
        f"failures={rel_embed_failures}"
    )

    total_rag = (
        entity_docs_new
        + entity_docs_updated
        + entity_docs_skipped_valid
        + rel_docs_new
        + rel_docs_updated
        + rel_docs_skipped_valid
    )

    return {
        "pgvector_enabled": True,
        **migration_info,
        "execution_device": device_str,
        "embedding_model": EMBEDDING_MODEL_NAME,
        "template_version": ENTITY_TEMPLATE_VERSION,
        "cuda_batch_size": batch_size,
        "thread_limit": THREAD_LIMIT,
        "token_limit": MAX_TOKENS,
        "entity_docs_new": entity_docs_new,
        "entity_docs_updated": entity_docs_updated,
        "entity_docs_skipped_valid": entity_docs_skipped_valid,
        "entity_docs_truncated": entity_truncated,
        "entity_embed_failures": entity_embed_failures,
        "rel_docs_new": rel_docs_new,
        "rel_docs_updated": rel_docs_updated,
        "rel_docs_skipped_valid": rel_docs_skipped_valid,
        "rel_docs_truncated": rel_truncated,
        "rel_embed_failures": rel_embed_failures,
        "total_rag_docs": total_rag,
        "last_attempted_batch": last_attempted_batch,
        "warning_count": len(warnings),
        "warnings_sample": warnings[:15],
    }


# ---------------------------------------------------------------------------
# Legacy standalone CLI (delegates to full ifc_to_db pipeline)
# ---------------------------------------------------------------------------


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Stage 2: Generate embeddings into rag_documents (full pipeline)."
    )
    parser.add_argument(
        "--ifc-path",
        default=str(IFC_SOURCE_PATH),
        help="Path to the IFC file (default: project source IFC).",
    )
    args = parser.parse_args()

    # Full pipeline: ifc_to_db runs Stage 1 (idempotent) + Stage 2
    from bim_rag.pipeline_structured import ifc_to_db

    try:
        report = ifc_to_db(args.ifc_path)
        print_report(report, label="Full Pipeline Report (Stage 2 CLI)")
    except Exception as exc:
        print(f"[Stage 2] FAILED: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
