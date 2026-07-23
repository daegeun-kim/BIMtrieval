"""Manifest v002 schema constants and validation (task26 §5).

v002 replaces the four duplicated conceptual views with ONE normalized
capability namespace, applicability per subject class, traversal contracts,
derived floors, and profiles. Canonical serialization and hashing are shared
with v001 (`schema.canonical_json` / `compute_content_hash`).

Validation here is structural AND contract-aware: every executable capability
must name an accessor the access contract declares, with uses/operators the
contract permits. That is the ingestion half of the bidirectional completeness
check (§3.3); the backend half asserts every declared accessor has a compiler
adapter.
"""

from __future__ import annotations

from typing import Any

from bim_rag.contract import ACCESS_CONTRACT_VERSION, load_access_contract
from bim_rag.semantic_manifest.schema import (
    ManifestValidationError,
    compute_content_hash,
)

MANIFEST_SCHEMA_VERSION_V002 = "v002"
MANIFEST_BUILDER_VERSION_V002 = "v002"
MANIFEST_SUFFIX_V002 = ".semantic.v002.json"

#: Contract coverage states (differ from the v001 vocabulary by design).
COVERAGE_STATES_V002 = frozenset(
    {
        "present_complete",
        "present_partial",
        "checked_absent",
        "source_unresolvable",
        "extractor_unsupported",
        "extraction_failed",
    }
)

NON_QUERYABLE_COVERAGE_V002 = frozenset(
    {"source_unresolvable", "extractor_unsupported", "extraction_failed"}
)

_REQUIRED_CONTENT_KEYS = (
    "entity_total",
    "class_inventory",
    "capabilities",
    "traversals",
    "derived_floors",
    "profiles",
    "spatial_membership",
    "storeys",
)


def build_document_v002(
    *,
    source_model_id: int,
    file_fingerprint: str,
    file_name: str,
    ifc_schema: str | None,
    extraction_version: str,
    content: dict[str, Any],
) -> dict[str, Any]:
    return {
        "identity": {
            "source_model_id": int(source_model_id),
            "file_fingerprint": file_fingerprint,
            "file_name": file_name,
            "ifc_schema": ifc_schema,
            "extraction_version": extraction_version,
            "manifest_schema_version": MANIFEST_SCHEMA_VERSION_V002,
            "builder_version": MANIFEST_BUILDER_VERSION_V002,
            "contract_version": ACCESS_CONTRACT_VERSION,
            "content_hash": compute_content_hash(content),
        },
        "content": content,
    }


def validate_document_v002(document: dict[str, Any]) -> list[str]:
    """Structural + contract validation. Returns problems; empty means valid."""
    problems: list[str] = []
    identity = document.get("identity")
    content = document.get("content")
    if not isinstance(identity, dict):
        return ["manifest is missing its identity block"]
    if not isinstance(content, dict):
        return ["manifest is missing its content block"]

    for key in (
        "source_model_id",
        "file_fingerprint",
        "extraction_version",
        "manifest_schema_version",
        "builder_version",
        "contract_version",
        "content_hash",
    ):
        if identity.get(key) in (None, ""):
            problems.append(f"identity.{key} is missing")

    if identity.get("manifest_schema_version") != MANIFEST_SCHEMA_VERSION_V002:
        problems.append(
            f"identity.manifest_schema_version {identity.get('manifest_schema_version')!r} "
            f"!= {MANIFEST_SCHEMA_VERSION_V002!r}"
        )
    if identity.get("content_hash") != compute_content_hash(content):
        problems.append("identity.content_hash does not match the serialized content")

    for key in _REQUIRED_CONTENT_KEYS:
        if key not in content:
            problems.append(f"content.{key} is missing")
    if problems:
        return problems

    try:
        contract = load_access_contract(identity.get("contract_version", ACCESS_CONTRACT_VERSION))
    except Exception as exc:  # noqa: BLE001 - reported as a validation problem
        return [f"access contract could not be loaded: {exc}"]

    accessors = contract["accessors"]
    legal_uses = set(contract["uses"])
    max_id = int(contract["id_rules"]["max_semantic_id_length"])
    operators_by_type = contract["operators_by_data_type"]

    seen_ids: dict[str, str] = {}

    def _check_id(semantic_id: Any, where: str) -> None:
        if not isinstance(semantic_id, str) or not semantic_id:
            problems.append(f"{where}: missing semantic id")
            return
        if len(semantic_id) > max_id:
            problems.append(f"{where}: id {semantic_id!r} exceeds {max_id} chars")
        if semantic_id in seen_ids:
            problems.append(f"duplicate semantic id {semantic_id!r} ({where} and {seen_ids[semantic_id]})")
        else:
            seen_ids[semantic_id] = where

    for capability in content["capabilities"]:
        cid = capability.get("id")
        _check_id(cid, "capabilities")
        accessor = capability.get("accessor")
        executable = capability.get("executable", False)
        uses = capability.get("uses", [])
        if not set(uses) <= legal_uses:
            problems.append(f"capability {cid}: illegal uses {sorted(set(uses) - legal_uses)}")
        if executable:
            declaration = accessors.get(accessor)
            if declaration is None:
                problems.append(f"capability {cid}: executable but accessor {accessor!r} undeclared")
                continue
            if not uses:
                problems.append(f"capability {cid}: executable but has no uses")
            if not set(uses) <= set(declaration["uses"]):
                problems.append(
                    f"capability {cid}: uses {sorted(set(uses) - set(declaration['uses']))} "
                    f"not permitted by accessor {accessor}"
                )
            data_type = capability.get("data_type")
            if data_type:
                legal_ops = set(operators_by_type.get(data_type, ()))
                declared_ops = set(capability.get("operators", ()))
                if not declared_ops <= legal_ops:
                    problems.append(
                        f"capability {cid}: operators {sorted(declared_ops - legal_ops)} "
                        f"illegal for {data_type}"
                    )
            if not capability.get("applicability"):
                problems.append(f"capability {cid}: executable but has no applicability")
        else:
            if not capability.get("limitation"):
                problems.append(f"capability {cid}: non-executable without a limitation reason")

        for entry in capability.get("applicability", ()):
            state = entry.get("coverage")
            if state not in COVERAGE_STATES_V002:
                problems.append(f"capability {cid}: unknown coverage state {state!r}")

    for traversal in content["traversals"]:
        _check_id(traversal.get("id"), "traversals")
        if traversal.get("accessor") != "relationship.member_edge":
            problems.append(f"traversal {traversal.get('id')}: illegal accessor")
        if traversal.get("direction") not in ("outgoing", "incoming"):
            problems.append(f"traversal {traversal.get('id')}: illegal direction")

    for profile in content["profiles"]:
        _check_id(profile.get("id"), "profiles")
        if profile.get("accessor") not in ("derived.building_profile", "derived.thematic_profile"):
            problems.append(f"profile {profile.get('id')}: illegal accessor")

    for band in content["derived_floors"].get("bands", ()):
        _check_id(band.get("id"), "derived_floors")
        if band.get("classification") not in ("occupiable", "non_occupiable_reference", "uncertain"):
            problems.append(f"band {band.get('id')}: illegal classification")

    return problems


__all__ = [
    "MANIFEST_SCHEMA_VERSION_V002",
    "MANIFEST_BUILDER_VERSION_V002",
    "MANIFEST_SUFFIX_V002",
    "COVERAGE_STATES_V002",
    "NON_QUERYABLE_COVERAGE_V002",
    "ManifestValidationError",
    "build_document_v002",
    "validate_document_v002",
]
