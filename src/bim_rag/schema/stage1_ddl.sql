-- Stage 1: Structured IFC import schema (no vector extension required)
-- Run ONLY when explicitly authorized (Stage 1 execution).

CREATE TABLE IF NOT EXISTS ifc_source_models (
    id                        SERIAL PRIMARY KEY,
    file_path                 TEXT        NOT NULL,
    file_name                 TEXT        NOT NULL,
    file_fingerprint          TEXT        NOT NULL UNIQUE,
    ifc_schema                TEXT,
    import_timestamp          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    total_entity_count        INTEGER,
    eligible_entity_count     INTEGER,
    excluded_relationship_count INTEGER,
    extraction_metadata       JSONB
);

CREATE INDEX IF NOT EXISTS ix_ifc_source_models_fingerprint
    ON ifc_source_models (file_fingerprint);

CREATE TABLE IF NOT EXISTS ifc_entities (
    id               SERIAL PRIMARY KEY,
    source_model_id  INTEGER NOT NULL REFERENCES ifc_source_models(id) ON DELETE CASCADE,
    global_id        TEXT    NOT NULL,
    step_id          INTEGER,
    ifc_class        TEXT    NOT NULL,
    canonical_json   JSONB   NOT NULL,
    import_timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    extraction_warnings JSONB,
    CONSTRAINT uq_entity_model_globalid UNIQUE (source_model_id, global_id)
);

CREATE INDEX IF NOT EXISTS ix_ifc_entities_ifc_class  ON ifc_entities (ifc_class);
CREATE INDEX IF NOT EXISTS ix_ifc_entities_global_id  ON ifc_entities (global_id);
