"""Create `entity_spatial_memberships` and backfill every imported model.

Additive migration (task26 §4.2): creates the table/indexes if missing, then
repopulates memberships for each model through the same deterministic
projection the production pipeline runs. Idempotent.

Run:
    python -m bim_rag.db_admin.apply_spatial_membership_migration
"""

from __future__ import annotations

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from bim_rag.config import get_db_url, sanitize_db_error
from bim_rag.schema.models import Base, EntitySpatialMembership
from bim_rag.spatial_membership import populate_spatial_memberships


def main() -> None:
    try:
        engine = create_engine(get_db_url())
        Base.metadata.create_all(engine, tables=[EntitySpatialMembership.__table__])
        with engine.connect() as conn:
            model_ids = [
                r[0] for r in conn.execute(text("SELECT id FROM ifc_source_models ORDER BY id"))
            ]
        for sid in model_ids:
            with Session(engine) as session, session.begin():
                stats = populate_spatial_memberships(session, sid)
            print(f"[spatial_membership] model {sid}: {stats}")
    except Exception as exc:  # noqa: BLE001 - CLI surface
        raise SystemExit(sanitize_db_error(str(exc))) from None


if __name__ == "__main__":
    main()
