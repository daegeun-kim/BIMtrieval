"""Versioned, repeatable SQL migrations (Task 34).

Schema *creation* is idempotent already — the SQLAlchemy models are the source
of truth and `Base.metadata.create_all()` is safe to re-run. What was missing is
a record of which hand-written SQL changes have been applied to a given
database, so a second person (or a container starting for the first time) can
reach the same schema without knowing which one-off scripts to run in which
order.

The ledger is one table:

    schema_migrations(version PRIMARY KEY, checksum, applied_at)

Migrations are the `.sql` files in `bim_rag/schema/migrations/`, applied in
filename order, each inside its own transaction. Already-applied versions are
skipped, so running this is always safe.

A file that CHANGED after being applied is an error, not a silent skip: the
database no longer matches the file that claims to describe it, and quietly
continuing would hide a real divergence. Fix it by adding a new migration
rather than editing history.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Engine

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "schema" / "migrations"

_LEDGER_DDL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version    TEXT PRIMARY KEY,
    checksum   TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""


class MigrationDivergenceError(RuntimeError):
    """An applied migration's file no longer matches what was applied."""


@dataclass(frozen=True)
class Migration:
    version: str
    path: Path
    sql: str

    @property
    def checksum(self) -> str:
        return hashlib.sha256(self.sql.encode("utf-8")).hexdigest()


def discover() -> list[Migration]:
    """Every migration on disk, in filename order (`0001_…`, `0002_…`, …)."""
    out = []
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        out.append(
            Migration(
                version=path.stem,
                path=path,
                sql=path.read_text(encoding="utf-8"),
            )
        )
    return out


def applied_versions(engine: Engine) -> dict[str, str]:
    """`{version: checksum}` for everything already applied to this database."""
    with engine.begin() as conn:
        conn.execute(text(_LEDGER_DDL))
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT version, checksum FROM schema_migrations")).all()
    return {version: checksum for version, checksum in rows}


def pending(engine: Engine) -> list[Migration]:
    """Migrations not yet applied. Raises if an applied one has since changed."""
    already = applied_versions(engine)
    out: list[Migration] = []
    for migration in discover():
        recorded = already.get(migration.version)
        if recorded is None:
            out.append(migration)
        elif recorded != migration.checksum:
            raise MigrationDivergenceError(
                f"{migration.version} was applied to this database, but "
                f"{migration.path.name} has changed since. The database no longer "
                "matches the file that describes it. Add a new migration instead "
                "of editing an applied one."
            )
    return out


def apply_pending(engine: Engine) -> list[str]:
    """Apply every pending migration in order. Returns the versions applied."""
    applied: list[str] = []
    for migration in pending(engine):
        with engine.begin() as conn:
            conn.execute(text(migration.sql))
            conn.execute(
                text(
                    "INSERT INTO schema_migrations (version, checksum) VALUES (:version, :checksum)"
                ),
                {"version": migration.version, "checksum": migration.checksum},
            )
        applied.append(migration.version)
    return applied
