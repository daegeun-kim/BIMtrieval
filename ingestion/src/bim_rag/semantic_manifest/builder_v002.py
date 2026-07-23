"""Deterministic semantic-manifest v002 builder (task26 §5).

One normalized capability namespace instead of four duplicated views. Every
capability records, per subject class, how many subjects are eligible and how
many actually carry the fact — the association v001 lost by unioning
`applies_to` across a container (§1.3). Materials and classifications are
ordinary executable field capabilities. Relationship role pairs become typed
traversal contracts. Raw storeys and derived occupiable floor bands are both
present and distinct.

Everything is measured from the imported rows of ONE model; no LLM, no
network, no model-specific rule. Deterministic ordering throughout so the
content hash is stable.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from bim_rag.contract import load_access_contract, operators_for
from bim_rag.semantic_manifest.builder import (
    _ATTRIBUTE_PATHS,
    _infer_data_type,
    _is_noise_value,
    _source_model_identity,
)
from bim_rag.semantic_manifest.coverage import ContainerShape, classify_container_structure
from bim_rag.semantic_manifest.floors import derive_floors
from bim_rag.semantic_manifest.schema_v002 import build_document_v002

#: Every stored value up to this many distinct values is fully enumerated in
#: the machine artifact; beyond it the capability keeps request-time lookup.
ENUMERATED_VALUE_LIMIT = 8

#: Diagnostic example values retained per capability (most frequent first).
EXAMPLE_VALUE_LIMIT = 8

#: Reversible exporter-wrapper key syntax: `[Namespace]Field`. The namespace
#: match is GREEDY (up to the last `]`), mirroring the SQL parse, so a
#: namespace may itself contain a bracketed qualifier (`ArchiCADQuantities[...]`).
_WRAPPER_KEY_RE = re.compile(r"^\[(?P<ns>.*)\](?P<field>.+)$")

_MAX_ID_LENGTH = 120


def _bounded_id(raw: str) -> str:
    """Stable semantic id within the contract's length limit."""
    if len(raw) <= _MAX_ID_LENGTH:
        return raw
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:8]
    return f"{raw[: _MAX_ID_LENGTH - 9]}~{digest}"


def _split_identifier(identifier: str) -> str:
    if not identifier:
        return ""
    out: list[str] = []
    for index, char in enumerate(identifier):
        if char in "_-.":
            out.append(" ")
            continue
        if char.isupper() and index and not identifier[index - 1].isupper():
            out.append(" ")
        out.append(char)
    return " ".join("".join(out).split())


def _aliases(*labels: str) -> list[str]:
    seen: list[str] = []
    for label in labels:
        for candidate in (label, _split_identifier(label)):
            lowered = candidate.strip().casefold()
            if lowered and lowered not in seen:
                seen.append(lowered)
            if lowered.startswith("ifc "):
                trimmed = lowered[4:]
                if trimmed and trimmed not in seen:
                    seen.append(trimmed)
    return seen[:6]


def _coverage_state(known: int, eligible: int) -> str:
    if eligible <= 0 or known <= 0:
        return "checked_absent"
    if known >= eligible:
        return "present_complete"
    return "present_partial"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def build_semantic_manifest_v002(session: Session, source_model_id: int) -> dict[str, Any]:
    identity = _source_model_identity(session, source_model_id)
    load_access_contract()  # fail fast if the contract is unreadable

    class_counts = _class_counts(session, source_model_id)
    capabilities: list[dict[str, Any]] = []

    capabilities.extend(_class_capabilities(class_counts))
    capabilities.extend(_attribute_capabilities(session, source_model_id, class_counts))
    capabilities.extend(_field_capabilities(session, source_model_id, class_counts))
    capabilities.extend(_material_capabilities(session, source_model_id, class_counts))
    capabilities.extend(_classification_capabilities(session, source_model_id, class_counts))

    membership_summary = _spatial_membership_summary(session, source_model_id, class_counts)
    capabilities.append(_spatial_capability(membership_summary))

    capabilities.sort(key=lambda c: c["id"])

    content = {
        "entity_total": sum(class_counts.values()),
        "class_inventory": [
            {"ifc_class": name, "count": count} for name, count in sorted(class_counts.items())
        ],
        "capabilities": capabilities,
        "traversals": _traversal_contracts(session, source_model_id),
        "derived_floors": derive_floors(session, source_model_id),
        "profiles": _profiles(),
        "spatial_membership": membership_summary,
        "storeys": _storeys(session, source_model_id),
    }

    return build_document_v002(
        source_model_id=source_model_id,
        file_fingerprint=identity["file_fingerprint"],
        file_name=identity["file_name"],
        ifc_schema=identity["ifc_schema"],
        extraction_version=identity["extraction_version"],
        content=content,
    )


def _class_counts(session: Session, sid: int) -> dict[str, int]:
    rows = session.execute(
        text("SELECT ifc_class, count(*) FROM ifc_entities WHERE source_model_id = :id GROUP BY 1"),
        {"id": sid},
    ).fetchall()
    return {r[0]: int(r[1]) for r in rows}


# ---------------------------------------------------------------------------
# Class capabilities
# ---------------------------------------------------------------------------


def _class_capabilities(class_counts: dict[str, int]) -> list[dict[str, Any]]:
    out = []
    for ifc_class in sorted(class_counts):
        count = class_counts[ifc_class]
        out.append(
            {
                "id": f"cls:{ifc_class}",
                "kind": "class",
                "label": _split_identifier(ifc_class),
                "aliases": _aliases(ifc_class),
                "grain": "entity",
                "uses": ["target", "topic_context"],
                "accessor": "entity.class",
                "executable": True,
                "applicability": [
                    {
                        "subject": f"cls:{ifc_class}",
                        "coverage": "present_complete",
                        "known_count": count,
                        "eligible_count": count,
                        "can_prove_absence": True,
                    }
                ],
                "value_policy": "none",
                "provenance": [f"ifc_entities.ifc_class={ifc_class}"],
            }
        )
    return out


# ---------------------------------------------------------------------------
# Attribute capabilities (one per attribute, applicability per class)
# ---------------------------------------------------------------------------


def _attribute_capabilities(
    session: Session, sid: int, class_counts: dict[str, int]
) -> list[dict[str, Any]]:
    out = []
    for attr_name, path, declared_type in _ATTRIBUTE_PATHS:
        expr = "canonical_json" + "".join(f"->'{p}'" for p in path[:-1]) + f"->>'{path[-1]}'"
        per_class = session.execute(
            text(
                f"SELECT ifc_class, count(*) FILTER (WHERE {expr} IS NOT NULL), count(*) "  # noqa: S608
                "FROM ifc_entities WHERE source_model_id = :id GROUP BY 1 ORDER BY 1"
            ),
            {"id": sid},
        ).fetchall()
        values = session.execute(
            text(
                "SELECT v, n FROM ("
                f"SELECT {expr} AS v, count(*) AS n, "  # noqa: S608 - fixed literal path
                f"row_number() OVER (ORDER BY count(*) DESC, {expr}) AS rn "  # noqa: S608
                "FROM ifc_entities WHERE source_model_id = :id "
                f"AND {expr} IS NOT NULL GROUP BY 1) x WHERE rn <= :cap ORDER BY n DESC, v"
            ),
            {"id": sid, "cap": EXAMPLE_VALUE_LIMIT + 24},
        ).fetchall()
        distinct = session.execute(
            text(
                f"SELECT count(DISTINCT {expr}) FROM ifc_entities "  # noqa: S608
                f"WHERE source_model_id = :id AND {expr} IS NOT NULL"
            ),
            {"id": sid},
        ).scalar()

        applicability = [
            {
                "subject": f"cls:{ifc_class}",
                "coverage": _coverage_state(int(known), int(total)),
                "known_count": int(known),
                "eligible_count": int(total),
                "can_prove_absence": True,
            }
            for ifc_class, known, total in per_class
            if int(known) > 0
        ]
        if not applicability:
            continue

        clean_values = [(v, int(n)) for v, n in values if not _is_noise_value(v)][
            :EXAMPLE_VALUE_LIMIT
        ]
        out.append(
            _field_capability_record(
                semantic_id=f"attr:{attr_name}",
                label=_split_identifier(attr_name),
                aliases=_aliases(attr_name),
                data_type=declared_type,
                distinct_count=int(distinct or 0),
                example_values=clean_values,
                applicability=applicability,
                accessor="json.attribute",
                provenance=[f"canonical_json.{'.'.join(path)}"],
                unit_state="not_applicable",
                unit=None,
                physical={
                    "source": "type_fact" if attr_name.startswith("type_") else "attribute",
                    "field": attr_name,
                    "path": list(path),
                },
            )
        )
    return out


def _field_capability_record(
    *,
    semantic_id: str,
    label: str,
    aliases: list[str],
    data_type: str,
    distinct_count: int,
    example_values: list[tuple[str, int]],
    applicability: list[dict[str, Any]],
    accessor: str,
    provenance: list[str],
    unit_state: str,
    unit: str | None,
    physical: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """One executable field capability with contract-legal uses/operators."""
    if data_type == "number":
        if unit_state in ("known", "unitless"):
            uses = ["filter", "group", "report", "order", "aggregate"]
            operators = operators_for("number")
        else:
            # Numeric with an unproven unit contract: presence/grouping/reporting
            # stay executable; comparison and aggregation do not (§4.3).
            uses = ["filter", "group", "report"]
            operators = ["is_present", "is_missing"]
    elif data_type == "boolean":
        uses = ["filter", "group", "report"]
        operators = operators_for("boolean")
    else:
        uses = ["filter", "group", "report"]
        operators = operators_for("text")

    for entry in applicability:
        entry.setdefault("unit_state", unit_state)
        if unit:
            entry.setdefault("unit", unit)
        entry.setdefault("distinct_value_count", distinct_count)

    record = {
        "id": _bounded_id(semantic_id),
        "kind": "field",
        "label": label,
        "aliases": aliases,
        "grain": "entity",
        "uses": uses,
        "data_type": data_type,
        "operators": operators,
        "accessor": accessor,
        "executable": True,
        "applicability": applicability,
        "value_policy": (
            "enumerated"
            if 0 < distinct_count <= ENUMERATED_VALUE_LIMIT and data_type != "number"
            else "request_lookup"
        ),
        "values": [{"value": v, "count": n} for v, n in example_values],
        "provenance": provenance,
    }
    if physical is not None:
        # Backend-only structured addressing (machine artifact, never in the
        # binder projection): where the fact physically lives, with the RAW
        # container/field keys so wrapper-derived fields stay addressable.
        record["physical"] = physical
    return record


# ---------------------------------------------------------------------------
# Property / quantity field capabilities
# ---------------------------------------------------------------------------


def _field_capabilities(
    session: Session, sid: int, class_counts: dict[str, int]
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for top_key, prefix in (("property_sets", "prop"), ("quantity_sets", "qty")):
        out.extend(_container_field_capabilities(session, sid, top_key, prefix, class_counts))
    return out


def _container_shapes(
    session: Session, sid: int, top_key: str
) -> dict[str, ContainerShape]:
    rows = session.execute(
        text(
            "SELECT ps.key, count(DISTINCT pr.key), count(DISTINCT e.id), count(*) "
            "FROM ifc_entities e, "
            f"jsonb_each(e.canonical_json->'{top_key}') ps, "  # noqa: S608 - fixed literal
            "jsonb_each(ps.value) pr "
            "WHERE e.source_model_id = :id AND jsonb_typeof(ps.value) = 'object' "
            "GROUP BY 1 ORDER BY 1"
        ),
        {"id": sid},
    ).fetchall()
    return {
        r[0]: ContainerShape(
            container=r[0],
            distinct_field_count=int(r[1]),
            occurrence_count=int(r[2]),
            field_instance_count=int(r[3]),
        )
        for r in rows
    }


def _container_field_capabilities(
    session: Session,
    sid: int,
    top_key: str,
    prefix: str,
    class_counts: dict[str, int],
) -> list[dict[str, Any]]:
    shapes = _container_shapes(session, sid, top_key)
    if not shapes:
        return []

    reliable = [n for n, s in shapes.items() if classify_container_structure(s).reliable]
    unreliable = [n for n in shapes if n not in reliable]

    out: list[dict[str, Any]] = []
    if reliable:
        out.extend(
            _fields_for_containers(
                session, sid, top_key, prefix, reliable, class_counts, wrapper=None
            )
        )
    for wrapper in unreliable:
        out.extend(
            _wrapper_capabilities(session, sid, top_key, prefix, wrapper, class_counts, shapes)
        )

    failures = session.execute(
        text(
            "SELECT count(*) FROM ifc_entities WHERE source_model_id = :id "
            f"AND canonical_json->'{top_key}' ? '_extraction_error'"  # noqa: S608
        ),
        {"id": sid},
    ).scalar()
    if failures:
        out.append(
            {
                "id": f"{prefix}:_extraction_failure",
                "kind": "field",
                "label": f"{top_key} extraction failure",
                "aliases": [],
                "grain": "entity",
                "uses": [],
                "accessor": "json.property_value",
                "executable": False,
                "limitation": (
                    f"{top_key} extraction raised for {int(failures)} entities during import; "
                    "their values are unknown rather than absent"
                ),
                "applicability": [
                    {
                        "subject": "cls:*",
                        "coverage": "extraction_failed",
                        "known_count": 0,
                        "eligible_count": int(failures),
                        "can_prove_absence": False,
                    }
                ],
                "value_policy": "none",
                "values": [],
                "provenance": [f"canonical_json.{top_key}._extraction_error"],
            }
        )
    return out


def _fields_for_containers(
    session: Session,
    sid: int,
    top_key: str,
    prefix: str,
    containers: list[str],
    class_counts: dict[str, int],
    *,
    wrapper: str | None,
    allowed_namespaces: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Field capabilities for a list of RELIABLE containers.

    When `wrapper` is set, `containers` are DERIVED namespaces inside that
    wrapper and the physical key is `[namespace]field` inside the wrapper
    container; provenance always records the true physical path.
    """
    per_class = session.execute(
        text(
            "SELECT ps.key, pr.key, e.ifc_class, count(DISTINCT e.id) "
            "FROM ifc_entities e, "
            f"jsonb_each(e.canonical_json->'{top_key}') ps, "  # noqa: S608 - fixed literal
            "jsonb_each(ps.value) pr "
            "WHERE e.source_model_id = :id AND jsonb_typeof(ps.value) = 'object' "
            + ("AND ps.key = :wrapper " if wrapper else "AND ps.key = ANY(:names) ")
            + "GROUP BY 1, 2, 3 ORDER BY 1, 2, 3"
        ),
        {"id": sid, "names": containers, "wrapper": wrapper},
    ).fetchall()

    stats = session.execute(
        text(
            "SELECT ps.key, pr.key, "
            "count(DISTINCT pr.value->>'value') AS distinct_values, "
            "array_agg(DISTINCT pr.value->>'type') AS py_types, "
            "count(*) FILTER (WHERE jsonb_typeof(pr.value->'value') = 'number') AS numeric_n, "
            "count(*) FILTER (WHERE pr.value->>'unit_state' = 'known') AS unit_known_n, "
            "count(*) FILTER (WHERE pr.value->>'unit_state' = 'unitless') AS unitless_n, "
            "array_agg(DISTINCT pr.value->>'normalized_unit') "
            "  FILTER (WHERE pr.value->>'normalized_unit' IS NOT NULL) AS units, "
            "count(*) AS n "
            "FROM ifc_entities e, "
            f"jsonb_each(e.canonical_json->'{top_key}') ps, "  # noqa: S608 - fixed literal
            "jsonb_each(ps.value) pr "
            "WHERE e.source_model_id = :id AND jsonb_typeof(ps.value) = 'object' "
            + ("AND ps.key = :wrapper " if wrapper else "AND ps.key = ANY(:names) ")
            + "GROUP BY 1, 2 ORDER BY 1, 2"
        ),
        {"id": sid, "names": containers, "wrapper": wrapper},
    ).fetchall()

    examples = session.execute(
        text(
            "SELECT container, field, v, n FROM ("
            "SELECT ps.key AS container, pr.key AS field, pr.value->>'value' AS v, "
            "count(*) AS n, "
            "row_number() OVER (PARTITION BY ps.key, pr.key ORDER BY count(*) DESC, "
            "pr.value->>'value') AS rn "
            "FROM ifc_entities e, "
            f"jsonb_each(e.canonical_json->'{top_key}') ps, "  # noqa: S608 - fixed literal
            "jsonb_each(ps.value) pr "
            "WHERE e.source_model_id = :id AND jsonb_typeof(ps.value) = 'object' "
            + ("AND ps.key = :wrapper " if wrapper else "AND ps.key = ANY(:names) ")
            + "AND pr.value->>'value' IS NOT NULL "
            "GROUP BY 1, 2, 3) x WHERE rn <= :cap ORDER BY 1, 2, 4 DESC, 3"
        ),
        {"id": sid, "names": containers, "wrapper": wrapper, "cap": EXAMPLE_VALUE_LIMIT + 24},
    ).fetchall()

    applicability_map: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for container, raw_field, ifc_class, known in per_class:
        key = _resolve_key(container, raw_field, wrapper)
        if key is None:
            continue
        applicability_map.setdefault(key, []).append(
            {
                "subject": f"cls:{ifc_class}",
                "coverage": _coverage_state(int(known), class_counts.get(ifc_class, 0)),
                "known_count": int(known),
                "eligible_count": class_counts.get(ifc_class, 0),
                "can_prove_absence": True,
            }
        )

    examples_map: dict[tuple[str, str], list[tuple[str, int]]] = {}
    for container, raw_field, value, count in examples:
        key = _resolve_key(container, raw_field, wrapper)
        if key is None or _is_noise_value(value):
            continue
        bucket = examples_map.setdefault(key, [])
        if len(bucket) < EXAMPLE_VALUE_LIMIT:
            bucket.append((value, int(count)))

    out: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for row in stats:
        container, raw_field = row[0], row[1]
        key = _resolve_key(container, raw_field, wrapper)
        if key is None:
            continue
        namespace, field_name = key
        if allowed_namespaces is not None and namespace not in allowed_namespaces:
            continue
        applicability = applicability_map.get(key, [])
        if not applicability:
            continue

        py_types = {t for t in (row[3] or []) if t}
        example_values = examples_map.get(key, [])
        data_type = _infer_data_type(py_types, [v for v, _ in example_values])
        numeric_n, unit_known_n, unitless_n = int(row[4]), int(row[5]), int(row[6])
        units = [u for u in (row[7] or []) if u]
        if data_type == "number":
            if numeric_n and unitless_n == numeric_n:
                unit_state, unit = "unitless", None
            elif numeric_n and unit_known_n == numeric_n and len(units) == 1:
                unit_state, unit = "known", units[0]
            else:
                unit_state, unit = "unknown", None
        else:
            unit_state, unit = "not_applicable", None

        if wrapper:
            semantic_id = f"{prefix}:{wrapper}[{namespace}].{field_name}"
            label = f"{namespace}.{field_name}"
            provenance = [f"canonical_json.{top_key}.{wrapper}.{raw_field}"]
        else:
            semantic_id = f"{prefix}:{namespace}.{field_name}"
            label = f"{namespace}.{field_name}"
            provenance = [f"canonical_json.{top_key}.{namespace}.{field_name}"]

        record = _field_capability_record(
            semantic_id=semantic_id,
            label=label,
            aliases=_aliases(field_name, f"{namespace} {field_name}"),
            data_type=data_type,
            distinct_count=int(row[2]),
            example_values=example_values,
            applicability=applicability,
            accessor="json.property_value" if prefix == "prop" else "json.quantity_value",
            provenance=provenance,
            unit_state=unit_state,
            unit=unit,
            physical={
                "source": top_key,
                "set": container,
                "field": raw_field,
            },
        )
        if record["id"] not in seen_ids:
            seen_ids.add(record["id"])
            out.append(record)
    return out


def _resolve_key(
    container: str, raw_field: str, wrapper: str | None
) -> tuple[str, str] | None:
    """(namespace, field) for one physical key, or None when unparseable."""
    if wrapper is None:
        return (container, raw_field)
    match = _WRAPPER_KEY_RE.match(raw_field)
    if match is None:
        return None
    return (match.group("ns"), match.group("field"))


def _wrapper_capabilities(
    session: Session,
    sid: int,
    top_key: str,
    prefix: str,
    wrapper: str,
    class_counts: dict[str, int],
    shapes: dict[str, ContainerShape],
) -> list[dict[str, Any]]:
    """Segment one structurally unreliable container by its reversible
    namespace syntax (§4.4). Parseable namespaces with a stable field schema
    become ordinary capabilities; the remainder stays honestly unavailable."""
    # Proper namespace shapes: distinct ENTITIES carrying each namespace, not a
    # per-key proxy — a per-instance schedule bag must not look schema-stable.
    ns_rows = session.execute(
        text(
            r"SELECT substring(pr.key from '^\[(.*)\]') AS ns, "
            "count(DISTINCT pr.key) AS fields, "
            "count(DISTINCT e.id) AS entities, "
            "count(*) AS instances "
            "FROM ifc_entities e, "
            f"jsonb_each(e.canonical_json->'{top_key}') ps, "  # noqa: S608 - fixed literal
            "jsonb_each(ps.value) pr "
            "WHERE e.source_model_id = :id AND ps.key = :wrapper "
            "GROUP BY 1"
        ),
        {"id": sid, "wrapper": wrapper},
    ).fetchall()

    reliable_namespaces: list[str] = []
    unparsed_keys = 0
    for namespace, fields, entities, instances in ns_rows:
        if namespace is None:
            unparsed_keys += int(fields)
            continue
        shape = ContainerShape(
            container=namespace,
            distinct_field_count=int(fields),
            occurrence_count=int(entities),
            field_instance_count=int(instances),
        )
        if classify_container_structure(shape).reliable:
            reliable_namespaces.append(namespace)
        else:
            unparsed_keys += int(fields)

    out: list[dict[str, Any]] = []
    if reliable_namespaces:
        out.extend(
            _fields_for_containers(
                session,
                sid,
                top_key,
                prefix,
                [],
                class_counts,
                wrapper=wrapper,
                allowed_namespaces=set(reliable_namespaces),
            )
        )

    if unparsed_keys:
        shape = shapes[wrapper]
        out.append(
            {
                "id": _bounded_id(f"{prefix}:{wrapper}.__unresolvable__"),
                "kind": "field",
                "label": f"{wrapper} (unresolvable subset)",
                "aliases": _aliases(wrapper),
                "grain": "entity",
                "uses": [],
                "accessor": "json.property_value",
                "executable": False,
                "limitation": (
                    f"{unparsed_keys} field names in the {wrapper} container do not follow a "
                    "reversible namespace structure, so their meaning cannot be resolved "
                    "without inference; they are reported as unavailable rather than guessed"
                ),
                "applicability": [
                    {
                        "subject": "cls:*",
                        "coverage": "source_unresolvable",
                        "known_count": 0,
                        "eligible_count": shape.occurrence_count,
                        "can_prove_absence": False,
                    }
                ],
                "value_policy": "none",
                "values": [],
                "provenance": [f"canonical_json.{top_key}.{wrapper}"],
            }
        )
    return out


# ---------------------------------------------------------------------------
# Materials / classifications as ordinary fields (§5.3)
# ---------------------------------------------------------------------------


def _material_capabilities(
    session: Session, sid: int, class_counts: dict[str, int]
) -> list[dict[str, Any]]:
    per_class = session.execute(
        text(
            "SELECT e.ifc_class, count(DISTINCT e.id) "
            "FROM ifc_entities e, jsonb_array_elements(e.canonical_json->'materials') m "
            "WHERE e.source_model_id = :id AND m->>'name' IS NOT NULL "
            "GROUP BY 1 ORDER BY 1"
        ),
        {"id": sid},
    ).fetchall()
    if not per_class:
        return []
    values = session.execute(
        text(
            "SELECT v, n FROM ("
            "SELECT m->>'name' AS v, count(*) AS n, "
            "row_number() OVER (ORDER BY count(*) DESC, m->>'name') AS rn "
            "FROM ifc_entities e, jsonb_array_elements(e.canonical_json->'materials') m "
            "WHERE e.source_model_id = :id AND m->>'name' IS NOT NULL "
            "GROUP BY 1) x WHERE rn <= :cap ORDER BY n DESC, v"
        ),
        {"id": sid, "cap": EXAMPLE_VALUE_LIMIT + 24},
    ).fetchall()
    distinct = session.execute(
        text(
            "SELECT count(DISTINCT m->>'name') FROM ifc_entities e, "
            "jsonb_array_elements(e.canonical_json->'materials') m "
            "WHERE e.source_model_id = :id"
        ),
        {"id": sid},
    ).scalar()

    applicability = [
        {
            "subject": f"cls:{ifc_class}",
            "coverage": _coverage_state(int(known), class_counts.get(ifc_class, 0)),
            "known_count": int(known),
            "eligible_count": class_counts.get(ifc_class, 0),
            "can_prove_absence": True,
        }
        for ifc_class, known in per_class
    ]
    clean = [(v, int(n)) for v, n in values if not _is_noise_value(v)][:EXAMPLE_VALUE_LIMIT]
    return [
        _field_capability_record(
            semantic_id="mat:material.name",
            label="material",
            aliases=["material", "materials", "made of", "material name"],
            data_type="text",
            distinct_count=int(distinct or 0),
            example_values=clean,
            applicability=applicability,
            accessor="json.material_name",
            provenance=["canonical_json.materials[].name"],
            unit_state="not_applicable",
            unit=None,
            physical={"source": "materials", "field": "name"},
        )
    ]


_CLASSIFICATION_FIELDS = (
    ("system", "classification system"),
    ("code", "classification code"),
    ("description", "classification description"),
)


def _classification_capabilities(
    session: Session, sid: int, class_counts: dict[str, int]
) -> list[dict[str, Any]]:
    out = []
    for field_key, label in _CLASSIFICATION_FIELDS:
        per_class = session.execute(
            text(
                "SELECT e.ifc_class, count(DISTINCT e.id) "
                "FROM ifc_entities e, jsonb_array_elements(e.canonical_json->'classifications') c "
                f"WHERE e.source_model_id = :id AND c->>'{field_key}' IS NOT NULL "  # noqa: S608
                "GROUP BY 1 ORDER BY 1"
            ),
            {"id": sid},
        ).fetchall()
        if not per_class:
            continue
        values = session.execute(
            text(
                "SELECT v, n FROM ("
                f"SELECT c->>'{field_key}' AS v, count(*) AS n, "  # noqa: S608 - fixed literal
                f"row_number() OVER (ORDER BY count(*) DESC, c->>'{field_key}') AS rn "  # noqa: S608
                "FROM ifc_entities e, jsonb_array_elements(e.canonical_json->'classifications') c "
                f"WHERE e.source_model_id = :id AND c->>'{field_key}' IS NOT NULL "  # noqa: S608
                "GROUP BY 1) x WHERE rn <= :cap ORDER BY n DESC, v"
            ),
            {"id": sid, "cap": EXAMPLE_VALUE_LIMIT + 24},
        ).fetchall()
        distinct = session.execute(
            text(
                f"SELECT count(DISTINCT c->>'{field_key}') FROM ifc_entities e, "  # noqa: S608
                "jsonb_array_elements(e.canonical_json->'classifications') c "
                "WHERE e.source_model_id = :id"
            ),
            {"id": sid},
        ).scalar()

        applicability = [
            {
                "subject": f"cls:{ifc_class}",
                "coverage": _coverage_state(int(known), class_counts.get(ifc_class, 0)),
                "known_count": int(known),
                "eligible_count": class_counts.get(ifc_class, 0),
                "can_prove_absence": True,
            }
            for ifc_class, known in per_class
        ]
        clean = [(v, int(n)) for v, n in values if not _is_noise_value(v)][:EXAMPLE_VALUE_LIMIT]
        out.append(
            _field_capability_record(
                semantic_id=f"cla:classification.{field_key}",
                label=label,
                aliases=_aliases(label, field_key),
                data_type="text",
                distinct_count=int(distinct or 0),
                example_values=clean,
                applicability=applicability,
                accessor="json.classification_field",
                provenance=[f"canonical_json.classifications[].{field_key}"],
                unit_state="not_applicable",
                unit=None,
                physical={"source": "classifications", "field": field_key},
            )
        )
    return out


# ---------------------------------------------------------------------------
# Spatial membership summary + capability (§4.2, §10.2)
# ---------------------------------------------------------------------------


def _spatial_membership_summary(
    session: Session, sid: int, class_counts: dict[str, int]
) -> dict[str, Any]:
    rows = session.execute(
        text(
            "SELECT e.ifc_class, "
            "count(*) FILTER (WHERE e.canonical_json->'storey'->>'global_id' IS NOT NULL) "
            "  AS direct_count, "
            "count(*) FILTER (WHERE EXISTS (SELECT 1 FROM entity_spatial_memberships m "
            "  WHERE m.source_model_id = e.source_model_id AND m.entity_id = e.id)) "
            "  AS membership_count, "
            "count(*) FILTER (WHERE e.canonical_json->'storey'->>'global_id' IS NOT NULL "
            "  OR EXISTS (SELECT 1 FROM entity_spatial_memberships m "
            "  WHERE m.source_model_id = e.source_model_id AND m.entity_id = e.id)) "
            "  AS effective_count, "
            "count(*) AS total_count "
            "FROM ifc_entities e WHERE e.source_model_id = :id "
            "GROUP BY 1 ORDER BY 1"
        ),
        {"id": sid},
    ).fetchall()
    return {
        "by_class": [
            {
                "ifc_class": r[0],
                "direct_count": int(r[1]),
                "aggregated_count": int(r[2]),
                "effective_count": int(r[3]),
                "total_count": int(r[4]),
            }
            for r in rows
        ]
    }


def _spatial_capability(summary: dict[str, Any]) -> dict[str, Any]:
    applicability = [
        {
            "subject": f"cls:{entry['ifc_class']}",
            "coverage": _coverage_state(entry["effective_count"], entry["total_count"]),
            "known_count": entry["effective_count"],
            "eligible_count": entry["total_count"],
            "can_prove_absence": entry["effective_count"] >= entry["total_count"],
        }
        for entry in summary["by_class"]
        if entry["effective_count"] > 0
    ]
    return {
        "id": "spatial:floor_membership",
        "kind": "spatial",
        "label": "storey / floor membership",
        "aliases": ["floor", "storey", "story", "level", "on the floor", "per floor"],
        "grain": "entity",
        "uses": ["scope", "group"],
        "accessor": "spatial.effective_membership",
        "executable": bool(applicability),
        "limitation": None if applicability else "no entity resolves to a storey in this model",
        "applicability": applicability,
        "value_policy": "none",
        "values": [],
        "provenance": [
            "entity_spatial_memberships",
            "canonical_json.storey.global_id",
        ],
    }


# ---------------------------------------------------------------------------
# Traversal contracts (§5.4)
# ---------------------------------------------------------------------------


def _traversal_contracts(session: Session, sid: int) -> list[dict[str, Any]]:
    rows = session.execute(
        text(
            "SELECT r.ifc_class, rm.role, rm.endpoint_ifc_class, count(*), "
            "count(*) FILTER (WHERE rm.entity_id IS NOT NULL) "
            "FROM ifc_relationships r "
            "JOIN relationship_members rm ON rm.relationship_id = r.id "
            "WHERE r.source_model_id = :id AND rm.endpoint_ifc_class IS NOT NULL "
            "GROUP BY 1, 2, 3 ORDER BY 1, 2, 3"
        ),
        {"id": sid},
    ).fetchall()
    counts = session.execute(
        text(
            "SELECT ifc_class, count(*) FROM ifc_relationships "
            "WHERE source_model_id = :id GROUP BY 1"
        ),
        {"id": sid},
    ).fetchall()
    rel_counts = {r[0]: int(r[1]) for r in counts}

    by_role: dict[str, dict[str, dict[str, Any]]] = {}
    for rel_class, role, endpoint_class, total, resolved in rows:
        role_entry = by_role.setdefault(rel_class, {}).setdefault(
            role, {"classes": [], "count": 0, "resolved": 0}
        )
        role_entry["classes"].append(endpoint_class)
        role_entry["count"] += int(total)
        role_entry["resolved"] += int(resolved)

    out: list[dict[str, Any]] = []
    for rel_class in sorted(by_role):
        roles = by_role[rel_class]
        relating = sorted(r for r in roles if r.startswith("Relating"))
        related = sorted(r for r in roles if r.startswith("Related"))
        for from_role in relating:
            for to_role in related:
                pairs = (
                    (from_role, to_role, "outgoing"),
                    (to_role, from_role, "incoming"),
                )
                for source_role, target_role, direction in pairs:
                    source = roles[source_role]
                    target = roles[target_role]
                    out.append(
                        {
                            "id": _bounded_id(f"path:{rel_class}.{source_role}->{target_role}"),
                            "kind": "traversal",
                            "relationship": rel_class,
                            "label": (
                                f"{_split_identifier(rel_class)} "
                                f"{_split_identifier(source_role)} to "
                                f"{_split_identifier(target_role)}"
                            ),
                            "aliases": _aliases(rel_class),
                            "from_role": source_role,
                            "to_role": target_role,
                            "direction": direction,
                            "from_classes": sorted(set(source["classes"])),
                            "to_classes": sorted(set(target["classes"])),
                            "relationship_count": rel_counts.get(rel_class, 0),
                            "resolved_from_count": source["resolved"],
                            "resolved_to_count": target["resolved"],
                            "endpoint_fact_resolvable": target["count"] > 0,
                            "endpoint_entity_resolvable": target["resolved"] > 0,
                            "endpoint_viewer_hydratable": target["resolved"] > 0,
                            "accessor": "relationship.member_edge",
                            "max_supported_hops": 1,
                        }
                    )
    return out


# ---------------------------------------------------------------------------
# Profiles + storeys
# ---------------------------------------------------------------------------


def _profiles() -> list[dict[str, Any]]:
    return [
        {
            "id": "derived:building_profile",
            "kind": "derived_profile",
            "label": "building profile",
            "aliases": ["summary", "overview", "describe the building", "what is in this model"],
            "accessor": "derived.building_profile",
            "uses": ["target"],
        },
        {
            "id": "derived:thematic_profile",
            "kind": "derived_profile",
            "label": "thematic profile",
            "aliases": ["circulation", "envelope", "theme", "aspect"],
            "accessor": "derived.thematic_profile",
            "uses": ["target"],
        },
    ]


def _storeys(session: Session, sid: int) -> list[dict[str, Any]]:
    rows = session.execute(
        text(
            "SELECT global_id, canonical_json->'identity'->>'name', "
            "canonical_json->'placement'->>'elevation' "
            "FROM ifc_entities WHERE source_model_id = :id "
            "AND ifc_class = 'IfcBuildingStorey' "
            "ORDER BY (canonical_json->'placement'->>'elevation')::numeric NULLS LAST, global_id"
        ),
        {"id": sid},
    ).fetchall()
    out = []
    for global_id, name, elevation in rows:
        try:
            value: float | None = float(elevation)
        except (TypeError, ValueError):
            value = None
        out.append(
            {"id": f"storey:{global_id}", "global_id": global_id, "name": name, "elevation": value}
        )
    return out
