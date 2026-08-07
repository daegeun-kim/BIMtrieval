"""Portable configuration, IFC resolution, and the migration ledger (Task 34).

Offline: no database, no IFC parsing, no embedding model. The migration runner
is exercised against a fake engine that records what it was asked to execute, so
its ordering/skipping/divergence rules are testable without PostgreSQL.
"""

from __future__ import annotations

import tomllib
from pathlib import Path, PurePosixPath

import pytest

from bim_rag import config
from bim_rag.db_admin import migrations

REPO_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# .env.example — the contract a first-time user copies
# ---------------------------------------------------------------------------


def test_env_example_exists_and_declares_exactly_the_required_names():
    text = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    assigned = {
        line.split("=", 1)[0].strip()
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#") and "=" in line
    }
    assert assigned == {"db_url", "DATABASE_URL", "OPENAI_API_KEY"}


def test_env_example_carries_no_real_credential():
    """Every value must be an obvious placeholder, not something usable."""
    text = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    for line in text.splitlines():
        if line.startswith("OPENAI_API_KEY="):
            assert line.endswith("sk-your-own-key-here")
        if line.startswith(("db_url=", "DATABASE_URL=")):
            assert "CHANGE_ME" in line


def test_the_two_database_urls_are_documented_as_different_roles():
    """The read-only backend boundary only exists if the user knows to set it."""
    text = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    assert "read-only" in text
    assert "bim_rag_query_ro" in text
    assert "bootstrap_readonly_role" in text


# ---------------------------------------------------------------------------
# IFC resolution — a path, or a filename in the documented folder
# ---------------------------------------------------------------------------


def test_an_existing_path_is_used_as_given(tmp_path):
    model = tmp_path / "tower.ifc"
    model.write_text("ISO-10303-21;", encoding="utf-8")
    assert config.resolve_ifc_path(model) == model


def test_a_bare_filename_resolves_inside_the_ifc_folder(tmp_path, monkeypatch):
    ifc_dir = tmp_path / "ifc"
    ifc_dir.mkdir()
    model = ifc_dir / "tower.ifc"
    model.write_text("ISO-10303-21;", encoding="utf-8")
    monkeypatch.setattr(config, "get_ifc_dir", lambda: ifc_dir)

    assert config.resolve_ifc_path("tower.ifc") == model


def test_a_missing_file_names_both_places_it_looked(tmp_path, monkeypatch):
    """The error has to tell the user what to do, not just that it failed."""
    ifc_dir = tmp_path / "ifc"
    monkeypatch.setattr(config, "get_ifc_dir", lambda: ifc_dir)

    with pytest.raises(FileNotFoundError) as excinfo:
        config.resolve_ifc_path("absent.ifc")

    message = str(excinfo.value)
    assert "absent.ifc" in message
    assert str(ifc_dir) in message


def test_the_ifc_folder_defaults_beside_the_env_file(monkeypatch):
    monkeypatch.delenv("ifc_dir", raising=False)
    monkeypatch.delenv("IFC_DIR", raising=False)
    assert config.get_ifc_dir() == config._ENV_FILE.parent / "ifc"


def test_the_ifc_folder_is_overridable_for_models_stored_elsewhere(monkeypatch):
    monkeypatch.setenv("ifc_dir", r"D:\shared\bim")
    assert config.get_ifc_dir() == Path(r"D:\shared\bim")


# ---------------------------------------------------------------------------
# Documented entry points actually exist
# ---------------------------------------------------------------------------


def test_every_declared_console_script_is_importable():
    """A broken entry point is worse than a missing one: `bim-pipeline` shipped
    for months importing `run_stage1`, which had already been removed."""
    import importlib

    scripts = tomllib.loads(
        (REPO_ROOT / "ingestion" / "pyproject.toml").read_text(encoding="utf-8")
    )["project"]["scripts"]
    assert {"bim-db-init", "bim-import"} <= set(scripts)

    for name, target in scripts.items():
        module_name, _, attribute = target.partition(":")
        module = importlib.import_module(module_name)
        assert callable(getattr(module, attribute)), f"{name} -> {target} is not callable"


# ---------------------------------------------------------------------------
# Migration ledger
# ---------------------------------------------------------------------------


class _FakeConn:
    def __init__(self, recorder, applied):
        self._recorder = recorder
        self._applied = applied

    def execute(self, statement, params=None):
        self._recorder.append((str(statement), params))
        if "SELECT version, checksum FROM schema_migrations" in str(statement):
            return _FakeResult([(v, c) for v, c in self._applied.items()])
        return _FakeResult([])

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeEngine:
    """Records executed statements; reports `applied` as the ledger contents."""

    def __init__(self, applied=None):
        self.statements: list[tuple[str, object]] = []
        self.applied = dict(applied or {})

    def begin(self):
        return _FakeConn(self.statements, self.applied)

    def connect(self):
        return _FakeConn(self.statements, self.applied)


def test_migrations_are_discovered_in_filename_order():
    versions = [m.version for m in migrations.discover()]
    assert versions == sorted(versions)
    assert "0001_catalog_metadata_proposal" in versions


def test_a_migration_checksum_is_content_addressed():
    first, *_ = migrations.discover()
    assert len(first.checksum) == 64
    assert (
        first.checksum
        != migrations.Migration(
            version=first.version, path=first.path, sql=first.sql + "\n-- edited"
        ).checksum
    )


def test_an_empty_database_has_every_migration_pending():
    engine = _FakeEngine()
    assert [m.version for m in migrations.pending(engine)] == [
        m.version for m in migrations.discover()
    ]


def test_an_already_applied_migration_is_skipped():
    """Repeatability: running setup twice must not re-run anything."""
    known = {m.version: m.checksum for m in migrations.discover()}
    assert migrations.pending(_FakeEngine(known)) == []


def test_a_changed_applied_migration_is_an_error_not_a_silent_skip():
    """The database no longer matches the file claiming to describe it."""
    known = {m.version: "0" * 64 for m in migrations.discover()}
    with pytest.raises(migrations.MigrationDivergenceError) as excinfo:
        migrations.pending(_FakeEngine(known))
    assert "has changed since" in str(excinfo.value)


def test_applying_records_each_version_in_the_ledger():
    engine = _FakeEngine()
    applied = migrations.apply_pending(engine)

    assert applied == [m.version for m in migrations.discover()]
    inserts = [
        params
        for statement, params in engine.statements
        if "INSERT INTO schema_migrations" in statement
    ]
    assert [p["version"] for p in inserts] == applied


def test_the_migrations_are_declared_as_package_data():
    """A non-editable install must ship the SQL, or setup silently does nothing.

    `bim-db-init` reads `bim_rag/schema/migrations/*.sql` at runtime to decide
    what to apply. The editable install used everywhere locally points at the
    source tree, so missing package-data was invisible until the container built
    a real wheel — which contained no `.sql` at all, meaning `bim-db-init` would
    have reported "none pending" against a database with no schema.
    """
    pyproject = tomllib.loads(
        (REPO_ROOT / "ingestion" / "pyproject.toml").read_text(encoding="utf-8")
    )
    patterns = pyproject["tool"]["setuptools"]["package-data"]["bim_rag"]
    assert "schema/migrations/*.sql" in patterns
    assert "schema/*.sql" in patterns

    # Every non-Python file under the package must be matched by some pattern.
    package_root = REPO_ROOT / "ingestion" / "src" / "bim_rag"
    data_files = [
        path
        for path in package_root.rglob("*")
        if path.is_file() and path.suffix not in {".py", ".pyc"}
    ]
    assert data_files, "expected the schema SQL to exist"
    for path in data_files:
        relative = path.relative_to(package_root).as_posix()
        assert any(PurePosixPath(relative).match(pattern) for pattern in patterns), (
            f"{relative} would not be installed"
        )
