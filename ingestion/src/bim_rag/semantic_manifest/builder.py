"""Deterministic semantic-manifest builder (task25 §2.2).

Generates the complete semantic inventory for ONE source model from imported
canonical facts, relationship rows, and the IFC schema. No LLM, no embedding
model, no network call, and no inference of building facts from general model
knowledge: every record here is something the imported data actually says.

Relationship to the backend's capped vocabulary builder
------------------------------------------------------
The aggregation CONCEPTS are reused from
`backend/app/query/semantic/vocabulary/builder.py` — group observed values by
(class, field), count occurrences, derive coverage. The CAPS are not. §2.2
forbids reusing the prompt-oriented omission rules that builder needs, so this
module has none of them:

- no global fact cap (the backend's `_fair_trim` to 1,500);
- no per-profile value cap (20) and no per-field value cap (8);
- no minimum-occurrence threshold, so singletons survive;
- no `char_length BETWEEN 2 AND 40` filter on values;
- no wholesale rejection of a field for having "too many" distinct values —
  high-cardinality fields keep their concept and become `searchable` instead.

Only genuinely-correct noise filters are kept (GUID-shaped and `#step`-shaped
values, which are identity artifacts rather than semantic values), plus the
deterministic ordering.

Classification keys are read as written by ingestion (`system`/`code`/
`description`, see `ifc_parser.py`), which the backend builder does not do — it
reads `name`/`identification` and therefore silently yields nothing.
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from bim_rag.semantic_manifest.coverage import (
    ContainerShape,
    classify_container_structure,
    classify_field_coverage,
)
from bim_rag.semantic_manifest.schema import (
    COVERAGE_ABSENT,
    COVERAGE_EXTRACTION_FAILURE,
    COVERAGE_PARTIAL,
    COVERAGE_POPULATED,
    SECTION_GLOBAL,
    SECTION_OBJECT,
    SECTION_RELATIONSHIP,
    SECTION_TYPE_PROPERTY,
    build_document,
)

#: Above this many distinct values, a field keeps its CONCEPT (cardinality,
#: coverage, normalization, `searchable`) instead of enumerating every value.
#: The query-time high-recall stage performs exact authoritative lookup against
#: the database for a value the user actually names, so capability is preserved
#: without dumping occurrence data into the prompt (§2.2).
DEFAULT_MAX_ENUMERATED_VALUES = 200

#: Values that are identity artifacts, not semantic vocabulary.
_GUID_RE = re.compile(r"^[0-9A-Za-z_$]{22}$")
_STEP_RE = re.compile(r"^#\d+$")

#: Canonical-JSON attribute paths worth exposing as queryable field concepts.
#: A fixed literal list — never interpolated from user or model data.
_ATTRIBUTE_PATHS: tuple[tuple[str, tuple[str, ...], str], ...] = (
    ("name", ("identity", "name"), "text"),
    ("description", ("identity", "description"), "text"),
    ("object_type", ("identity", "object_type"), "text"),
    ("tag", ("identity", "tag"), "text"),
    ("long_name", ("identity", "long_name"), "text"),
    ("composition_type", ("identity", "composition_type"), "text"),
    ("predefined_type", ("meta", "predefined_type"), "text"),
    ("type_name", ("type", "name"), "text"),
    ("type_predefined_type", ("type", "predefined_type"), "text"),
    ("storey_name", ("storey", "name"), "text"),
)

_TEXT_OPERATORS = ("equals", "not_equals", "contains", "in", "is_null", "is_not_null")
_NUMERIC_OPERATORS = ("equals", "not_equals", "gt", "gte", "lt", "lte", "between", "is_null")
_BOOLEAN_OPERATORS = ("equals", "not_equals", "is_null")


def build_semantic_manifest(
    session: Session,
    source_model_id: int,
    *,
    max_enumerated_values: int = DEFAULT_MAX_ENUMERATED_VALUES,
    max_schema_ratio: float | None = None,
    min_distinct_fields: int | None = None,
) -> dict[str, Any]:
    """Build the complete manifest document for one already-imported model."""
    identity = _source_model_identity(session, source_model_id)

    class_counts = _entity_class_counts(session, source_model_id)
    structure = _classify_property_containers(
        session,
        source_model_id,
        max_schema_ratio=max_schema_ratio,
        min_distinct_fields=min_distinct_fields,
    )

    content = {
        SECTION_OBJECT: _build_object_level(
            session,
            source_model_id,
            class_counts,
            max_enumerated_values=max_enumerated_values,
        ),
        SECTION_TYPE_PROPERTY: _build_type_property_level(
            session,
            source_model_id,
            class_counts,
            structure,
            max_enumerated_values=max_enumerated_values,
        ),
        SECTION_RELATIONSHIP: _build_relationship_level(session, source_model_id),
        SECTION_GLOBAL: _build_global_level(session, source_model_id, class_counts, structure),
    }

    return build_document(
        source_model_id=source_model_id,
        file_fingerprint=identity["file_fingerprint"],
        file_name=identity["file_name"],
        ifc_schema=identity["ifc_schema"],
        extraction_version=identity["extraction_version"],
        content=content,
    )


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------


def _source_model_identity(session: Session, sid: int) -> dict[str, Any]:
    row = session.execute(
        text(
            "SELECT file_name, file_fingerprint, ifc_schema, extraction_metadata "
            "FROM ifc_source_models WHERE id = :id"
        ),
        {"id": sid},
    ).fetchone()
    if row is None:
        raise ValueError(f"source model {sid} does not exist")
    metadata = row[3] or {}
    return {
        "file_name": row[0],
        "file_fingerprint": row[1],
        "ifc_schema": row[2],
        "extraction_version": metadata.get("extraction_version", "unknown"),
    }


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _is_noise_value(value: str | None) -> bool:
    """Identity artifacts only.

    Deliberately far narrower than the backend builder's filter, which also
    drops values longer than 60 characters and any purely numeric string —
    both of which discard real semantic values such as numeric codes and fire
    ratings (§2.2 forbids that kind of omission).
    """
    if value is None:
        return True
    stripped = value.strip()
    if not stripped:
        return True
    return bool(_GUID_RE.match(stripped) or _STEP_RE.match(stripped))


def _entity_class_counts(session: Session, sid: int) -> dict[str, int]:
    rows = session.execute(
        text("SELECT ifc_class, count(*) FROM ifc_entities WHERE source_model_id = :id GROUP BY 1"),
        {"id": sid},
    ).fetchall()
    return {r[0]: int(r[1]) for r in rows}


def _operators_for(data_type: str) -> tuple[str, ...]:
    if data_type == "number":
        return _NUMERIC_OPERATORS
    if data_type == "boolean":
        return _BOOLEAN_OPERATORS
    return _TEXT_OPERATORS


def _infer_data_type(python_types: set[str], values: list[str]) -> str:
    """Map recorded Python type names / observed values onto a query data type."""
    if python_types & {"bool"}:
        return "boolean"
    if python_types and python_types <= {"int", "float"}:
        return "number"
    if values and all(_looks_numeric(v) for v in values):
        return "number"
    if values and all(v.strip().lower() in {"true", "false"} for v in values):
        return "boolean"
    return "text"


def _looks_numeric(value: str) -> bool:
    try:
        float(value.strip())
    except (TypeError, ValueError):
        return False
    return True


# ---------------------------------------------------------------------------
# Object level (§2.3.1)
# ---------------------------------------------------------------------------


def _build_object_level(
    session: Session,
    sid: int,
    class_counts: dict[str, int],
    *,
    max_enumerated_values: int = DEFAULT_MAX_ENUMERATED_VALUES,
) -> dict[str, Any]:
    """Every present occurrence class with its identity vocabulary.

    Free-text identity fields (`name`, `description`) are frequently
    high-cardinality; `_field_record` keeps their concept and marks them
    `searchable` rather than enumerating thousands of per-occurrence strings.
    """
    attribute_values = _attribute_values_by_class(session, sid)

    classes = []
    for ifc_class in sorted(class_counts):
        total = class_counts[ifc_class]
        attributes = []
        for attr_name, _path, declared_type in _ATTRIBUTE_PATHS:
            observed = attribute_values.get((ifc_class, attr_name))
            if observed is None:
                # The attribute is simply not carried by this class here. That
                # is an exact zero, and it is recorded rather than omitted so
                # the binder can tell "none" from "unknown".
                attributes.append(
                    {
                        "id": f"attr:{ifc_class}.{attr_name}",
                        "field": attr_name,
                        "data_type": declared_type,
                        "coverage": COVERAGE_ABSENT,
                        "populated_count": 0,
                        "total_count": total,
                    }
                )
                continue
            values, populated = observed
            attributes.append(
                _field_record(
                    semantic_id=f"attr:{ifc_class}.{attr_name}",
                    field=attr_name,
                    data_type=declared_type,
                    populated=populated,
                    total=total,
                    values=values,
                    max_enumerated_values=max_enumerated_values,
                )
            )

        classes.append(
            {
                "id": f"cls:{ifc_class}",
                "ifc_class": ifc_class,
                "count": total,
                "attributes": attributes,
            }
        )

    return {"classes": classes}


def _attribute_values_by_class(
    session: Session, sid: int
) -> dict[tuple[str, str], tuple[list[tuple[str, int]], int]]:
    """Observed values for every fixed attribute path, grouped by class.

    Emitted with NO per-class or per-value cap — this is the aggregation the
    backend builder performs under `vocab_max_values_per_profile`.
    """
    out: dict[tuple[str, str], tuple[list[tuple[str, int]], int]] = {}
    for attr_name, path, _declared in _ATTRIBUTE_PATHS:
        expr = "canonical_json" + "".join(f"->'{p}'" for p in path[:-1]) + f"->>'{path[-1]}'"
        rows = session.execute(
            text(
                f"SELECT ifc_class, {expr} AS v, count(*) AS n "  # noqa: S608 - fixed literal path
                "FROM ifc_entities WHERE source_model_id = :id "
                f"AND {expr} IS NOT NULL "
                "GROUP BY 1, 2 ORDER BY 1, 3 DESC, 2"
            ),
            {"id": sid},
        ).fetchall()
        for ifc_class, value, count in rows:
            if _is_noise_value(value):
                continue
            values, populated = out.setdefault((ifc_class, attr_name), ([], 0))
            values.append((value, int(count)))
            out[(ifc_class, attr_name)] = (values, populated + int(count))
    return out


def _field_record(
    *,
    semantic_id: str,
    field: str,
    data_type: str,
    populated: int,
    total: int,
    values: list[tuple[str, int]],
    set_name: str | None = None,
    max_enumerated_values: int = DEFAULT_MAX_ENUMERATED_VALUES,
) -> dict[str, Any]:
    """One queryable field concept, with its value vocabulary or search capability."""
    record: dict[str, Any] = {
        "id": semantic_id,
        "field": field,
        "data_type": data_type,
        "operators": list(_operators_for(data_type)),
        "coverage": classify_field_coverage(populated, total),
        "populated_count": populated,
        "total_count": total,
        "distinct_value_count": len(values),
    }
    if set_name is not None:
        record["set"] = set_name

    if len(values) > max_enumerated_values:
        # High cardinality: keep the CONCEPT and the capability, not the data.
        # §2.2 — the query-time stage looks a named value up authoritatively.
        record["searchable"] = True
        record["values_omitted_reason"] = (
            "high cardinality; exact values are resolved by authoritative lookup at query time"
        )
    else:
        record["values"] = [{"value": v, "count": c} for v, c in sorted(values, key=_value_sort)]
    return record


def _value_sort(item: tuple[str, int]) -> tuple[int, str]:
    """Most frequent first, then alphabetical — stable across runs."""
    value, count = item
    return (-count, value)


# ---------------------------------------------------------------------------
# Type / property level (§2.3.2)
# ---------------------------------------------------------------------------


def _classify_property_containers(
    session: Session,
    sid: int,
    *,
    max_schema_ratio: float | None,
    min_distinct_fields: int | None,
) -> dict[str, Any]:
    """Measure the shape of every property/quantity container in the model.

    Runs BEFORE any field or value query so that an unreliable container's
    fields are never fetched, never enumerated, and never offered to the binder.
    """
    kwargs: dict[str, Any] = {}
    if max_schema_ratio is not None:
        kwargs["max_schema_ratio"] = max_schema_ratio
    if min_distinct_fields is not None:
        kwargs["min_distinct_fields"] = min_distinct_fields

    result: dict[str, Any] = {"containers": {}, "unreliable": set(), "extraction_failures": {}}

    for top_key, kind in (("property_sets", "property"), ("quantity_sets", "quantity")):
        # `jsonb_each` over a non-object value raises, and extraction records a
        # STRING under `_extraction_error` when it fails — so failures are
        # counted separately and never walked as if they were containers.
        failures = session.execute(
            text(
                "SELECT count(*) FROM ifc_entities "
                "WHERE source_model_id = :id "
                f"AND canonical_json->'{top_key}' ? '_extraction_error'"  # noqa: S608
            ),
            {"id": sid},
        ).scalar()
        if failures:
            result["extraction_failures"][kind] = int(failures)

        rows = session.execute(
            text(
                "SELECT ps.key AS container, "
                "count(DISTINCT pr.key) AS distinct_fields, "
                "count(DISTINCT e.id) AS occurrences, "
                "count(*) AS field_instances "
                "FROM ifc_entities e, "
                f"jsonb_each(e.canonical_json->'{top_key}') ps, "  # noqa: S608 - fixed literal
                "jsonb_each(ps.value) pr "
                "WHERE e.source_model_id = :id AND jsonb_typeof(ps.value) = 'object' "
                "GROUP BY 1 ORDER BY 1"
            ),
            {"id": sid},
        ).fetchall()

        for container, distinct_fields, occurrences, field_instances in rows:
            shape = ContainerShape(
                container=container,
                distinct_field_count=int(distinct_fields),
                occurrence_count=int(occurrences),
                field_instance_count=int(field_instances),
            )
            verdict = classify_container_structure(shape, **kwargs)
            result["containers"][(kind, container)] = (shape, verdict)
            if not verdict.reliable:
                result["unreliable"].add((kind, container))

    return result


def _build_type_property_level(
    session: Session,
    sid: int,
    class_counts: dict[str, int],
    structure: dict[str, Any],
    *,
    max_enumerated_values: int,
) -> dict[str, Any]:
    """Property/quantity containers, materials, and classifications."""
    property_containers = _build_containers(
        session,
        sid,
        "property_sets",
        "property",
        class_counts,
        structure,
        max_enumerated_values=max_enumerated_values,
    )
    quantity_containers = _build_containers(
        session,
        sid,
        "quantity_sets",
        "quantity",
        class_counts,
        structure,
        max_enumerated_values=max_enumerated_values,
    )

    return {
        "property_containers": property_containers,
        "quantity_containers": quantity_containers,
        "materials": _build_materials(session, sid, class_counts),
        "classifications": _build_classifications(session, sid, class_counts),
    }


def _build_containers(
    session: Session,
    sid: int,
    top_key: str,
    kind: str,
    class_counts: dict[str, int],
    structure: dict[str, Any],
    *,
    max_enumerated_values: int,
) -> list[dict[str, Any]]:
    containers: list[dict[str, Any]] = []

    named = sorted(
        name for (container_kind, name) in structure["containers"] if container_kind == kind
    )
    unreliable_names = {
        name for (container_kind, name) in structure["unreliable"] if container_kind == kind
    }

    reliable_names = [n for n in named if n not in unreliable_names]
    # Each field's coverage denominator is its own container's reach: "of the
    # occurrences carrying this container, how many carry this field".
    container_occurrences = {
        name: structure["containers"][(kind, name)][0].occurrence_count for name in reliable_names
    }
    fields = (
        _container_fields(
            session,
            sid,
            top_key,
            reliable_names,
            container_occurrences,
            max_enumerated_values=max_enumerated_values,
        )
        if reliable_names
        else {}
    )
    applies = _container_classes(session, sid, top_key, named)

    for name in named:
        shape, verdict = structure["containers"][(kind, name)]
        record: dict[str, Any] = {
            "id": f"{kind}set:{name}",
            "container": name,
            "kind": kind,
            "applies_to": sorted(applies.get(name, [])),
            "occurrence_count": shape.occurrence_count,
            "distinct_field_count": shape.distinct_field_count,
            "coverage": verdict.coverage,
        }
        if verdict.reliable:
            record["fields"] = fields.get(name, [])
        else:
            # Bounded diagnostic ONLY. The field names are deliberately absent:
            # they are not reliably interpretable, so presenting them would
            # invite exactly the inference this state exists to prevent.
            record["structure_diagnostic"] = verdict.diagnostic
        containers.append(record)

    failures = structure["extraction_failures"].get(kind)
    if failures:
        containers.append(
            {
                "id": f"{kind}set:_extraction_failure",
                "container": None,
                "kind": kind,
                "coverage": COVERAGE_EXTRACTION_FAILURE,
                "affected_entity_count": failures,
                "reason": (
                    f"{kind} extraction raised for these entities during import; "
                    "their values are unknown rather than absent"
                ),
            }
        )
    return containers


def _container_classes(
    session: Session, sid: int, top_key: str, names: list[str]
) -> dict[str, list[str]]:
    if not names:
        return {}
    rows = session.execute(
        text(
            "SELECT DISTINCT ps.key, e.ifc_class FROM ifc_entities e, "
            f"jsonb_each(e.canonical_json->'{top_key}') ps "  # noqa: S608 - fixed literal
            "WHERE e.source_model_id = :id AND jsonb_typeof(ps.value) = 'object' "
            "AND ps.key = ANY(:names) ORDER BY 1, 2"
        ),
        {"id": sid, "names": names},
    ).fetchall()
    out: dict[str, list[str]] = {}
    for container, ifc_class in rows:
        out.setdefault(container, []).append(ifc_class)
    return out


def _container_fields(
    session: Session,
    sid: int,
    top_key: str,
    names: list[str],
    container_occurrences: dict[str, int],
    *,
    max_enumerated_values: int,
) -> dict[str, list[dict[str, Any]]]:
    """Every field in every RELIABLE container, with its full value vocabulary.

    No minimum-occurrence threshold and no per-field value cap: a value observed
    exactly once is still a real value someone may ask about.
    """
    occurrence_rows = session.execute(
        text(
            "SELECT ps.key, pr.key, count(DISTINCT e.id) "
            "FROM ifc_entities e, "
            f"jsonb_each(e.canonical_json->'{top_key}') ps, "  # noqa: S608 - fixed literal
            "jsonb_each(ps.value) pr "
            "WHERE e.source_model_id = :id AND jsonb_typeof(ps.value) = 'object' "
            "AND ps.key = ANY(:names) "
            "GROUP BY 1, 2 ORDER BY 1, 2"
        ),
        {"id": sid, "names": names},
    ).fetchall()
    populated: dict[tuple[str, str], int] = {(r[0], r[1]): int(r[2]) for r in occurrence_rows}

    value_rows = session.execute(
        text(
            "SELECT ps.key, pr.key, pr.value->>'value', pr.value->>'type', count(*) "
            "FROM ifc_entities e, "
            f"jsonb_each(e.canonical_json->'{top_key}') ps, "  # noqa: S608 - fixed literal
            "jsonb_each(ps.value) pr "
            "WHERE e.source_model_id = :id AND jsonb_typeof(ps.value) = 'object' "
            "AND ps.key = ANY(:names) "
            "GROUP BY 1, 2, 3, 4 ORDER BY 1, 2, 5 DESC, 3"
        ),
        {"id": sid, "names": names},
    ).fetchall()

    values: dict[tuple[str, str], list[tuple[str, int]]] = {}
    types: dict[tuple[str, str], set[str]] = {}
    for container, field, value, py_type, count in value_rows:
        key = (container, field)
        types.setdefault(key, set()).add(py_type or "")
        if _is_noise_value(value):
            continue
        values.setdefault(key, []).append((value, int(count)))

    out: dict[str, list[dict[str, Any]]] = {}
    for (container, field), populated_count in sorted(populated.items()):
        key = (container, field)
        field_values = values.get(key, [])
        data_type = _infer_data_type(types.get(key, set()), [v for v, _ in field_values])
        out.setdefault(container, []).append(
            _field_record(
                semantic_id=f"prop:{container}.{field}",
                field=field,
                set_name=container,
                data_type=data_type,
                populated=populated_count,
                total=container_occurrences.get(container, populated_count),
                values=field_values,
                max_enumerated_values=max_enumerated_values,
            )
        )
    return out


def _build_materials(
    session: Session, sid: int, class_counts: dict[str, int]
) -> list[dict[str, Any]]:
    rows = session.execute(
        text(
            "SELECT e.ifc_class, m->>'name', count(*) "
            "FROM ifc_entities e, jsonb_array_elements(e.canonical_json->'materials') m "
            "WHERE e.source_model_id = :id AND m->>'name' IS NOT NULL "
            "GROUP BY 1, 2 ORDER BY 1, 3 DESC, 2"
        ),
        {"id": sid},
    ).fetchall()
    grouped: dict[str, list[tuple[str, int]]] = {}
    for ifc_class, value, count in rows:
        if _is_noise_value(value):
            continue
        grouped.setdefault(ifc_class, []).append((value, int(count)))

    out = []
    for ifc_class in sorted(class_counts):
        values = grouped.get(ifc_class, [])
        out.append(
            {
                "id": f"mat:{ifc_class}",
                "ifc_class": ifc_class,
                "coverage": COVERAGE_POPULATED if values else COVERAGE_ABSENT,
                "materials": [{"value": v, "count": c} for v, c in values],
            }
        )
    return [r for r in out if r["materials"] or r["coverage"] == COVERAGE_ABSENT]


def _build_classifications(
    session: Session, sid: int, class_counts: dict[str, int]
) -> list[dict[str, Any]]:
    """Classification references, read with the keys ingestion actually writes.

    `ifc_parser.py` writes `{system, code, description}`. Reading `name` or
    `identification` — as the backend's vocabulary builder does — silently
    yields nothing for every model.
    """
    rows = session.execute(
        text(
            "SELECT e.ifc_class, c->>'system', c->>'code', c->>'description', count(*) "
            "FROM ifc_entities e, jsonb_array_elements(e.canonical_json->'classifications') c "
            "WHERE e.source_model_id = :id GROUP BY 1, 2, 3, 4 ORDER BY 1, 5 DESC, 2, 3"
        ),
        {"id": sid},
    ).fetchall()

    grouped: dict[str, list[dict[str, Any]]] = {}
    for ifc_class, system, code, description, count in rows:
        if _is_noise_value(code) and _is_noise_value(description):
            continue
        grouped.setdefault(ifc_class, []).append(
            {
                "system": system,
                "code": code,
                "description": description,
                "count": int(count),
            }
        )

    out = []
    for ifc_class in sorted(grouped):
        out.append(
            {
                "id": f"cla:{ifc_class}",
                "ifc_class": ifc_class,
                "coverage": COVERAGE_POPULATED,
                "references": grouped[ifc_class],
            }
        )
    return out


# ---------------------------------------------------------------------------
# System / relationship level (§2.3.3)
# ---------------------------------------------------------------------------


def _build_relationship_level(session: Session, sid: int) -> dict[str, Any]:
    counts = session.execute(
        text(
            "SELECT ifc_class, count(*) FROM ifc_relationships "
            "WHERE source_model_id = :id GROUP BY 1 ORDER BY 1"
        ),
        {"id": sid},
    ).fetchall()

    endpoints = session.execute(
        text(
            "SELECT r.ifc_class, rm.role, rm.endpoint_ifc_class, count(*), "
            "count(*) FILTER (WHERE rm.entity_id IS NOT NULL) "
            "FROM ifc_relationships r "
            "JOIN relationship_members rm ON rm.relationship_id = r.id "
            "WHERE r.source_model_id = :id "
            "GROUP BY 1, 2, 3 ORDER BY 1, 2, 4 DESC, 3"
        ),
        {"id": sid},
    ).fetchall()

    by_class: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for rel_class, role, endpoint_class, total, resolved in endpoints:
        by_class.setdefault(rel_class, {}).setdefault(role, []).append(
            {
                "endpoint_ifc_class": endpoint_class,
                "count": int(total),
                "resolved_count": int(resolved),
            }
        )

    classes = []
    for rel_class, count in counts:
        roles = by_class.get(rel_class, {})
        classes.append(
            {
                "id": f"rel:{rel_class}",
                "ifc_class": rel_class,
                "count": int(count),
                "coverage": COVERAGE_POPULATED if roles else COVERAGE_ABSENT,
                "endpoint_roles": [
                    {
                        "id": f"rel:{rel_class}:{role}",
                        "role": role,
                        "endpoints": endpoint_classes,
                    }
                    for role, endpoint_classes in sorted(roles.items())
                ],
            }
        )

    return {"relationship_classes": classes}


# ---------------------------------------------------------------------------
# Global level (§2.3.4)
# ---------------------------------------------------------------------------


def _build_global_level(
    session: Session,
    sid: int,
    class_counts: dict[str, int],
    structure: dict[str, Any],
) -> dict[str, Any]:
    storeys = session.execute(
        text(
            "SELECT canonical_json->'identity'->>'name', global_id, "
            "canonical_json->'placement'->>'elevation' "
            "FROM ifc_entities WHERE source_model_id = :id "
            "AND ifc_class = 'IfcBuildingStorey' "
            "ORDER BY (canonical_json->'placement'->>'elevation')::numeric NULLS LAST, 1"
        ),
        {"id": sid},
    ).fetchall()

    contained = session.execute(
        text(
            "SELECT count(DISTINCT e.id) FROM ifc_entities e "
            "WHERE e.source_model_id = :id AND e.canonical_json->'storey'->>'global_id' IS NOT NULL"
        ),
        {"id": sid},
    ).scalar()

    total_entities = sum(class_counts.values())
    missing = _missing_capabilities(structure, class_counts)

    return {
        "entity_total": total_entities,
        "class_inventory": [
            {"ifc_class": name, "count": count} for name, count in sorted(class_counts.items())
        ],
        "storeys": [
            {
                "id": f"storey:{global_id}",
                "name": name,
                "global_id": global_id,
                "elevation": _as_float(elevation),
            }
            for name, global_id, elevation in storeys
        ],
        "spatial_containment": {
            "entities_assigned_to_a_storey": int(contained or 0),
            "coverage": (
                COVERAGE_POPULATED
                if contained and contained >= total_entities
                else COVERAGE_PARTIAL
                if contained
                else COVERAGE_ABSENT
            ),
        },
        "missing_capabilities": missing,
    }


def _as_float(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _missing_capabilities(
    structure: dict[str, Any], class_counts: dict[str, int]
) -> list[dict[str, Any]]:
    """What this model genuinely cannot answer, and why (§2.2, §2.3.4).

    Stated positively and boundedly so the final answer can say what the IFC
    does not determine, rather than the pipeline silently returning a broader
    result.
    """
    missing: list[dict[str, Any]] = []

    for (kind, container), (shape, verdict) in sorted(structure["containers"].items()):
        if verdict.reliable:
            continue
        missing.append(
            {
                "capability": f"{kind}_queries",
                "scope": container,
                "coverage": verdict.coverage,
                "affected_field_count": shape.distinct_field_count,
                "affected_occurrence_count": shape.occurrence_count,
                "reason": verdict.diagnostic["reason"] if verdict.diagnostic else None,
            }
        )

    for kind, count in sorted(structure["extraction_failures"].items()):
        missing.append(
            {
                "capability": f"{kind}_queries",
                "scope": None,
                "coverage": COVERAGE_EXTRACTION_FAILURE,
                "affected_occurrence_count": count,
                "reason": f"{kind} extraction raised for these entities during import",
            }
        )

    reliable_property_containers = [
        name
        for (kind, name), (_shape, verdict) in structure["containers"].items()
        if kind == "property" and verdict.reliable
    ]
    if not reliable_property_containers:
        missing.append(
            {
                "capability": "property_queries",
                "scope": None,
                "coverage": COVERAGE_ABSENT,
                "reason": (
                    "this model exposes no property container with a reliably "
                    "interpretable field schema, so property-based filtering is "
                    "not available for it"
                ),
            }
        )

    reliable_quantity_containers = [
        name
        for (kind, name), (_shape, verdict) in structure["containers"].items()
        if kind == "quantity" and verdict.reliable
    ]
    if not reliable_quantity_containers:
        missing.append(
            {
                "capability": "quantity_queries",
                "scope": None,
                "coverage": COVERAGE_ABSENT,
                "reason": (
                    "no quantity set was extracted for this model, so measured "
                    "quantities such as areas and volumes are not available"
                ),
            }
        )

    return missing
