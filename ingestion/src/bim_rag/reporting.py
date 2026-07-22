"""Validation and reconciliation reporting for Stage 1 and Stage 2."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any


def build_stage1_report(
    scan: dict[str, Any],
    fingerprint: str,
    entities_imported: int,
    entities_upserted: int,
    extraction_failures: int,
    warnings: list[str],
) -> dict[str, Any]:
    return {
        "stage": 1,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "ifc_schema": scan["ifc_schema"],
        "file_fingerprint_prefix": fingerprint[:16] + "...",
        "total_entity_count": scan["total_entity_count"],
        "eligible_entity_count": scan["eligible_entity_count"],
        "excluded_relationship_count": scan["excluded_relationship_count"],
        "duplicate_global_ids": scan.get("duplicate_global_ids", []),
        "class_counts": scan["class_counts"],
        "entities_imported_new": entities_imported,
        "entities_updated": entities_upserted,
        "extraction_failures": extraction_failures,
        "warning_count": len(warnings),
        "warnings_sample": warnings[:10],
    }


def build_structured_report(
    scan: dict[str, Any],
    fingerprint: str,
    source_model_id: int,
    entities_new: int,
    entities_updated: int,
    relationships_new: int,
    relationships_updated: int,
    members_total: int,
    members_resolved: int,
    members_unresolved: int,
    entity_failures: int,
    rel_failures: int,
    warnings: list[str],
) -> dict[str, Any]:
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source_model_id": source_model_id,
        "file_fingerprint_prefix": fingerprint[:16] + "...",
        "ifc_schema": scan["ifc_schema"],
        "total_ifc_entity_count": scan["total_entity_count"],
        "eligible_entity_count": scan["eligible_entity_count"],
        "relationship_count_ifc": scan["relationship_count"],
        "relationship_class_counts": scan.get("relationship_class_counts", {}),
        "entity_class_counts": scan["class_counts"],
        "duplicate_entity_global_ids": scan.get("duplicate_global_ids", []),
        "entities_imported_new": entities_new,
        "entities_updated": entities_updated,
        "relationships_imported_new": relationships_new,
        "relationships_updated": relationships_updated,
        "members_total": members_total,
        "members_resolved": members_resolved,
        "members_unresolved": members_unresolved,
        "entity_extraction_failures": entity_failures,
        "relationship_extraction_failures": rel_failures,
        "warning_count": len(warnings),
        "warnings_sample": warnings[:15],
    }


def build_stage2_report(
    device_str: str,
    entity_count: int,
    vectors_created: int,
    vectors_updated: int,
    truncated_count: int,
    embed_failures: int,
    warnings: list[str],
) -> dict[str, Any]:
    return {
        "stage": 2,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "execution_device": device_str,
        "embedding_model": "BAAI/bge-m3",
        "embedding_dim": 1024,
        "template_version": "v001",
        "document_type": "element_description",
        "entity_count": entity_count,
        "vectors_created_new": vectors_created,
        "vectors_updated": vectors_updated,
        "truncated_texts": truncated_count,
        "embedding_failures": embed_failures,
        "warning_count": len(warnings),
        "warnings_sample": warnings[:10],
    }


def build_unified_report(
    scan: dict[str, Any],
    fingerprint: str,
    source_model_id: int,
    entities_new: int,
    entities_updated: int,
    relationships_new: int,
    relationships_updated: int,
    members_total: int,
    members_resolved: int,
    members_unresolved: int,
    entity_failures: int,
    rel_failures: int,
    vector_stats: dict[str, Any],
    warnings: list[str],
    manifest_stats: dict[str, Any] | None = None,
) -> dict[str, Any]:
    manifest_stats = manifest_stats or {}
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source_model_id": source_model_id,
        "file_fingerprint_prefix": fingerprint[:16] + "...",
        "ifc_schema": scan["ifc_schema"],
        "total_ifc_entity_count": scan["total_entity_count"],
        "eligible_entity_count": scan["eligible_entity_count"],
        "relationship_count_ifc": scan["relationship_count"],
        "relationship_class_counts": scan.get("relationship_class_counts", {}),
        "entity_class_counts": scan["class_counts"],
        "duplicate_entity_global_ids": scan.get("duplicate_global_ids", []),
        "entities_imported_new": entities_new,
        "entities_updated": entities_updated,
        "relationships_imported_new": relationships_new,
        "relationships_updated": relationships_updated,
        "members_total": members_total,
        "members_resolved": members_resolved,
        "members_unresolved": members_unresolved,
        "entity_extraction_failures": entity_failures,
        "relationship_extraction_failures": rel_failures,
        # Vector phase
        "pgvector_enabled": vector_stats.get("pgvector_enabled", False),
        "element_vectors_found": vector_stats.get("element_vectors_found", False),
        "element_vectors_empty": vector_stats.get("element_vectors_empty", True),
        "execution_device": vector_stats.get("execution_device", "unknown"),
        "embedding_model": vector_stats.get("embedding_model", ""),
        "template_version": vector_stats.get("template_version", ""),
        "cuda_batch_size": vector_stats.get("cuda_batch_size"),
        "thread_limit": vector_stats.get("thread_limit"),
        "token_limit": vector_stats.get("token_limit"),
        "entity_docs_new": vector_stats.get("entity_docs_new", 0),
        "entity_docs_updated": vector_stats.get("entity_docs_updated", 0),
        "entity_docs_skipped_valid": vector_stats.get("entity_docs_skipped_valid", 0),
        "entity_docs_truncated": vector_stats.get("entity_docs_truncated", 0),
        "entity_embed_failures": vector_stats.get("entity_embed_failures", 0),
        "rel_docs_new": vector_stats.get("rel_docs_new", 0),
        "rel_docs_updated": vector_stats.get("rel_docs_updated", 0),
        "rel_docs_skipped_valid": vector_stats.get("rel_docs_skipped_valid", 0),
        "rel_docs_truncated": vector_stats.get("rel_docs_truncated", 0),
        "rel_embed_failures": vector_stats.get("rel_embed_failures", 0),
        "total_rag_docs": vector_stats.get("total_rag_docs", 0),
        "last_attempted_batch": vector_stats.get("last_attempted_batch", {}),
        # Semantic manifest (task25 §2.1)
        "manifest_validated": manifest_stats.get("validated", False),
        "manifest_path": manifest_stats.get("path"),
        "manifest_schema_version": manifest_stats.get("manifest_schema_version"),
        "manifest_builder_version": manifest_stats.get("builder_version"),
        "manifest_content_hash": manifest_stats.get("content_hash"),
        "manifest_bytes": manifest_stats.get("bytes"),
        "manifest_estimated_tokens": manifest_stats.get("estimated_tokens"),
        "manifest_semantic_record_count": manifest_stats.get("semantic_record_count"),
        "manifest_class_count": manifest_stats.get("class_count"),
        "manifest_property_field_count": manifest_stats.get("property_field_count"),
        "manifest_quantity_field_count": manifest_stats.get("quantity_field_count"),
        "manifest_relationship_class_count": manifest_stats.get("relationship_class_count"),
        "manifest_missing_capability_count": manifest_stats.get("missing_capability_count"),
        "manifest_unsupported_structure_count": manifest_stats.get("unsupported_structure_count"),
        "manifest_error": manifest_stats.get("error"),
        # §2.1: a model is only "fully query-ready" when its structured data,
        # its semantic manifest, AND its vectors all succeeded.
        "fully_query_ready": bool(
            manifest_stats.get("validated") and vector_stats.get("total_rag_docs", 0) > 0
        ),
        "warning_count": len(warnings) + vector_stats.get("warning_count", 0),
        "warnings_sample": (warnings + vector_stats.get("warnings_sample", []))[:15],
    }


def print_report(report: dict[str, Any], label: str = "Report") -> None:
    print(f"\n{'=' * 60}")
    print(f"  {label}")
    print(f"{'=' * 60}")
    print(json.dumps(report, indent=2, default=str))
    print(f"{'=' * 60}\n")
