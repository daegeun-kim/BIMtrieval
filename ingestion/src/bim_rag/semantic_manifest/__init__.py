"""Ingestion-owned semantic manifest generation (task25 §2).

One deterministic, LLM-free JSON artifact per source model, describing every
queryable concept that model actually contains — and, just as importantly, the
concepts it cannot reliably answer.

Public API::

    from bim_rag.semantic_manifest import generate_manifest
    stats = generate_manifest(session, source_model_id, root)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from bim_rag.semantic_manifest.builder import build_semantic_manifest
from bim_rag.semantic_manifest.coverage import (
    ContainerShape,
    StructureVerdict,
    classify_container_structure,
    classify_field_coverage,
)
from bim_rag.semantic_manifest.measurement import (
    MeasureFacts,
    UnitRegistryView,
    build_measure_facts,
)
from bim_rag.semantic_manifest.schema import (
    COVERAGE_STATES,
    MANIFEST_BUILDER_VERSION,
    MANIFEST_SCHEMA_VERSION,
    MANIFEST_SUFFIX,
    NON_QUERYABLE_COVERAGE,
    UNIT_STATE_MIXED,
    UNIT_STATE_UNIFORM,
    UNIT_STATE_UNKNOWN,
    UNIT_STATES,
    ManifestValidationError,
    canonical_json,
    compute_content_hash,
    estimate_tokens,
    validate_document,
)
from bim_rag.semantic_manifest.writer import (
    manifest_dir,
    manifest_path,
    read_manifest,
    write_manifest,
)

__all__ = [
    "COVERAGE_STATES",
    "MANIFEST_BUILDER_VERSION",
    "MANIFEST_SCHEMA_VERSION",
    "MANIFEST_SUFFIX",
    "NON_QUERYABLE_COVERAGE",
    "UNIT_STATES",
    "UNIT_STATE_MIXED",
    "UNIT_STATE_UNIFORM",
    "UNIT_STATE_UNKNOWN",
    "ContainerShape",
    "ManifestValidationError",
    "MeasureFacts",
    "StructureVerdict",
    "UnitRegistryView",
    "build_measure_facts",
    "build_semantic_manifest",
    "canonical_json",
    "classify_container_structure",
    "classify_field_coverage",
    "compute_content_hash",
    "estimate_tokens",
    "generate_manifest",
    "manifest_dir",
    "manifest_path",
    "read_manifest",
    "validate_document",
    "write_manifest",
]


def generate_manifest(
    session: Session,
    source_model_id: int,
    root: Path,
    **builder_kwargs: Any,
) -> dict[str, Any]:
    """Build, validate, and atomically publish one model's semantic manifest.

    This is the single production entrypoint. `ifc_to_db()` calls it, and the
    one-time backfill calls it — there is deliberately no second implementation
    and no separate ingestion path (§2.1, §8).
    """
    document = build_semantic_manifest(session, source_model_id, **builder_kwargs)
    stats = write_manifest(document, root)
    stats.update(_record_counts(document))
    return stats


def _record_counts(document: dict[str, Any]) -> dict[str, Any]:
    """Bounded semantic-record metrics for the ingestion report (§2.1)."""
    content = document["content"]
    obj = content["object_level"]
    types = content["type_property_level"]
    rels = content["relationship_level"]
    glob = content["global_level"]

    property_fields = sum(len(c.get("fields", [])) for c in types.get("property_containers", []))
    quantity_fields = sum(len(c.get("fields", [])) for c in types.get("quantity_containers", []))
    attribute_fields = sum(len(c.get("attributes", [])) for c in obj.get("classes", []))
    measurement_fields = sum(len(c.get("measurements", [])) for c in obj.get("classes", []))

    unsupported = [
        c
        for c in types.get("property_containers", []) + types.get("quantity_containers", [])
        if "structure_diagnostic" in c
    ]

    unit_states = _unit_state_counts(document)

    return {
        "class_count": len(obj.get("classes", [])),
        "attribute_field_count": attribute_fields,
        "measurement_field_count": measurement_fields,
        "uniform_unit_field_count": unit_states.get(UNIT_STATE_UNIFORM, 0),
        "mixed_unit_field_count": unit_states.get(UNIT_STATE_MIXED, 0),
        "unknown_unit_field_count": unit_states.get(UNIT_STATE_UNKNOWN, 0),
        "dimension_default_units": {
            measure_type: _default_symbol(document, measure_type)
            for measure_type in ("length", "area", "volume")
        },
        "property_container_count": len(types.get("property_containers", [])),
        "property_field_count": property_fields,
        "quantity_container_count": len(types.get("quantity_containers", [])),
        "quantity_field_count": quantity_fields,
        "material_record_count": len(types.get("materials", [])),
        "classification_record_count": len(types.get("classifications", [])),
        "relationship_class_count": len(rels.get("relationship_classes", [])),
        "storey_count": len(glob.get("storeys", [])),
        "missing_capability_count": len(glob.get("missing_capabilities", [])),
        "unsupported_structure_count": len(unsupported),
        "semantic_record_count": (
            len(obj.get("classes", []))
            + attribute_fields
            + measurement_fields
            + property_fields
            + quantity_fields
            + len(types.get("materials", []))
            + len(types.get("classifications", []))
            + len(rels.get("relationship_classes", []))
            + len(glob.get("storeys", []))
        ),
    }


def _unit_state_counts(document: dict[str, Any]) -> dict[str, int]:
    """How many field records sit in each unit state (task27 §3, §5)."""
    counts: dict[str, int] = {}
    for record in _iter_records(document["content"]):
        state = record.get("unit_state")
        if isinstance(state, str):
            counts[state] = counts.get(state, 0) + 1
    return counts


def _default_symbol(document: dict[str, Any], measure_type: str) -> str | None:
    """The model's own default unit symbol for one family, or None if unresolved."""
    units = document["content"]["global_level"].get("dimension_units") or {}
    key = (units.get("defaults") or {}).get(measure_type)
    definition = (units.get("definitions") or {}).get(key) if key else None
    if not definition or not definition.get("resolved", True):
        return None
    return definition.get("symbol")


def _iter_records(node: Any):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _iter_records(value)
    elif isinstance(node, list):
        for value in node:
            yield from _iter_records(value)
