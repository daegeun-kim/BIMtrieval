"""One-off, idempotent creation of a dedicated read-only PostgreSQL role for
runtime query execution (spec_v003 §13, tasks/task05.md item 12).

Requires CREATEROLE privilege on the connection loaded from `db_url` in
`.env` (the existing ingestion connection). If that connection lacks
CREATEROLE, this script reports the exact requirement and stops rather than
escalating database authority implicitly (spec_v003 §13: "If creation
requires administrator privileges, document the exact requirement and stop
for user action rather than escalating database authority implicitly.").

The generated password is never printed or logged — only written directly
into the repository `.env` as `DATABASE_URL=...`, which the backend's
`app.config.settings.Settings.get_database_url()` already prefers over the
ingestion `db_url`.

Run manually from ingestion/ in the bim_rag Conda env (idempotent):
    python -m bim_rag.db_admin.bootstrap_readonly_role
"""

from __future__ import annotations

import secrets
from urllib.parse import urlparse, urlunparse

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from bim_rag.config import _ENV_FILE, get_db_url, sanitize_db_error

ROLE_NAME = "bim_rag_query_ro"
STATEMENT_TIMEOUT_MS = 5000

# Granted only if the table currently exists — safe to run before or after
# apply_catalog_migration.py (the two new tables are skipped if absent yet
# and this script can simply be re-run afterward to grant them).
_GRANTED_TABLES = [
    "ifc_source_models",
    "ifc_entities",
    "ifc_relationships",
    "relationship_members",
    "entity_spatial_memberships",
    "rag_documents",
    "model_families",
    "source_model_catalog_entries",
]


def _role_exists(session: Session) -> bool:
    return bool(
        session.execute(
            text("SELECT 1 FROM pg_roles WHERE rolname = :name"), {"name": ROLE_NAME}
        ).first()
    )


def _require_createrole(session: Session) -> None:
    can_create = session.execute(
        text("SELECT rolcreaterole FROM pg_roles WHERE rolname = current_user")
    ).scalar_one()
    if not can_create:
        raise RuntimeError(
            "The connection in .env lacks CREATEROLE privilege. An administrator must run, as a "
            f"superuser: CREATE ROLE {ROLE_NAME} WITH LOGIN PASSWORD '<choose-a-password>'; then "
            "set DATABASE_URL in .env to that role's DSN, and re-run this script to apply grants."
        )


def _current_database(session: Session) -> str:
    return session.execute(text("SELECT current_database()")).scalar_one()


def _apply_grants(session: Session) -> None:
    dbname = _current_database(session)
    session.execute(text(f'GRANT CONNECT ON DATABASE "{dbname}" TO "{ROLE_NAME}"'))
    session.execute(text(f'GRANT USAGE ON SCHEMA public TO "{ROLE_NAME}"'))
    granted = []
    for table in _GRANTED_TABLES:
        exists = session.execute(
            text("SELECT to_regclass(:t) IS NOT NULL"), {"t": f"public.{table}"}
        ).scalar_one()
        if exists:
            session.execute(text(f'GRANT SELECT ON public."{table}" TO "{ROLE_NAME}"'))
            granted.append(table)
    session.execute(
        text(f'ALTER ROLE "{ROLE_NAME}" SET statement_timeout = {STATEMENT_TIMEOUT_MS}')
    )
    session.execute(text(f'REVOKE CREATE ON SCHEMA public FROM "{ROLE_NAME}"'))
    print(f"[bootstrap_readonly_role] Granted SELECT on: {granted}")
    if len(granted) < len(_GRANTED_TABLES):
        missing = sorted(set(_GRANTED_TABLES) - set(granted))
        print(f"[bootstrap_readonly_role] Skipped (not yet present): {missing}")


def _write_database_url_to_env(dsn: str) -> None:
    lines: list[str] = []
    if _ENV_FILE.exists():
        lines = _ENV_FILE.read_text(encoding="utf-8").splitlines()
    lines = [ln for ln in lines if not ln.startswith("DATABASE_URL=")]
    lines.append(f"DATABASE_URL={dsn}")
    _ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _build_dsn(admin_db_url: str, password: str) -> str:
    parsed = urlparse(admin_db_url)
    netloc = f"{ROLE_NAME}:{password}@{parsed.hostname}"
    if parsed.port:
        netloc += f":{parsed.port}"
    return urlunparse(
        (parsed.scheme, netloc, parsed.path, parsed.params, parsed.query, parsed.fragment)
    )


def verify_read_only(dsn: str) -> None:
    engine = create_engine(dsn)
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1 FROM ifc_entities LIMIT 1"))
            insert_rejected = False
            try:
                conn.execute(
                    text(
                        "INSERT INTO ifc_source_models (file_path, file_name, file_fingerprint) "
                        "VALUES ('x', 'x', 'permission-probe-should-fail')"
                    )
                )
            except Exception as exc:
                conn.rollback()
                if "permission denied" in str(exc).lower():
                    insert_rejected = True
                else:
                    raise
            if not insert_rejected:
                conn.rollback()
                raise RuntimeError(f"{ROLE_NAME} was able to INSERT — read-only enforcement failed")
    finally:
        engine.dispose()
    print(f"[bootstrap_readonly_role] Verified: {ROLE_NAME} can SELECT, INSERT is rejected.")


def main() -> None:
    admin_db_url = get_db_url()
    engine = create_engine(admin_db_url)
    new_password: str | None = None
    try:
        with Session(engine) as session, session.begin():
            _require_createrole(session)
            if _role_exists(session):
                print(f"[bootstrap_readonly_role] Role {ROLE_NAME!r} exists; re-applying grants.")
            else:
                new_password = secrets.token_urlsafe(32)
                session.execute(
                    text(f'CREATE ROLE "{ROLE_NAME}" WITH LOGIN PASSWORD :pw'), {"pw": new_password}
                )
                print(f"[bootstrap_readonly_role] Created role {ROLE_NAME!r}.")
            _apply_grants(session)
    except Exception as exc:
        raise RuntimeError(sanitize_db_error(str(exc))) from None
    finally:
        engine.dispose()

    if new_password is not None:
        dsn = _build_dsn(admin_db_url, new_password)
        _write_database_url_to_env(dsn)
        print("[bootstrap_readonly_role] Wrote DATABASE_URL to .env (value not printed or logged).")
        verify_read_only(dsn)
    else:
        print(
            "[bootstrap_readonly_role] Role already existed; password not regenerated. If "
            ".env's DATABASE_URL is missing/stale, drop the role and re-run, or set it manually."
        )


if __name__ == "__main__":
    main()
