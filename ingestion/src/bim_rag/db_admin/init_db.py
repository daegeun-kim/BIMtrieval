"""`bim-db-init` — bring an empty database to the schema BIMtrieval expects.

One repeatable command, safe to run any number of times, replacing the previous
sequence of one-off scripts a new user had to discover and order correctly:

1. `CREATE EXTENSION IF NOT EXISTS vector` (pgvector)
2. create every canonical table from the SQLAlchemy models
3. apply pending SQL migrations, recorded in `schema_migrations`
4. seed catalog metadata for any already-imported model that lacks it
5. optionally create the backend's dedicated read-only role

Connects with `db_url` — the ingestion/write account. The backend's read-only
`DATABASE_URL` cannot and must not create anything.

Usage (from anywhere, in the `bim_rag` environment):

    bim-db-init
    bim-db-init --with-readonly-role
"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

import bim_rag.schema.models as models  # noqa: F401  (registers every table on Base.metadata)
from bim_rag.config import get_db_url, sanitize_db_error
from bim_rag.db_admin.apply_catalog_migration import seed_initial_catalog_metadata
from bim_rag.db_admin.migrations import apply_pending
from bim_rag.schema.models import Base


def _enable_pgvector(engine: Engine) -> None:
    try:
        with engine.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    except Exception as exc:
        raise RuntimeError(
            "Could not enable the pgvector extension. Install the pgvector "
            "binaries for your PostgreSQL server, and make sure the `db_url` "
            f"role may CREATE EXTENSION. Underlying error: {sanitize_db_error(str(exc))}"
        ) from None


def init_database(engine: Engine, *, with_readonly_role: bool = False) -> dict[str, object]:
    """Idempotently bring `engine`'s database to the expected schema."""
    report: dict[str, object] = {}

    print("[bim-db-init] Enabling pgvector...")
    _enable_pgvector(engine)

    print("[bim-db-init] Creating/verifying tables...")
    before = set(Base.metadata.tables)
    Base.metadata.create_all(engine)
    report["tables"] = sorted(before)

    print("[bim-db-init] Applying pending migrations...")
    applied = apply_pending(engine)
    report["migrations_applied"] = applied
    print(f"[bim-db-init]   {len(applied)} applied: {applied or 'none pending'}")

    print("[bim-db-init] Seeding catalog metadata for imported models...")
    seed_initial_catalog_metadata(engine)

    if with_readonly_role:
        print("[bim-db-init] Creating the read-only backend role...")
        # Imported here so the default path does not require CREATEROLE.
        from bim_rag.db_admin.bootstrap_readonly_role import main as bootstrap_readonly

        bootstrap_readonly()
        report["readonly_role"] = True

    return report


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="bim-db-init",
        description=(
            "Create/verify the BIMtrieval database schema. Idempotent: safe to "
            "run repeatedly, including against a database that already has data."
        ),
    )
    parser.add_argument(
        "--with-readonly-role",
        action="store_true",
        help=(
            "Also create the dedicated read-only role the backend connects "
            "through, and write its DATABASE_URL into the repository .env. "
            "Requires CREATEROLE on the db_url connection."
        ),
    )
    args = parser.parse_args()

    engine = None
    try:
        engine = create_engine(get_db_url())
        init_database(engine, with_readonly_role=args.with_readonly_role)
    except Exception as exc:
        print(f"[bim-db-init] FAILED: {sanitize_db_error(str(exc))}", file=sys.stderr)
        sys.exit(1)
    finally:
        if engine is not None:
            engine.dispose()

    print("[bim-db-init] Database is ready. Import a model with: bim-import <file.ifc>")


if __name__ == "__main__":
    main()
