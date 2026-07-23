"""Create missing catalog entries and report readiness for every model.

Run:
    python -m bim_rag.db_admin.backfill_catalog_and_readiness
"""

from __future__ import annotations

import json

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from bim_rag.config import get_db_url, sanitize_db_error
from bim_rag.readiness import ensure_catalog_entry, verify_model_readiness


def main() -> None:
    try:
        engine = create_engine(get_db_url())
        with engine.connect() as conn:
            model_ids = [
                r[0] for r in conn.execute(text("SELECT id FROM ifc_source_models ORDER BY id"))
            ]
        for sid in model_ids:
            with Session(engine) as session, session.begin():
                created = ensure_catalog_entry(session, sid)
            with Session(engine) as session:
                readiness = verify_model_readiness(session, sid)
            print(f"[catalog] model {sid}: created={created['created']}")
            print(f"[readiness] model {sid}: {json.dumps(readiness, default=str)}")
    except Exception as exc:  # noqa: BLE001 - CLI surface
        raise SystemExit(sanitize_db_error(str(exc))) from None


if __name__ == "__main__":
    main()
