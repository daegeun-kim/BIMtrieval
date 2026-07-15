"""Staged CUDA smoke tests for the Task 03 vectorization recovery run.

Run ONE stage at a time (separate process invocations) and inspect the
result before advancing, per tasks/task03.md: "stop between stages to
inspect the result... If Windows crashes... report the exact last
completed stage."

    python -m bim_rag.smoke_test --stage 1
    python -m bim_rag.smoke_test --stage 2
    python -m bim_rag.smoke_test --stage 3
    python -m bim_rag.smoke_test --stage 4
    python -m bim_rag.smoke_test --stage 5
    python -m bim_rag.smoke_test --stage 6 [--sample-size 32]

Stage 6 also validates and stores its sample into rag_documents (stage 7
in the task's numbering) via the same upsert path as the production run,
so smoke-test work becomes real progress rather than being discarded.

Each stage prints with flush=True and exits non-zero on failure so the
last completed stage is visible even if the process is killed abruptly.
"""

from __future__ import annotations

import argparse
import sys
import time
from typing import Any

import torch
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from bim_rag.config import (
    CUDA_BATCH_SIZE,
    THREAD_LIMIT,
    get_db_url,
    sanitize_db_error,
    validate_batch_size,
)
from bim_rag.rel_templates import (
    DOCUMENT_TYPE as REL_DOCUMENT_TYPE,
)
from bim_rag.rel_templates import (
    TEMPLATE_VERSION as REL_TEMPLATE_VERSION,
)
from bim_rag.rel_templates import generate_rel_text
from bim_rag.schema.models import DbIfcRelationship, IfcEntity, IfcSourceModel, RelationshipMember
from bim_rag.stage2_embed import (
    EMBEDDING_DIM,
    EMBEDDING_MODEL_NAME,
    _add_rag_document_hash_columns,
    _detect_device,
    _encode_batch,
    _hash_json,
    _hash_text,
    _upsert_rag_document,
    _validate_vector,
)
from bim_rag.templates import (
    DOCUMENT_TYPE as ENTITY_DOCUMENT_TYPE,
)
from bim_rag.templates import (
    TEMPLATE_VERSION as ENTITY_TEMPLATE_VERSION,
)
from bim_rag.templates import generate_text
from bim_rag.text_limits import MAX_TOKENS


def _p(msg: str) -> None:
    print(msg, flush=True)


def _resolve_source_model_id(session: Session, explicit: int | None) -> int:
    if explicit is not None:
        return explicit
    models = session.query(IfcSourceModel.id).all()
    if len(models) != 1:
        raise RuntimeError(
            f"Expected exactly one ifc_source_models row, found {len(models)}. "
            "Pass --source-model-id explicitly."
        )
    return models[0][0]


def _load_model() -> tuple[Any, torch.device, str]:
    from sentence_transformers import SentenceTransformer

    device, device_str = _detect_device()
    torch.set_num_threads(THREAD_LIMIT)
    _p(f"[Smoke] Execution device: {device_str}")
    _p(f"[Smoke] Thread limit: {THREAD_LIMIT}  Token limit: {MAX_TOKENS}")
    _p(f"[Smoke] Loading {EMBEDDING_MODEL_NAME} ...")
    t0 = time.time()
    model = SentenceTransformer(EMBEDDING_MODEL_NAME, device=str(device))
    _p(f"[Smoke] Model loaded in {time.time() - t0:.1f}s.")
    return model, device, device_str


def _validate_or_raise(stage: str, vec: list[float]) -> None:
    if not _validate_vector(vec, EMBEDDING_DIM):
        raise RuntimeError(f"[Smoke][{stage}] FAIL: invalid embedding (dim={len(vec)})")
    _p(f"[Smoke][{stage}] dim={len(vec)} nan/inf=False PASS")


# ---------------------------------------------------------------------------
# Stages
# ---------------------------------------------------------------------------


def stage1_load_model() -> None:
    _p("[Smoke][Stage 1] Load BAAI/bge-m3 on CUDA, no encoding.")
    _, device, device_str = _load_model()
    if device.type != "cuda":
        _p(f"[Smoke][Stage 1] WARNING: not running on CUDA (device={device_str}).")
    _p("[Smoke][Stage 1] PASS")


def stage2_encode_synthetic() -> None:
    _p("[Smoke][Stage 2] Encode one short synthetic document.")
    model, _, _ = _load_model()
    embeddings = _encode_batch(
        model,
        ["This is a short synthetic smoke-test sentence for BAAI/bge-m3."],
        source_kind="synthetic",
        batch_offset=0,
    )
    _validate_or_raise("Stage 2", embeddings[0].tolist())
    _p("[Smoke][Stage 2] PASS")


def stage3_encode_real_entity(source_model_id: int | None) -> None:
    _p("[Smoke][Stage 3] Encode one real entity document.")
    model, _, _ = _load_model()
    engine = create_engine(get_db_url(), echo=False)
    with Session(engine) as session:
        smid = _resolve_source_model_id(session, source_model_id)
        entity = (
            session.query(IfcEntity).filter_by(source_model_id=smid).order_by(IfcEntity.id).first()
        )
        if entity is None:
            raise RuntimeError("No entities found for the resolved source model.")
        text, truncated, orig_tok, enc_tok = generate_text(
            entity.canonical_json, tokenizer=model.tokenizer
        )
    _p(
        f"[Smoke][Stage 3] entity global_id={entity.global_id} "
        f"tokens={enc_tok}/{orig_tok} truncated={truncated}"
    )
    embeddings = _encode_batch(model, [text], source_kind="entity", batch_offset=0)
    _validate_or_raise("Stage 3", embeddings[0].tolist())
    _p("[Smoke][Stage 3] PASS")


def stage4_encode_real_relationship(source_model_id: int | None) -> None:
    _p("[Smoke][Stage 4] Encode one real relationship document.")
    model, _, _ = _load_model()
    engine = create_engine(get_db_url(), echo=False)
    with Session(engine) as session:
        smid = _resolve_source_model_id(session, source_model_id)
        rel = (
            session.query(DbIfcRelationship)
            .filter_by(source_model_id=smid)
            .order_by(DbIfcRelationship.id)
            .first()
        )
        if rel is None:
            raise RuntimeError("No relationships found for the resolved source model.")
        members = [
            {
                "role": m.role,
                "member_order": m.member_order,
                "endpoint_step_id": m.endpoint_step_id,
                "endpoint_ifc_class": m.endpoint_ifc_class,
                "endpoint_global_id": m.endpoint_global_id,
                "endpoint_name": m.endpoint_name,
                "entity_id": m.entity_id,
            }
            for m in session.query(RelationshipMember).filter_by(relationship_id=rel.id).all()
        ]
        text, truncated, orig_tok, enc_tok = generate_rel_text(
            rel.canonical_json, members=members, tokenizer=model.tokenizer
        )
    _p(
        f"[Smoke][Stage 4] rel global_id={rel.global_id} "
        f"tokens={enc_tok}/{orig_tok} truncated={truncated}"
    )
    embeddings = _encode_batch(model, [text], source_kind="relationship", batch_offset=0)
    _validate_or_raise("Stage 4", embeddings[0].tolist())
    _p("[Smoke][Stage 4] PASS")


def _fetch_mixed_sample(
    session: Session, source_model_id: int, n_entities: int, n_rels: int
) -> tuple[list[IfcEntity], list[tuple[DbIfcRelationship, list[dict]]]]:
    entities = (
        session.query(IfcEntity)
        .filter_by(source_model_id=source_model_id)
        .order_by(IfcEntity.id)
        .limit(n_entities)
        .all()
    )
    rels = (
        session.query(DbIfcRelationship)
        .filter_by(source_model_id=source_model_id)
        .order_by(DbIfcRelationship.id)
        .limit(n_rels)
        .all()
    )
    rels_with_members = []
    for rel in rels:
        members = [
            {
                "role": m.role,
                "member_order": m.member_order,
                "endpoint_step_id": m.endpoint_step_id,
                "endpoint_ifc_class": m.endpoint_ifc_class,
                "endpoint_global_id": m.endpoint_global_id,
                "endpoint_name": m.endpoint_name,
                "entity_id": m.entity_id,
            }
            for m in session.query(RelationshipMember).filter_by(relationship_id=rel.id).all()
        ]
        rels_with_members.append((rel, members))
    return entities, rels_with_members


def stage5_encode_mixed_batch(source_model_id: int | None) -> None:
    _p("[Smoke][Stage 5] Encode a fixed batch of 4 mixed real documents.")
    model, _, _ = _load_model()
    engine = create_engine(get_db_url(), echo=False)
    with Session(engine) as session:
        smid = _resolve_source_model_id(session, source_model_id)
        entities, rels_with_members = _fetch_mixed_sample(session, smid, 2, 2)
        if len(entities) < 2 or len(rels_with_members) < 2:
            raise RuntimeError("Not enough source rows for a mixed batch of 4.")
        texts = []
        for e in entities:
            t, _, _, _ = generate_text(e.canonical_json, tokenizer=model.tokenizer)
            texts.append(t)
        for rel, members in rels_with_members:
            t, _, _, _ = generate_rel_text(
                rel.canonical_json, members=members, tokenizer=model.tokenizer
            )
            texts.append(t)

    validate_batch_size(len(texts))
    embeddings = _encode_batch(model, texts, source_kind="mixed", batch_offset=0)
    for i, emb in enumerate(embeddings):
        _validate_or_raise(f"Stage 5 item {i}", emb.tolist())
    _p("[Smoke][Stage 5] PASS")


def stage6_encode_and_store_sample(source_model_id: int | None, sample_size: int) -> None:
    _p(f"[Smoke][Stage 6] Encode + store up to {sample_size} real documents, batches of 4.")
    if sample_size > 32:
        raise ValueError("Stage 6 sample size must not exceed 32 (task03.md requirement).")

    model, _, _ = _load_model()
    batch_size = validate_batch_size(CUDA_BATCH_SIZE)
    engine = create_engine(get_db_url(), echo=False)

    with Session(engine) as session:
        _add_rag_document_hash_columns(engine)
        smid = _resolve_source_model_id(session, source_model_id)
        n_each = sample_size // 2
        entities, rels_with_members = _fetch_mixed_sample(
            session, smid, n_each, sample_size - n_each
        )

        items: list[dict[str, Any]] = []
        for e in entities:
            t, trunc, orig_tok, enc_tok = generate_text(e.canonical_json, tokenizer=model.tokenizer)
            items.append(
                {
                    "kind": "entity",
                    "entity_id": e.id,
                    "relationship_id": None,
                    "document_type": ENTITY_DOCUMENT_TYPE,
                    "template_version": ENTITY_TEMPLATE_VERSION,
                    "text": t,
                    "truncated": trunc,
                    "source_hash": _hash_json(e.canonical_json),
                    "text_hash": _hash_text(t),
                    "original_token_count": orig_tok,
                    "encoded_token_count": enc_tok,
                    "metadata": {"ifc_class": e.ifc_class, "global_id": e.global_id},
                }
            )
        for rel, members in rels_with_members:
            t, trunc, orig_tok, enc_tok = generate_rel_text(
                rel.canonical_json, members=members, tokenizer=model.tokenizer
            )
            items.append(
                {
                    "kind": "relationship",
                    "entity_id": None,
                    "relationship_id": rel.id,
                    "document_type": REL_DOCUMENT_TYPE,
                    "template_version": REL_TEMPLATE_VERSION,
                    "text": t,
                    "truncated": trunc,
                    "source_hash": _hash_json(
                        {"canonical": rel.canonical_json, "members": members}
                    ),
                    "text_hash": _hash_text(t),
                    "original_token_count": orig_tok,
                    "encoded_token_count": enc_tok,
                    "metadata": {"ifc_class": rel.ifc_class},
                }
            )

    _p(
        f"[Smoke][Stage 6] Prepared {len(items)} documents ({len(entities)} entity, "
        f"{len(rels_with_members)} relationship)."
    )

    new_count = 0
    updated_count = 0
    for batch_start in range(0, len(items), batch_size):
        batch = items[batch_start : batch_start + batch_size]
        texts = [b["text"] for b in batch]
        embeddings = _encode_batch(
            model, texts, source_kind="stage6-sample", batch_offset=batch_start
        )

        with Session(engine) as session:
            with session.begin():
                for item, emb in zip(batch, embeddings):
                    vec_list = emb.tolist()
                    if not _validate_vector(vec_list, EMBEDDING_DIM):
                        raise RuntimeError(
                            f"[Smoke][Stage 6] invalid embedding at offset {batch_start}"
                        )
                    inserted = _upsert_rag_document(
                        session,
                        source_model_id=smid,
                        source_kind=item["kind"],
                        entity_id=item["entity_id"],
                        relationship_id=item["relationship_id"],
                        document_type=item["document_type"],
                        template_version=item["template_version"],
                        text_value=item["text"],
                        truncated=item["truncated"],
                        source_hash=item["source_hash"],
                        text_hash=item["text_hash"],
                        original_token_count=item["original_token_count"],
                        encoded_token_count=item["encoded_token_count"],
                        vec_list=vec_list,
                        metadata=item["metadata"],
                    )
                    if inserted:
                        new_count += 1
                    else:
                        updated_count += 1
        _p(f"[Smoke][Stage 6] batch {batch_start}-{batch_start + len(batch)} stored.")

    _p(f"[Smoke][Stage 6] Stored: new={new_count} updated={updated_count}")
    _p("[Smoke][Stage 6] PASS (stage 7 validate+store folded in)")


_STAGES = {
    1: lambda args: stage1_load_model(),
    2: lambda args: stage2_encode_synthetic(),
    3: lambda args: stage3_encode_real_entity(args.source_model_id),
    4: lambda args: stage4_encode_real_relationship(args.source_model_id),
    5: lambda args: stage5_encode_mixed_batch(args.source_model_id),
    6: lambda args: stage6_encode_and_store_sample(args.source_model_id, args.sample_size),
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one staged CUDA smoke test (task03.md).")
    parser.add_argument("--stage", type=int, required=True, choices=sorted(_STAGES.keys()))
    parser.add_argument("--source-model-id", type=int, default=None)
    parser.add_argument("--sample-size", type=int, default=32)
    args = parser.parse_args()

    try:
        _STAGES[args.stage](args)
    except Exception as exc:
        print(
            f"[Smoke][Stage {args.stage}] FAIL: {sanitize_db_error(str(exc))}",
            file=sys.stderr,
            flush=True,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
