"""Backfill v002 semantic manifests for every imported model.

Run:
    python -m bim_rag.db_admin.backfill_manifests_v002
"""

from __future__ import annotations

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from bim_rag.config import get_db_url, get_model_semantics_root, sanitize_db_error
from bim_rag.semantic_manifest import generate_manifest_v002


def main() -> None:
    try:
        engine = create_engine(get_db_url())
        root = get_model_semantics_root()
        with engine.connect() as conn:
            model_ids = [
                r[0] for r in conn.execute(text("SELECT id FROM ifc_source_models ORDER BY id"))
            ]
        for sid in model_ids:
            with Session(engine) as session:
                stats = generate_manifest_v002(session, sid, root)
            print(
                f"[manifest_v002] model {sid}: {stats['capability_count']} capabilities, "
                f"{stats['traversal_count']} traversals, {stats['floor_band_count']} bands, "
                f"{stats['bytes']} bytes (~{stats['estimated_tokens']} tokens) "
                f"hash={stats['content_hash'][:12]}"
            )
    except Exception as exc:  # noqa: BLE001 - CLI surface
        raise SystemExit(sanitize_db_error(str(exc))) from None


if __name__ == "__main__":
    main()
