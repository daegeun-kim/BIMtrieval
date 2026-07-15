-- Additive migration: add ifc_relationships and relationship_members tables.
-- Safe to run against an existing database that already has ifc_source_models
-- and ifc_entities from Task 02. Uses IF NOT EXISTS throughout.
-- Run ONLY when explicitly authorized (Task 02-1).

CREATE TABLE IF NOT EXISTS ifc_relationships (
    id                  SERIAL PRIMARY KEY,
    source_model_id     INTEGER NOT NULL REFERENCES ifc_source_models(id) ON DELETE CASCADE,
    global_id           TEXT    NOT NULL,
    step_id             INTEGER,
    ifc_class           TEXT    NOT NULL,
    name                TEXT,
    description         TEXT,
    canonical_json      JSONB   NOT NULL,
    import_timestamp    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    extraction_warnings JSONB,
    CONSTRAINT uq_rel_model_globalid UNIQUE (source_model_id, global_id)
);

CREATE INDEX IF NOT EXISTS ix_ifc_relationships_ifc_class
    ON ifc_relationships (ifc_class);
CREATE INDEX IF NOT EXISTS ix_ifc_relationships_global_id
    ON ifc_relationships (global_id);
CREATE INDEX IF NOT EXISTS ix_ifc_relationships_source_model_id
    ON ifc_relationships (source_model_id);

-- relationship_members: one row per direct endpoint in a relationship.
-- NULLS NOT DISTINCT: treats NULL member_order as equal for dedup (PG15+).
CREATE TABLE IF NOT EXISTS relationship_members (
    id                  SERIAL PRIMARY KEY,
    relationship_id     INTEGER NOT NULL REFERENCES ifc_relationships(id) ON DELETE CASCADE,
    source_model_id     INTEGER NOT NULL REFERENCES ifc_source_models(id) ON DELETE CASCADE,
    role                TEXT    NOT NULL,
    member_order        INTEGER,
    endpoint_step_id    INTEGER,
    endpoint_ifc_class  TEXT,
    endpoint_global_id  TEXT,
    endpoint_name       TEXT,
    entity_id           INTEGER REFERENCES ifc_entities(id) ON DELETE SET NULL,
    CONSTRAINT uq_member_rel_role_order_step
        UNIQUE NULLS NOT DISTINCT (relationship_id, role, member_order, endpoint_step_id)
);

CREATE INDEX IF NOT EXISTS ix_relationship_members_relationship_id
    ON relationship_members (relationship_id);
CREATE INDEX IF NOT EXISTS ix_relationship_members_entity_id
    ON relationship_members (entity_id);
CREATE INDEX IF NOT EXISTS ix_relationship_members_source_model_id
    ON relationship_members (source_model_id);
