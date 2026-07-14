"""Model-catalog metadata ORM (spec_v002 Section 5).

Additive only: reuses the existing `Base` from `bim_rag.schema.models` and adds
two new tables that reference `ifc_source_models.id` by foreign key. Nothing in
this module calls `create_all`, Alembic, or otherwise applies a migration — see
`backend/src/db/migrations/0001_catalog_metadata_proposal.sql` for the reviewable,
NOT-EXECUTED DDL this module corresponds to.

Does not modify or repopulate ifc_source_models, ifc_entities, ifc_relationships,
relationship_members, or rag_documents.
"""

from __future__ import annotations

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB

from bim_rag.schema.models import Base


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
    """Catalog/version metadata for one ifc_source_models row (spec_v002 Section 5).

    One-to-one with `ifc_source_models` via `source_model_id`. `field_provenance`
    records per-field provenance (`ifc_extracted` | `manual` | `derived_exact`,
    spec_v002 Section 5.1), e.g. {"project_type": "ifc_extracted", "tags": "manual"}.
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
