"""Backend reader for ingestion-generated semantic manifests (task25 §2, §8).

The manifest is the semantic API the binder reads: a complete, per-model
inventory of queryable concepts and their coverage. The backend reads and
validates; ingestion writes. There is exactly one JSON contract between them.
"""

from __future__ import annotations

from app.query.semantic.manifest.loader import (
    ManifestUnavailableError,
    clear_manifest_cache,
    get_semantic_manifest,
)
from app.query.semantic.manifest.paths import (
    MANIFEST_SUFFIX,
    ManifestStatus,
    compute_manifest_status,
    expected_manifest_path,
    is_contained,
    manifest_dir,
)
from app.query.semantic.manifest.schema import (
    COVERAGE_ABSENT,
    COVERAGE_EXTRACTION_FAILURE,
    COVERAGE_PARTIAL,
    COVERAGE_POPULATED,
    COVERAGE_UNSUPPORTED,
    COVERAGE_UNSUPPORTED_SOURCE_STRUCTURE,
    KIND_ATTRIBUTE,
    KIND_CLASS,
    KIND_CLASSIFICATION,
    KIND_ENDPOINT_ROLE,
    KIND_MATERIAL,
    KIND_PROPERTY,
    KIND_QUANTITY,
    KIND_RELATIONSHIP,
    KIND_STOREY,
    MANIFEST_SCHEMA_VERSION,
    NON_QUERYABLE_COVERAGE,
    ManifestConcept,
    SemanticManifest,
    parse_manifest,
)

__all__ = [
    "COVERAGE_ABSENT",
    "COVERAGE_EXTRACTION_FAILURE",
    "COVERAGE_PARTIAL",
    "COVERAGE_POPULATED",
    "COVERAGE_UNSUPPORTED",
    "COVERAGE_UNSUPPORTED_SOURCE_STRUCTURE",
    "KIND_ATTRIBUTE",
    "KIND_CLASS",
    "KIND_CLASSIFICATION",
    "KIND_ENDPOINT_ROLE",
    "KIND_MATERIAL",
    "KIND_PROPERTY",
    "KIND_QUANTITY",
    "KIND_RELATIONSHIP",
    "KIND_STOREY",
    "MANIFEST_SCHEMA_VERSION",
    "MANIFEST_SUFFIX",
    "NON_QUERYABLE_COVERAGE",
    "ManifestConcept",
    "ManifestStatus",
    "ManifestUnavailableError",
    "SemanticManifest",
    "clear_manifest_cache",
    "compute_manifest_status",
    "expected_manifest_path",
    "get_semantic_manifest",
    "is_contained",
    "manifest_dir",
    "parse_manifest",
]
