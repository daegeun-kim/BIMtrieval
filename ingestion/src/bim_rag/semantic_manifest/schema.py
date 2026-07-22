"""Versioned schema for the ingestion-generated semantic manifest (task25 §2).

The manifest is a COMPLETE inventory of the unique queryable concepts in one
source model — classes, representations, relationships, operations, value
vocabularies, and coverage states. It is deliberately NOT a copy of every IFC
row: individual GUIDs and full occurrence records stay in PostgreSQL and the
existing RAG documents until a bound query retrieves them (§2.2).

Serialization is canonical so that the same IFC and the same builder/schema
versions always produce byte-identical content and therefore an identical
content hash (§2.1). Every collection is emitted in a deterministic order and
every mapping is key-sorted; no timestamp, path, or other environment-dependent
value participates in the hashed content.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

#: Bump when the document STRUCTURE changes (readers key their cache on it).
MANIFEST_SCHEMA_VERSION = "v001"

#: Bump when the builder changes what it EXTRACTS without changing structure.
MANIFEST_BUILDER_VERSION = "v001"

#: File suffix for a generated artifact.
MANIFEST_SUFFIX = ".semantic.json"


# ---------------------------------------------------------------------------
# Coverage vocabulary (§2.2)
# ---------------------------------------------------------------------------

#: The field/relationship concept is present and populated on every occurrence.
COVERAGE_POPULATED = "populated"
#: Present, but populated on only some occurrences.
COVERAGE_PARTIAL = "partial"
#: The concept exists in the schema/ontology but no occurrence carries a value.
#: This is an EXACT ZERO, and must stay distinguishable from the states below.
COVERAGE_ABSENT = "absent"
#: The concept is not supported by this extraction pipeline at all.
COVERAGE_UNSUPPORTED = "unsupported"
#: Extraction was attempted for this concept and raised.
COVERAGE_EXTRACTION_FAILURE = "extraction_failure"
#: The SOURCE DATA does not present this concept in a reliably interpretable
#: structure, so its fields cannot be resolved as queryable properties.
#:
#: This is the honest terminal state for a container whose contents cannot be
#: trusted — see `coverage.py`. It is NOT a licence to guess: the manifest
#: describes the limitation and stops. "Concept-complete" applies to reliably
#: interpretable source data; an unsupported source structure is COMPLETELY
#: represented by its limitation state (task25 owner decision).
COVERAGE_UNSUPPORTED_SOURCE_STRUCTURE = "unsupported_source_structure"

COVERAGE_STATES = frozenset(
    {
        COVERAGE_POPULATED,
        COVERAGE_PARTIAL,
        COVERAGE_ABSENT,
        COVERAGE_UNSUPPORTED,
        COVERAGE_EXTRACTION_FAILURE,
        COVERAGE_UNSUPPORTED_SOURCE_STRUCTURE,
    }
)

#: Coverage states under which a concept must NOT be treated as queryable.
#: A question that needs such a concept answers `unavailable` and says why —
#: it never silently falls back to a broader set (§5).
NON_QUERYABLE_COVERAGE = frozenset(
    {
        COVERAGE_UNSUPPORTED,
        COVERAGE_EXTRACTION_FAILURE,
        COVERAGE_UNSUPPORTED_SOURCE_STRUCTURE,
    }
)


# ---------------------------------------------------------------------------
# The four conceptual representations (§2.3)
# ---------------------------------------------------------------------------

#: Exactly four. Do NOT add a fifth (and specifically not a logical-floor
#: level): storeys, elevations, containment, and floor relationships flow
#: through the spatial/relationship/global semantics instead (§2.3).
SECTION_OBJECT = "object_level"
SECTION_TYPE_PROPERTY = "type_property_level"
SECTION_RELATIONSHIP = "relationship_level"
SECTION_GLOBAL = "global_level"

REQUIRED_SECTIONS = (
    SECTION_OBJECT,
    SECTION_TYPE_PROPERTY,
    SECTION_RELATIONSHIP,
    SECTION_GLOBAL,
)


class ManifestValidationError(RuntimeError):
    """The assembled manifest violated a structural invariant."""


# ---------------------------------------------------------------------------
# Canonical serialization + content hash
# ---------------------------------------------------------------------------


def canonical_json(payload: Any) -> str:
    """Serialize deterministically: sorted keys, compact separators, UTF-8.

    `ensure_ascii=False` keeps non-ASCII labels (Dutch and Swedish model data
    both occur here) readable rather than escaped, which materially reduces
    token count for the binder prompt (§2.4).
    """
    return json.dumps(
        payload,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )


def compute_content_hash(content: dict[str, Any]) -> str:
    """SHA-256 over the canonical semantic content.

    The caller passes the `content` block only — never `identity`, which
    carries the hash itself and generation metadata. Two runs over the same IFC
    with the same versions must agree here (§2.1).
    """
    return hashlib.sha256(canonical_json(content).encode("utf-8")).hexdigest()


def build_document(
    *,
    source_model_id: int,
    file_fingerprint: str,
    file_name: str,
    ifc_schema: str | None,
    extraction_version: str,
    content: dict[str, Any],
) -> dict[str, Any]:
    """Assemble the final artifact: identity block + hashed semantic content."""
    return {
        "identity": {
            "source_model_id": int(source_model_id),
            "file_fingerprint": file_fingerprint,
            "file_name": file_name,
            "ifc_schema": ifc_schema,
            "extraction_version": extraction_version,
            "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
            "builder_version": MANIFEST_BUILDER_VERSION,
            "content_hash": compute_content_hash(content),
        },
        "content": content,
    }


def validate_document(document: dict[str, Any]) -> list[str]:
    """Structural validation. Returns problems; empty means valid (§2.1).

    Run against the in-memory document BEFORE the atomic replace, so a corrupt
    artifact never reaches the final path.
    """
    problems: list[str] = []

    identity = document.get("identity")
    content = document.get("content")
    if not isinstance(identity, dict):
        return ["manifest is missing its identity block"]
    if not isinstance(content, dict):
        return ["manifest is missing its content block"]

    for field in (
        "source_model_id",
        "file_fingerprint",
        "extraction_version",
        "manifest_schema_version",
        "builder_version",
        "content_hash",
    ):
        if identity.get(field) in (None, ""):
            problems.append(f"identity.{field} is missing")

    if identity.get("manifest_schema_version") != MANIFEST_SCHEMA_VERSION:
        problems.append(
            f"identity.manifest_schema_version {identity.get('manifest_schema_version')!r} "
            f"!= builder's {MANIFEST_SCHEMA_VERSION!r}"
        )

    # The hash must describe the content actually present, or a stale artifact
    # could masquerade as current.
    expected = compute_content_hash(content)
    if identity.get("content_hash") != expected:
        problems.append("identity.content_hash does not match the serialized content")

    for section in REQUIRED_SECTIONS:
        if section not in content:
            problems.append(f"content.{section} is missing")

    problems.extend(_validate_coverage_states(content))
    problems.extend(_validate_semantic_ids(content))
    return problems


def _validate_coverage_states(content: dict[str, Any]) -> list[str]:
    """Every `coverage` value must come from the typed vocabulary."""
    problems: list[str] = []
    for path, value in _walk(content, "content"):
        if path.endswith(".coverage") and value not in COVERAGE_STATES:
            problems.append(f"{path} has unknown coverage state {value!r}")
    return problems


def _validate_semantic_ids(content: dict[str, Any]) -> list[str]:
    """Semantic IDs must be unique across the whole manifest.

    The binder selects records BY id (§3.3), so a collision would silently bind
    the wrong concept.
    """
    seen: dict[str, str] = {}
    problems: list[str] = []
    for path, value in _walk(content, "content"):
        if not path.endswith(".id") or not isinstance(value, str):
            continue
        if value in seen:
            problems.append(f"duplicate semantic id {value!r} at {path} and {seen[value]}")
        else:
            seen[value] = path
    return problems


def _walk(node: Any, path: str):
    """Yield (dotted_path, scalar) for every leaf, for structural assertions."""
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _walk(value, f"{path}.{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _walk(value, f"{path}[{index}]")
    else:
        yield path, node


def estimate_tokens(document: dict[str, Any]) -> int:
    """Conservative token estimate for the serialized manifest (§2.1, §2.4).

    Deliberately pessimistic: compact JSON of mostly identifier-like text runs
    near 3 characters per token, so dividing by 3 over-estimates rather than
    under-estimates. This feeds the soft-target check, where over-estimating is
    the safe direction.
    """
    return len(canonical_json(document).encode("utf-8")) // 3
