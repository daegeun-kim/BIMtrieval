"""Catalog metadata ORM is additive and reviewable (tasks/task04.md required
verification: "Proposed catalog schema is additive and reviewable").

Importing db.models must never call create_all/apply a migration, and must
not remove or alter the five existing canonical tables.
"""

from __future__ import annotations

from app.db.models import Base

_EXISTING_TABLES = {
    "ifc_source_models",
    "ifc_entities",
    "ifc_relationships",
    "relationship_members",
    "rag_documents",
}


def test_import_does_not_execute_a_migration(monkeypatch):
    calls = []
    monkeypatch.setattr(Base.metadata, "create_all", lambda *a, **k: calls.append((a, k)))

    import app.db.models  # noqa: F401

    assert calls == []


def test_new_tables_are_additive_and_named():
    import app.db.models  # noqa: F401

    table_names = set(Base.metadata.tables.keys())
    assert "model_families" in table_names
    assert "source_model_catalog_entries" in table_names


def test_existing_five_tables_untouched():
    import app.db.models  # noqa: F401

    table_names = set(Base.metadata.tables.keys())
    assert _EXISTING_TABLES.issubset(table_names)
    # spot-check a column that must survive unchanged
    ifc_entities = Base.metadata.tables["ifc_entities"]
    assert "global_id" in ifc_entities.columns
    assert "canonical_json" in ifc_entities.columns


def test_catalog_entry_references_ifc_source_models():
    import app.db.models as catalog

    entry_table = catalog.SourceModelCatalogEntry.__table__
    fk_targets = {fk.target_fullname for fk in entry_table.foreign_keys}
    assert "ifc_source_models.id" in fk_targets
