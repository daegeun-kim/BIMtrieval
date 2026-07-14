-- PROPOSAL — NOT EXECUTED.
--
-- Mirrors backend/src/db/models.py (ModelFamily, SourceModelCatalogEntry).
-- Additive only: creates two new tables and does not ALTER any of the five
-- existing tables (ifc_source_models, ifc_entities, ifc_relationships,
-- relationship_members, rag_documents). Task 04 authorizes writing this file
-- for review only; applying it against the database is explicitly out of
-- scope (see tasks/task04.md "Prohibited actions").

CREATE TABLE IF NOT EXISTS model_families (
    id            SERIAL PRIMARY KEY,
    family_key    TEXT NOT NULL UNIQUE,
    display_name  TEXT NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_model_families_family_key
    ON model_families (family_key);

CREATE TABLE IF NOT EXISTS source_model_catalog_entries (
    id                      SERIAL PRIMARY KEY,
    source_model_id         INTEGER NOT NULL UNIQUE
                                REFERENCES ifc_source_models (id) ON DELETE CASCADE,
    model_family_id         INTEGER REFERENCES model_families (id) ON DELETE SET NULL,

    display_name            TEXT,
    version_label           TEXT,
    version_order           INTEGER,
    is_current               BOOLEAN NOT NULL DEFAULT false,

    project_type            TEXT,
    discipline               TEXT,
    tags                     JSONB,
    description              TEXT,
    status                   TEXT NOT NULL DEFAULT 'available'
                                CHECK (status IN ('available', 'unavailable', 'processing')),
    viewer_source_location   TEXT,

    -- Per-field provenance map, e.g. {"project_type": "ifc_extracted", "tags": "manual"}
    field_provenance         JSONB,

    created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_catalog_entries_source_model_id
    ON source_model_catalog_entries (source_model_id);
CREATE INDEX IF NOT EXISTS ix_catalog_entries_model_family_id
    ON source_model_catalog_entries (model_family_id);
CREATE INDEX IF NOT EXISTS ix_catalog_entries_is_current
    ON source_model_catalog_entries (is_current);
