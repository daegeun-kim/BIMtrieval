-- Stage 2: pgvector extension + element_vectors table
-- Run ONLY after Stage 1 completes and when explicitly authorized.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS element_vectors (
    id                     SERIAL PRIMARY KEY,
    entity_id              INTEGER NOT NULL REFERENCES ifc_entities(id) ON DELETE CASCADE,
    document_type          TEXT    NOT NULL DEFAULT 'element_description',
    document_text          TEXT    NOT NULL,
    text_truncated         BOOLEAN NOT NULL DEFAULT FALSE,
    text_template_version  TEXT    NOT NULL DEFAULT 'v001',
    embedding_model        TEXT    NOT NULL DEFAULT 'BAAI/bge-m3',
    embedding_dim          INTEGER NOT NULL DEFAULT 1024,
    embedding              vector(1024),
    generation_timestamp   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_vector_entity_type_version
        UNIQUE (entity_id, document_type, text_template_version, embedding_model),
    CONSTRAINT ck_document_type CHECK (document_type = 'element_description'),
    CONSTRAINT ck_embedding_dim CHECK (embedding_dim = 1024)
);

CREATE INDEX IF NOT EXISTS ix_element_vectors_entity_id
    ON element_vectors (entity_id);

-- cosine-distance HNSW index (BGE-M3 embeddings are L2-normalised before storage)
CREATE INDEX IF NOT EXISTS ix_element_vectors_embedding_cosine
    ON element_vectors USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);
