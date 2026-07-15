"""One-off, idempotent application of the additive catalog-metadata migration
(spec_v003 §5, tasks/task05.md item 2).

Verifies, before and after, that the five existing canonical tables'
row counts are unchanged, then creates exactly the two new tables
(`model_families`, `source_model_catalog_entries` — mirrors
bim_rag/schema/migrations/0001_catalog_metadata_proposal.sql) and seeds one
catalog-metadata row per currently-ingested source model that doesn't
already have one, using only values derivable from the ingested data itself
(tasks/task05.md item 14: "do not invent building use/version metadata" —
project_type/discipline/tags/description are left null).

Run manually from ingestion/ in the bim_rag Conda env (idempotent):
    python -m bim_rag.db_admin.apply_catalog_migration
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

import bim_rag.schema.models as catalog_models  # noqa: F401  (registers catalog tables on Base.metadata)
from bim_rag.config import get_db_url, sanitize_db_error
from bim_rag.schema.models import (
    Base,
    DbIfcRelationship,
    IfcEntity,
    IfcSourceModel,
    RagDocument,
    RelationshipMember,
)

_EXISTING_TABLES = [
    IfcSourceModel.__table__,
    IfcEntity.__table__,
    DbIfcRelationship.__table__,
    RelationshipMember.__table__,
    RagDocument.__table__,
]
_NEW_TABLES = [
    catalog_models.ModelFamily.__table__,
    catalog_models.SourceModelCatalogEntry.__table__,
]


def _snapshot_counts(engine: Engine) -> dict[str, int]:
    with Session(engine) as session:
        return {
            t.name: session.execute(select(func.count()).select_from(t)).scalar_one()
            for t in _EXISTING_TABLES
        }


def apply_migration(engine: Engine) -> None:
    before = _snapshot_counts(engine)
    Base.metadata.create_all(engine, tables=_NEW_TABLES)
    after = _snapshot_counts(engine)
    if before != after:
        raise RuntimeError(
            f"Migration was not additive: existing row counts changed {before} -> {after}."
        )
    print(f"[apply_catalog_migration] Existing table counts unchanged: {after}")
    print(f"[apply_catalog_migration] Created (if absent): {[t.name for t in _NEW_TABLES]}")


def seed_initial_catalog_metadata(engine: Engine) -> None:
    with Session(engine) as session, session.begin():
        source_models = session.execute(select(IfcSourceModel)).scalars().all()
        for sm in source_models:
            existing = session.execute(
                select(catalog_models.SourceModelCatalogEntry).where(
                    catalog_models.SourceModelCatalogEntry.source_model_id == sm.id
                )
            ).scalar_one_or_none()
            if existing is not None:
                print(
                    f"[apply_catalog_migration] source_model_id={sm.id} already has a catalog "
                    "entry, skipping seed"
                )
                continue

            stem = Path(sm.file_name).stem
            family_key = stem.lower().replace(" ", "_")

            family = session.execute(
                select(catalog_models.ModelFamily).where(
                    catalog_models.ModelFamily.family_key == family_key
                )
            ).scalar_one_or_none()
            if family is None:
                family = catalog_models.ModelFamily(family_key=family_key, display_name=stem)
                session.add(family)
                session.flush()

            entry = catalog_models.SourceModelCatalogEntry(
                source_model_id=sm.id,
                model_family_id=family.id,
                display_name=stem,
                version_label="v1",
                version_order=1,
                is_current=True,
                status="available",
                viewer_source_location=sm.file_path,
                field_provenance={
                    "display_name": "derived_exact",
                    "version_label": "derived_exact",
                    "version_order": "derived_exact",
                    "is_current": "derived_exact",
                    "status": "derived_exact",
                    "viewer_source_location": "ifc_extracted",
                },
            )
            session.add(entry)
            print(
                f"[apply_catalog_migration] Seeded catalog entry for source_model_id={sm.id} "
                f"(family={family_key!r})"
            )


def main() -> None:
    try:
        engine = create_engine(get_db_url())
        apply_migration(engine)
        seed_initial_catalog_metadata(engine)
        engine.dispose()
    except Exception as exc:
        raise RuntimeError(sanitize_db_error(str(exc))) from None


if __name__ == "__main__":
    main()
