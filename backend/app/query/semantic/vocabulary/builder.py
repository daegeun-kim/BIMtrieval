"""Deterministic, bounded, read-only model-vocabulary builder (Task 16 §3).

Every query here is a read-only aggregate scoped to one `source_model_id`. No
statement writes BIM tables or stored corpus vectors, and no full canonical JSON
leaves this module — only bounded, provenance-tagged summaries. Ordering is
stable (class, count desc, value) so profiles are reproducible; per-instance
singleton noise is dropped from value facts, and GUID/STEP/opaque/numeric values
are excluded.

The builder is versioned (`PROFILE_BUILDER_VERSION`); the cache key includes it
so a builder change invalidates cached vocabularies (Task 16 §3 cache key).
"""

from __future__ import annotations

import re

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config.settings import Settings, get_settings
from app.query.semantic.vocabulary.profiles import (
    ClassProfile,
    ModelVocabulary,
    ObservedFactProfile,
    QuantityCoverageProfile,
    QueryableRef,
)

PROFILE_BUILDER_VERSION = "v001"
EXTRACTION_VERSION = "v001"

_NAME_SUFFIX_RE = re.compile(r"_\(#\d+\)$")
_GUID22_RE = re.compile(r"^[0-9A-Za-z_$]{22}$")
_UUID_RE = re.compile(r"^[0-9A-Fa-f-]{32,36}$")
_NUMERIC_RE = re.compile(r"^[0-9.,\-\s]+$")


def normalize_name_stem(name: str | None) -> str | None:
    """Strip a trailing exporter suffix `_(#755216)` to expose a recurring stem
    while the original name remains available elsewhere (Task 16 §3)."""
    if not name:
        return None
    return _NAME_SUFFIX_RE.sub("", name).strip() or None


def _is_noise_value(value: str | None) -> bool:
    if value is None:
        return True
    v = value.strip()
    if not v or len(v) > 60:
        return True
    if v.startswith("#"):
        return True
    if _GUID22_RE.match(v) or _UUID_RE.match(v):
        return True
    if _NUMERIC_RE.match(v):
        return True
    return False


def _top_per_group(rows: list[tuple], key_index: int, cap: int) -> list[tuple]:
    """Keep at most `cap` rows per group key, assuming `rows` are already ordered
    by (key, count desc, value)."""
    return _top_per_composite(rows, (key_index,), cap)


def _top_per_composite(rows: list[tuple], key_indices: tuple[int, ...], cap: int) -> list[tuple]:
    """Keep at most `cap` rows per composite group key, assuming `rows` are
    already ordered so that within each group the kept rows come first."""
    out: list[tuple] = []
    counts: dict = {}
    for r in rows:
        k = tuple(r[i] for i in key_indices)
        if counts.get(k, 0) >= cap:
            continue
        counts[k] = counts.get(k, 0) + 1
        out.append(r)
    return out


def build_model_vocabulary(
    session: Session, source_model_id: int, settings: Settings | None = None
) -> ModelVocabulary:
    settings = settings or get_settings()
    cap = settings.vocab_max_values_per_profile
    min_occ = settings.vocab_min_fact_occurrences

    meta = session.execute(
        text("SELECT file_fingerprint, ifc_schema FROM ifc_source_models WHERE id = :id"),
        {"id": source_model_id},
    ).first()
    if meta is None:
        raise ValueError(f"source_model_id {source_model_id} does not exist")
    fingerprint, ifc_schema = meta[0], meta[1]

    vocab = ModelVocabulary(
        source_model_id=source_model_id,
        file_fingerprint=fingerprint,
        extraction_version=EXTRACTION_VERSION,
        profile_builder_version=PROFILE_BUILDER_VERSION,
        ifc_schema=ifc_schema,
    )

    class_counts = _entity_class_counts(session, source_model_id)
    rel_counts = _relationship_class_counts(session, source_model_id)
    ontology = _load_ontology_map(ifc_schema)

    predefined = _grouped_attr(session, source_model_id, ["meta", "predefined_type"], cap)
    object_types = _grouped_attr(session, source_model_id, ["identity", "object_type"], cap)
    type_names = _grouped_attr(session, source_model_id, ["type", "name"], cap)
    storeys = _grouped_attr(session, source_model_id, ["storey", "name"], cap)
    name_stems = _grouped_name_stems(session, source_model_id, cap)
    materials = _grouped_materials(session, source_model_id, cap)
    classifications = _grouped_classifications(session, source_model_id, cap)
    pset_names = _grouped_set_names(session, source_model_id, "property_sets")
    qset_names = _grouped_set_names(session, source_model_id, "quantity_sets")
    endpoint_roles = _grouped_endpoint_roles(session, source_model_id, cap)

    # --- class profiles ---
    for ifc_class in sorted(class_counts):
        onto = ontology.get(ifc_class)
        vocab.classes.append(
            ClassProfile(
                ifc_class=ifc_class,
                kind="entity",
                instance_count=class_counts[ifc_class],
                predefined_types=predefined.get(ifc_class, []),
                name_stems=name_stems.get(ifc_class, []),
                representative_names=[v for v, _ in name_stems.get(ifc_class, [])][
                    : settings.vocab_max_representative_examples
                ],
                object_types=object_types.get(ifc_class, []),
                type_names=type_names.get(ifc_class, []),
                material_names=materials.get(ifc_class, []),
                classification_names=classifications.get(ifc_class, []),
                storey_names=storeys.get(ifc_class, []),
                property_set_names=pset_names.get(ifc_class, []),
                quantity_set_names=qset_names.get(ifc_class, []),
                present_in_ontology=onto is not None,
                ontology_label=onto[0] if onto else None,
                ancestors=onto[1] if onto else [],
            )
        )
    for ifc_class in sorted(rel_counts):
        onto = ontology.get(ifc_class)
        vocab.classes.append(
            ClassProfile(
                ifc_class=ifc_class,
                kind="relationship",
                instance_count=rel_counts[ifc_class],
                endpoint_roles=endpoint_roles.get(ifc_class, []),
                present_in_ontology=onto is not None,
                ontology_label=onto[0] if onto else None,
                ancestors=onto[1] if onto else [],
            )
        )

    # --- observed fact profiles ---
    _emit_attr_facts(vocab, name_stems, "name_stem", "attribute", None, "name", "contains")
    _emit_attr_facts(
        vocab,
        predefined,
        "predefined_type",
        "meta",
        None,
        "predefined_type",
        "case_insensitive_exact",
    )
    _emit_attr_facts(
        vocab,
        object_types,
        "object_type",
        "attribute",
        None,
        "object_type",
        "case_insensitive_exact",
    )
    _emit_attr_facts(
        vocab,
        type_names,
        "type_name",
        "type",
        None,
        "type_name",
        "case_insensitive_exact",
    )
    _emit_attr_facts(vocab, materials, "material", "material", None, None, None)
    _emit_attr_facts(vocab, classifications, "classification", "classification", None, None, None)
    _emit_attr_facts(vocab, storeys, "storey", "storey", None, "storey_name", None)

    _emit_property_value_facts(session, source_model_id, vocab, cap, min_occ)
    _emit_property_coverage_facts(session, source_model_id, vocab, cap, class_counts)
    _emit_quantity_coverage(session, source_model_id, vocab, class_counts)

    # Global cap on internal fact count. Trim FAIRLY across (class, fact_kind)
    # buckets by round-robin so a high-volume kind (property values) cannot
    # starve every class's name stems or a late-alphabet class's facts
    # (Task 16 §3 "do not silently sample without a stable sort and counts").
    vocab.facts = _fair_trim(vocab.facts, settings.vocab_max_facts_total)
    return vocab


def _fair_trim(facts: list[ObservedFactProfile], cap: int) -> list[ObservedFactProfile]:
    if len(facts) <= cap:
        facts.sort(key=lambda f: (f.ifc_class, f.fact_kind, -f.occurrence_count, f.observed_value))
        return facts
    buckets: dict[tuple, list[ObservedFactProfile]] = {}
    for f in facts:
        buckets.setdefault((f.ifc_class, f.fact_kind), []).append(f)
    for b in buckets.values():
        b.sort(key=lambda f: (-f.occurrence_count, f.observed_value))
    kept: list[ObservedFactProfile] = []
    ordered_keys = sorted(buckets)
    idx = 0
    while len(kept) < cap:
        progressed = False
        for k in ordered_keys:
            b = buckets[k]
            if idx < len(b):
                kept.append(b[idx])
                progressed = True
                if len(kept) >= cap:
                    break
        if not progressed:
            break
        idx += 1
    kept.sort(key=lambda f: (f.ifc_class, f.fact_kind, -f.occurrence_count, f.observed_value))
    return kept


# ---------------------------------------------------------------------------
# Grouped extraction helpers
# ---------------------------------------------------------------------------


def _entity_class_counts(session: Session, sid: int) -> dict[str, int]:
    rows = session.execute(
        text("SELECT ifc_class, count(*) FROM ifc_entities WHERE source_model_id = :id GROUP BY 1"),
        {"id": sid},
    ).fetchall()
    return {r[0]: r[1] for r in rows}


def _relationship_class_counts(session: Session, sid: int) -> dict[str, int]:
    rows = session.execute(
        text(
            "SELECT ifc_class, count(*) FROM ifc_relationships WHERE source_model_id = :id "
            "GROUP BY 1"
        ),
        {"id": sid},
    ).fetchall()
    return {r[0]: r[1] for r in rows}


def _grouped_attr(
    session: Session, sid: int, path: list[str], cap: int
) -> dict[str, list[tuple[str, int]]]:
    """Group a canonical_json text attribute by (ifc_class, value)."""
    expr = "canonical_json" + "".join(f"->'{p}'" for p in path[:-1]) + f"->>'{path[-1]}'"
    rows = session.execute(
        text(
            f"SELECT ifc_class, {expr} AS v, count(*) AS n "  # noqa: S608 (path is a fixed literal list)
            "FROM ifc_entities WHERE source_model_id = :id "
            f"AND {expr} IS NOT NULL "
            "GROUP BY 1, 2 ORDER BY 1, 3 DESC, 2"
        ),
        {"id": sid},
    ).fetchall()
    rows = [r for r in rows if not _is_noise_value(r[1])]
    return _bucket(_top_per_group(rows, 0, cap))


def _grouped_name_stems(session: Session, sid: int, cap: int) -> dict[str, list[tuple[str, int]]]:
    rows = session.execute(
        text(
            r"SELECT ifc_class, regexp_replace(canonical_json->'identity'->>'name', "
            r"'_\(#\d+\)$', '') AS stem, count(*) AS n "
            "FROM ifc_entities WHERE source_model_id = :id "
            "AND canonical_json->'identity'->>'name' IS NOT NULL "
            "GROUP BY 1, 2 ORDER BY 1, 3 DESC, 2"
        ),
        {"id": sid},
    ).fetchall()
    rows = [r for r in rows if r[1] and r[1].strip() and not _is_noise_value(r[1])]
    return _bucket(_top_per_group(rows, 0, cap))


def _grouped_materials(session: Session, sid: int, cap: int) -> dict[str, list[tuple[str, int]]]:
    rows = session.execute(
        text(
            "SELECT ifc_class, m->>'name' AS v, count(*) AS n "
            "FROM ifc_entities, jsonb_array_elements(canonical_json->'materials') m "
            "WHERE source_model_id = :id AND m->>'name' IS NOT NULL "
            "GROUP BY 1, 2 ORDER BY 1, 3 DESC, 2"
        ),
        {"id": sid},
    ).fetchall()
    rows = [r for r in rows if not _is_noise_value(r[1])]
    return _bucket(_top_per_group(rows, 0, cap))


def _grouped_classifications(
    session: Session, sid: int, cap: int
) -> dict[str, list[tuple[str, int]]]:
    rows = session.execute(
        text(
            "SELECT ifc_class, COALESCE(c->>'name', c->>'identification') AS v, count(*) AS n "
            "FROM ifc_entities, jsonb_array_elements(canonical_json->'classifications') c "
            "WHERE source_model_id = :id "
            "GROUP BY 1, 2 ORDER BY 1, 3 DESC, 2"
        ),
        {"id": sid},
    ).fetchall()
    rows = [r for r in rows if not _is_noise_value(r[1])]
    return _bucket(_top_per_group(rows, 0, cap))


def _grouped_set_names(session: Session, sid: int, top_key: str) -> dict[str, list[str]]:
    rows = session.execute(
        text(
            "SELECT DISTINCT ifc_class, set_name FROM ifc_entities, "
            "jsonb_object_keys(canonical_json->:top_key) AS set_name "
            "WHERE source_model_id = :id ORDER BY 1, 2"
        ),
        {"id": sid, "top_key": top_key},
    ).fetchall()
    out: dict[str, list[str]] = {}
    for cls, name in rows:
        out.setdefault(cls, []).append(name)
    return out


def _grouped_endpoint_roles(
    session: Session, sid: int, cap: int
) -> dict[str, list[tuple[str, int]]]:
    rows = session.execute(
        text(
            "SELECT r.ifc_class, rm.role, count(*) AS n "
            "FROM ifc_relationships r JOIN relationship_members rm ON rm.relationship_id = r.id "
            "WHERE r.source_model_id = :id GROUP BY 1, 2 ORDER BY 1, 3 DESC, 2"
        ),
        {"id": sid},
    ).fetchall()
    return _bucket(_top_per_group(rows, 0, cap))


def _bucket(rows: list[tuple]) -> dict[str, list[tuple[str, int]]]:
    out: dict[str, list[tuple[str, int]]] = {}
    for cls, value, n in rows:
        out.setdefault(cls, []).append((value, int(n)))
    return out


# ---------------------------------------------------------------------------
# Fact emission
# ---------------------------------------------------------------------------


def _emit_attr_facts(
    vocab: ModelVocabulary,
    grouped: dict[str, list[tuple[str, int]]],
    fact_kind: str,
    source: str,
    set_name: str | None,
    field_name: str | None,
    operator: str | None,
) -> None:
    for ifc_class, values in grouped.items():
        for value, count in values:
            queryable = None
            if operator and field_name:
                field_kind = {
                    "attribute": "attribute",
                    "meta": "attribute",
                    "type": "type_fact",
                    "storey": "attribute",
                }.get(source, "attribute")
                queryable = QueryableRef(
                    field_kind=field_kind,
                    set_name=None,
                    field_name=field_name,
                    operator=operator,
                    value=value,
                )
            vocab.facts.append(
                ObservedFactProfile(
                    ifc_class=ifc_class,
                    fact_kind=fact_kind,
                    source=source,
                    set_name=set_name,
                    field_name=field_name,
                    observed_value=value,
                    normalized_value=value if fact_kind == "name_stem" else None,
                    occurrence_count=count,
                    queryable=queryable,
                )
            )


def _emit_property_value_facts(
    session: Session, sid: int, vocab: ModelVocabulary, cap: int, min_occ: int
) -> None:
    rows = session.execute(
        text(
            "SELECT e.ifc_class, ps.key AS pset, pr.key AS prop, pr.value->>'value' AS v, "
            "count(*) AS n "
            "FROM ifc_entities e, jsonb_each(e.canonical_json->'property_sets') ps, "
            "jsonb_each(ps.value) pr "
            "WHERE e.source_model_id = :id AND pr.value->>'value' IS NOT NULL "
            "AND char_length(pr.value->>'value') BETWEEN 2 AND 40 "
            "GROUP BY 1, 2, 3, 4 HAVING count(*) >= :minocc "
            "ORDER BY 1, 2, 3, 5 DESC, 4"
        ),
        {"id": sid, "minocc": min_occ},
    ).fetchall()
    rows = [r for r in rows if not _is_noise_value(r[3])]
    # Only genuinely CATEGORICAL fields yield value facts: a field with a small
    # number of distinct values (e.g. Type ∈ {Wall, Roof, Slab, …}) carries
    # semantic meaning, whereas a field with hundreds of distinct values (IDs,
    # labels, layers) is per-instance noise. This keeps Type = Roof while
    # discarding high-cardinality noise (Task 16 §3 noise bounds, §12 roof case).
    distinct_per_field: dict[tuple, int] = {}
    for r in rows:
        distinct_per_field[(r[0], r[1], r[2])] = distinct_per_field.get((r[0], r[1], r[2]), 0) + 1
    max_categorical = 15
    rows = [r for r in rows if distinct_per_field[(r[0], r[1], r[2])] <= max_categorical]
    # Cap per (class, property-set, field) so each field's distinctive values
    # (e.g. Type = Roof) survive rather than being crowded out by another field's
    # high-frequency values within the same class (Task 16 §3, §12 roof case).
    per_field_cap = min(cap, 8)
    for ifc_class, pset, prop, value, count in _top_per_composite(rows, (0, 1, 2), per_field_cap):
        vocab.facts.append(
            ObservedFactProfile(
                ifc_class=ifc_class,
                fact_kind="property_value",
                source="property",
                set_name=pset,
                field_name=prop,
                observed_value=value,
                normalized_value=None,
                occurrence_count=int(count),
                queryable=QueryableRef(
                    field_kind="property",
                    set_name=pset,
                    field_name=prop,
                    operator="case_insensitive_exact",
                    value=value,
                ),
            )
        )


def _emit_property_coverage_facts(
    session: Session, sid: int, vocab: ModelVocabulary, cap: int, class_counts: dict[str, int]
) -> None:
    rows = session.execute(
        text(
            "SELECT e.ifc_class, ps.key AS pset, pr.key AS prop, count(*) AS n "
            "FROM ifc_entities e, jsonb_each(e.canonical_json->'property_sets') ps, "
            "jsonb_each(ps.value) pr "
            "WHERE e.source_model_id = :id "
            "GROUP BY 1, 2, 3 ORDER BY 1, 4 DESC, 3"
        ),
        {"id": sid},
    ).fetchall()
    for ifc_class, pset, prop, populated in _top_per_group(rows, 0, cap):
        vocab.facts.append(
            ObservedFactProfile(
                ifc_class=ifc_class,
                fact_kind="property_coverage",
                source="property",
                set_name=pset,
                field_name=prop,
                observed_value=f"{populated}/{class_counts.get(ifc_class, populated)} populated",
                normalized_value=None,
                occurrence_count=int(populated),
                queryable=None,
            )
        )


def _emit_quantity_coverage(
    session: Session, sid: int, vocab: ModelVocabulary, class_counts: dict[str, int]
) -> None:
    rows = session.execute(
        text(
            "SELECT e.ifc_class, qs.key AS qset, q.key AS qty, count(*) AS n, "
            "bool_or(q.value ? 'normalized_value') AS has_unit "
            "FROM ifc_entities e, jsonb_each(e.canonical_json->'quantity_sets') qs, "
            "jsonb_each(qs.value) q "
            "WHERE e.source_model_id = :id "
            "GROUP BY 1, 2, 3 ORDER BY 1, 4 DESC, 3"
        ),
        {"id": sid},
    ).fetchall()
    for ifc_class, qset, qty, populated, has_unit in rows:
        vocab.quantities.append(
            QuantityCoverageProfile(
                ifc_class=ifc_class,
                set_name=qset,
                field_name=qty,
                populated_count=int(populated),
                total_count=class_counts.get(ifc_class, int(populated)),
                unit_available=bool(has_unit),
            )
        )


def _load_ontology_map(ifc_schema: str | None) -> dict[str, tuple[str, list[str]]]:
    """Map ifc_class -> (label, ancestors) from the bundled ontology when the
    model's schema version is bundled; otherwise empty (degrade truthfully,
    Task 16 §2)."""
    if not ifc_schema:
        return {}
    try:
        from app.query.semantic.ontology.loader import get_ontology

        doc = get_ontology(ifc_schema)
    except Exception:  # noqa: BLE001 - unbundled/absent ontology degrades to empty
        return {}
    return {e.ifc_class: (e.label, e.ancestors) for e in doc.entities}
