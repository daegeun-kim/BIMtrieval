"""Backend-owned, read-oriented ORM for the live BIM database (Task 09).

The backend is independent of the ingestion project and must not import
`bim_rag`. These SQLAlchemy models are a backend-owned mirror of the live
schema created by ingestion. They define the five canonical BIM tables plus
the two catalog-metadata tables the backend reads, preserving the shared
identifiers (`global_id`, `source_model_id`, `entity_id`, `relationship_id`)
that let SQL, RAG, and graph results refer to the same BIM objects.

The backend is READ-ONLY with respect to BIM corpus data: nothing here calls
`create_all`, Alembic, or any migration. Schema creation/migration is owned by
ingestion. The small amount of definitional overlap with the ingestion schema
is intentional and acceptable (Task 09): application independence over
de-duplication.
"""

from __future__ import annotations

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    __allow_unmapped__ = True


# ---------------------------------------------------------------------------
# Canonical BIM tables (created and populated by ingestion; read-only here)
# ---------------------------------------------------------------------------


class IfcSourceModel(Base):
    """One row per imported IFC source file (identified by SHA-256 fingerprint)."""

    __tablename__ = "ifc_source_models"
    __allow_unmapped__ = True

    id = Column(Integer, primary_key=True, autoincrement=True)
    file_path = Column(Text, nullable=False)
    file_name = Column(Text, nullable=False)
    file_fingerprint = Column(Text, nullable=False, unique=True)
    ifc_schema = Column(Text)
    import_timestamp = Column(DateTime(timezone=True), server_default=func.now())
    total_entity_count = Column(Integer)
    eligible_entity_count = Column(Integer)
    excluded_relationship_count = Column(Integer)
    extraction_metadata = Column(JSONB)

    entities = relationship("IfcEntity", back_populates="source_model")

    __table_args__ = (Index("ix_ifc_source_models_fingerprint", "file_fingerprint"),)


class IfcEntity(Base):
    """One row per eligible IFC entity (IfcRoot with GlobalId, not IfcRelationship)."""

    __tablename__ = "ifc_entities"
    __allow_unmapped__ = True

    id = Column(Integer, primary_key=True, autoincrement=True)
    source_model_id = Column(
        Integer, ForeignKey("ifc_source_models.id", ondelete="CASCADE"), nullable=False
    )
    global_id = Column(Text, nullable=False)
    step_id = Column(Integer)
    ifc_class = Column(Text, nullable=False)
    canonical_json = Column(JSONB, nullable=False)
    import_timestamp = Column(DateTime(timezone=True), server_default=func.now())
    extraction_warnings = Column(JSONB)

    source_model = relationship("IfcSourceModel", back_populates="entities")

    __table_args__ = (
        UniqueConstraint("source_model_id", "global_id", name="uq_entity_model_globalid"),
        Index("ix_ifc_entities_ifc_class", "ifc_class"),
        Index("ix_ifc_entities_global_id", "global_id"),
    )


class DbIfcRelationship(Base):
    """One row per IFC relationship entity (IfcRelationship with GlobalId)."""

    __tablename__ = "ifc_relationships"
    __allow_unmapped__ = True

    id = Column(Integer, primary_key=True, autoincrement=True)
    source_model_id = Column(
        Integer, ForeignKey("ifc_source_models.id", ondelete="CASCADE"), nullable=False
    )
    global_id = Column(Text, nullable=False)
    step_id = Column(Integer)
    ifc_class = Column(Text, nullable=False)
    name = Column(Text)
    description = Column(Text)
    canonical_json = Column(JSONB, nullable=False)
    import_timestamp = Column(DateTime(timezone=True), server_default=func.now())
    extraction_warnings = Column(JSONB)

    source_model = relationship("IfcSourceModel")
    members = relationship("RelationshipMember", back_populates="ifc_relationship")

    __table_args__ = (
        UniqueConstraint("source_model_id", "global_id", name="uq_rel_model_globalid"),
        Index("ix_ifc_relationships_ifc_class", "ifc_class"),
        Index("ix_ifc_relationships_global_id", "global_id"),
        Index("ix_ifc_relationships_source_model_id", "source_model_id"),
    )


class RelationshipMember(Base):
    """One row per direct endpoint in an IFC relationship."""

    __tablename__ = "relationship_members"
    __allow_unmapped__ = True

    id = Column(Integer, primary_key=True, autoincrement=True)
    relationship_id = Column(
        Integer, ForeignKey("ifc_relationships.id", ondelete="CASCADE"), nullable=False
    )
    source_model_id = Column(
        Integer, ForeignKey("ifc_source_models.id", ondelete="CASCADE"), nullable=False
    )
    role = Column(Text, nullable=False)
    member_order = Column(Integer)
    endpoint_step_id = Column(Integer)
    endpoint_ifc_class = Column(Text)
    endpoint_global_id = Column(Text)
    endpoint_name = Column(Text)
    entity_id = Column(Integer, ForeignKey("ifc_entities.id", ondelete="SET NULL"))

    ifc_relationship = relationship("DbIfcRelationship", back_populates="members")

    __table_args__ = (
        UniqueConstraint(
            "relationship_id",
            "role",
            "member_order",
            "endpoint_step_id",
            name="uq_member_rel_role_order_step",
            postgresql_nulls_not_distinct=True,
        ),
        Index("ix_relationship_members_relationship_id", "relationship_id"),
        Index("ix_relationship_members_entity_id", "entity_id"),
        Index("ix_relationship_members_source_model_id", "source_model_id"),
    )


class RagDocument(Base):
    """One row per generated document/vector for an entity or relationship."""

    __tablename__ = "rag_documents"
    __allow_unmapped__ = True

    id = Column(Integer, primary_key=True, autoincrement=True)
    source_model_id = Column(
        Integer, ForeignKey("ifc_source_models.id", ondelete="CASCADE"), nullable=False
    )
    source_kind = Column(Text, nullable=False)
    entity_id = Column(Integer, ForeignKey("ifc_entities.id", ondelete="CASCADE"))
    relationship_id = Column(Integer, ForeignKey("ifc_relationships.id", ondelete="CASCADE"))
    document_type = Column(Text, nullable=False)
    document_text = Column(Text, nullable=False)
    text_truncated = Column(Boolean, nullable=False, default=False)
    text_template_version = Column(Text, nullable=False)
    embedding_model = Column(Text, nullable=False)
    embedding_dim = Column(Integer, nullable=False, default=1024)
    embedding = Column(Vector(1024))
    generation_timestamp = Column(DateTime(timezone=True), server_default=func.now())
    generation_metadata = Column(JSONB)
    source_hash = Column(Text)
    text_hash = Column(Text)
    original_token_count = Column(Integer)
    encoded_token_count = Column(Integer)

    __table_args__ = (
        CheckConstraint(
            "source_kind IN ('entity', 'relationship')",
            name="ck_rag_source_kind",
        ),
        CheckConstraint(
            "document_type IN ('entity_description', 'relationship_description')",
            name="ck_rag_document_type",
        ),
        CheckConstraint(
            "(entity_id IS NOT NULL AND relationship_id IS NULL) OR "
            "(entity_id IS NULL AND relationship_id IS NOT NULL)",
            name="ck_rag_source_ref_xor",
        ),
        CheckConstraint(
            "(source_kind = 'entity' AND document_type = 'entity_description') OR "
            "(source_kind = 'relationship' AND document_type = 'relationship_description')",
            name="ck_rag_kind_type_agreement",
        ),
        CheckConstraint("embedding_dim = 1024", name="ck_rag_embedding_dim"),
        Index("ix_rag_documents_source_model_id", "source_model_id"),
        Index("ix_rag_documents_source_model_kind", "source_model_id", "source_kind"),
        Index("ix_rag_documents_entity_id", "entity_id"),
        Index("ix_rag_documents_relationship_id", "relationship_id"),
        Index(
            "ix_rag_documents_doc_type_version",
            "document_type",
            "text_template_version",
            "embedding_model",
        ),
        Index(
            "uq_rag_entity_doc",
            "entity_id",
            "document_type",
            "text_template_version",
            "embedding_model",
            unique=True,
            postgresql_where=text("entity_id IS NOT NULL"),
        ),
        Index(
            "uq_rag_rel_doc",
            "relationship_id",
            "document_type",
            "text_template_version",
            "embedding_model",
            unique=True,
            postgresql_where=text("relationship_id IS NOT NULL"),
        ),
        Index(
            "ix_rag_documents_embedding_cosine",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )


class EntitySpatialMembership(Base):
    """Normalized effective entity-to-storey membership (task26 §4.2).

    Created and populated by ingestion; strictly read-only here. This table —
    not the denormalized `canonical_json.storey` scalar — is the definition of
    spatial membership for predicates, RAG scoping, floor grouping, and viewer
    hydration.
    """

    __tablename__ = "entity_spatial_memberships"
    __allow_unmapped__ = True

    id = Column(Integer, primary_key=True, autoincrement=True)
    source_model_id = Column(
        Integer, ForeignKey("ifc_source_models.id", ondelete="CASCADE"), nullable=False
    )
    entity_id = Column(Integer, ForeignKey("ifc_entities.id", ondelete="CASCADE"))
    entity_global_id = Column(Text, nullable=False)
    storey_entity_id = Column(Integer, ForeignKey("ifc_entities.id", ondelete="CASCADE"))
    storey_global_id = Column(Text, nullable=False)
    source_relationship_id = Column(
        Integer, ForeignKey("ifc_relationships.id", ondelete="SET NULL")
    )
    source_kind = Column(Text, nullable=False)
    hop_count = Column(Integer, nullable=False)
    resolution_status = Column(Text, nullable=False)
    is_primary = Column(Boolean, nullable=False, default=False)
    provenance = Column(Text)

    __table_args__ = (
        Index("ix_esm_model_entity", "source_model_id", "entity_id"),
        Index("ix_esm_model_entity_gid", "source_model_id", "entity_global_id"),
        Index("ix_esm_model_storey_gid", "source_model_id", "storey_global_id"),
        Index("ix_esm_model_storey_entity", "source_model_id", "storey_entity_id"),
        {"extend_existing": True},
    )


# ---------------------------------------------------------------------------
# Catalog-metadata tables (spec_v002 §5; created by ingestion migration).
# Read by the backend model catalog. Backend never writes these.
# ---------------------------------------------------------------------------


class ModelFamily(Base):
    """Groups multiple ifc_source_models versions under one logical model family."""

    __tablename__ = "model_families"
    __allow_unmapped__ = True

    id = Column(Integer, primary_key=True, autoincrement=True)
    family_key = Column(Text, nullable=False, unique=True)
    display_name = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (Index("ix_model_families_family_key", "family_key"),)


class SourceModelCatalogEntry(Base):
    """Catalog/version metadata for one ifc_source_models row (spec_v002 §5).

    One-to-one with `ifc_source_models` via `source_model_id`. `field_provenance`
    records per-field provenance (`ifc_extracted` | `manual` | `derived_exact`).
    """

    __tablename__ = "source_model_catalog_entries"
    __allow_unmapped__ = True

    id = Column(Integer, primary_key=True, autoincrement=True)
    source_model_id = Column(
        Integer,
        ForeignKey("ifc_source_models.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    model_family_id = Column(Integer, ForeignKey("model_families.id", ondelete="SET NULL"))

    display_name = Column(Text)
    version_label = Column(Text)
    version_order = Column(Integer)
    is_current = Column(Boolean, nullable=False, default=False)

    project_type = Column(Text)
    discipline = Column(Text)
    tags = Column(JSONB)
    description = Column(Text)
    status = Column(Text, nullable=False, default="available")
    viewer_source_location = Column(Text)

    field_provenance = Column(JSONB)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        CheckConstraint(
            "status IN ('available', 'unavailable', 'processing')",
            name="ck_catalog_entry_status",
        ),
        Index("ix_catalog_entries_source_model_id", "source_model_id"),
        Index("ix_catalog_entries_model_family_id", "model_family_id"),
        Index("ix_catalog_entries_is_current", "is_current"),
    )
