"""Sanitized per-source-model schema catalog + deterministic field resolution
(spec_v003 §4, §8, §9, §10).

Two layers:

- `build_schema_catalog()` — a bounded, cacheable summary (distinct classes,
  pset/qset names and a capped sample of field names within each) suitable
  for future planner context. Never returns full canonical JSON or unbounded
  value dumps.
- `resolve_field()` / `resolve_concept()` — the authoritative resolver.
  Existence is always checked directly against the database (not just the
  bounded cache), so a field missing from the capped sample can still be
  validated correctly. `resolve_concept()` searches attribute, quantity,
  property, and type_fact sources for a bare name and returns every match
  with provenance rather than guessing (spec_v003 §8) — the deterministic
  field-resolution registry required by tasks/task05.md item 6.

The JSON shape this module reads matches `bim_rag.ifc_parser.extract_canonical_json`
exactly: `property_sets = {pset_name: {prop_name: {"value", "type"}}}`,
`quantity_sets = {qset_name: {qty_name: {"value", "provenance", "unit"?,
"normalized_value"?, "normalized_unit"?}}}` (normalized_unit is currently
always "m", meters — see `normalize_quantity_value()`).
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal, Mapping

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.query.sql.errors import AmbiguousFieldError, FieldNotFoundError
from app.query.sql.operations import MissingValueState
from app.query.sql.schemas import FieldKind, FieldRef

MAX_CATALOG_SAMPLE = 500

# Fixed attribute fields resolved via canonical_json (bim_rag.ifc_parser identity/meta/storey).
_ATTRIBUTE_JSON_FIELDS: dict[str, tuple[str, ...]] = {
    "name": ("identity", "name"),
    "description": ("identity", "description"),
    "object_type": ("identity", "object_type"),
    "tag": ("identity", "tag"),
    "long_name": ("identity", "long_name"),
    "composition_type": ("identity", "composition_type"),
    "predefined_type": ("meta", "predefined_type"),
    "storey_name": ("storey", "name"),
    "storey_global_id": ("storey", "global_id"),
}
# Fixed attribute fields resolved via a direct ifc_entities column.
_ATTRIBUTE_COLUMN_FIELDS: dict[str, str] = {
    "global_id": "global_id",
    "ifc_class": "ifc_class",
    "step_id": "step_id",
}
# Fixed type_fact fields (bim_rag.ifc_parser._resolve_type — identity facts about the
# assigned type object only, not the type's own property/quantity sets).
_TYPE_FACT_JSON_FIELDS: dict[str, tuple[str, ...]] = {
    "type_name": ("type", "name"),
    "type_global_id": ("type", "global_id"),
    "type_predefined_type": ("type", "predefined_type"),
}

# Read-only public views of the three fixed field maps above. Other modules
# (e.g. the Task 24 field-concept index) need to know which fixed fields exist
# and where they live; exposing immutable proxies keeps this module the single
# definition of that mapping instead of it being duplicated or reached into.
ATTRIBUTE_JSON_FIELDS: Mapping[str, tuple[str, ...]] = MappingProxyType(_ATTRIBUTE_JSON_FIELDS)
ATTRIBUTE_COLUMN_FIELDS: Mapping[str, str] = MappingProxyType(_ATTRIBUTE_COLUMN_FIELDS)
TYPE_FACT_JSON_FIELDS: Mapping[str, tuple[str, ...]] = MappingProxyType(_TYPE_FACT_JSON_FIELDS)


@dataclass(frozen=True)
class ResolvedField:
    field_kind: FieldKind
    set_name: str | None
    field_name: str
    access_kind: Literal["column", "jsonb"]
    column_name: str | None
    json_path: tuple[str, ...]
    declared_value_type: str | None
    unit_capable: bool
    provenance: str


@dataclass
class SchemaCatalog:
    source_model_id: int
    file_fingerprint: str
    extraction_version: str
    entity_classes: list[str]
    relationship_classes: list[str]
    property_sets: dict[str, list[str]]
    property_sets_truncated: dict[str, bool]
    quantity_sets: dict[str, list[str]]
    quantity_sets_truncated: dict[str, bool]
    attribute_fields: list[str]
    type_fact_fields: list[str]


_catalog_cache: dict[tuple[int, str, str], SchemaCatalog] = {}


def invalidate_schema_catalog_cache() -> None:
    _catalog_cache.clear()


def build_schema_catalog(session: Session, source_model_id: int) -> SchemaCatalog:
    """Build (or return cached) sanitized schema catalog for one source model.

    Cached by (source_model_id, file_fingerprint, extraction_version) — spec_v003 §4:
    "Cache this context per source-model fingerprint and extraction version."
    """
    fp_row = session.execute(
        text("SELECT file_fingerprint FROM ifc_source_models WHERE id = :id"),
        {"id": source_model_id},
    ).first()
    if fp_row is None:
        raise FieldNotFoundError(f"source_model_id {source_model_id} does not exist")
    fingerprint = fp_row[0]
    extraction_version = "v001"

    cache_key = (source_model_id, fingerprint, extraction_version)
    cached = _catalog_cache.get(cache_key)
    if cached is not None:
        return cached

    entity_classes = [
        r[0]
        for r in session.execute(
            text(
                "SELECT DISTINCT ifc_class FROM ifc_entities WHERE source_model_id = :id ORDER BY 1"
            ),
            {"id": source_model_id},
        )
    ]
    relationship_classes = [
        r[0]
        for r in session.execute(
            text(
                "SELECT DISTINCT ifc_class FROM ifc_relationships "
                "WHERE source_model_id = :id ORDER BY 1"
            ),
            {"id": source_model_id},
        )
    ]
    property_sets, property_sets_truncated = _distinct_set_and_field_names(
        session, source_model_id, "property_sets"
    )
    quantity_sets, quantity_sets_truncated = _distinct_set_and_field_names(
        session, source_model_id, "quantity_sets"
    )

    catalog = SchemaCatalog(
        source_model_id=source_model_id,
        file_fingerprint=fingerprint,
        extraction_version=extraction_version,
        entity_classes=entity_classes,
        relationship_classes=relationship_classes,
        property_sets=property_sets,
        property_sets_truncated=property_sets_truncated,
        quantity_sets=quantity_sets,
        quantity_sets_truncated=quantity_sets_truncated,
        attribute_fields=sorted(set(_ATTRIBUTE_JSON_FIELDS) | set(_ATTRIBUTE_COLUMN_FIELDS)),
        type_fact_fields=sorted(_TYPE_FACT_JSON_FIELDS),
    )
    _catalog_cache[cache_key] = catalog
    return catalog


def _distinct_set_and_field_names(
    session: Session, source_model_id: int, top_key: str
) -> tuple[dict[str, list[str]], dict[str, bool]]:
    set_names = [
        r[0]
        for r in session.execute(
            text(
                "SELECT DISTINCT set_name FROM ifc_entities, "
                "jsonb_object_keys(canonical_json->:top_key) AS set_name "
                "WHERE source_model_id = :id"
            ),
            {"id": source_model_id, "top_key": top_key},
        )
    ]
    result: dict[str, list[str]] = {}
    truncated: dict[str, bool] = {}
    for set_name in set_names:
        rows = session.execute(
            text(
                "SELECT DISTINCT field_name FROM ifc_entities, "
                "jsonb_object_keys(canonical_json->:top_key->:set_name) AS field_name "
                "WHERE source_model_id = :id LIMIT :cap"
            ),
            {
                "id": source_model_id,
                "top_key": top_key,
                "set_name": set_name,
                "cap": MAX_CATALOG_SAMPLE + 1,
            },
        ).fetchall()
        names = [r[0] for r in rows]
        truncated[set_name] = len(names) > MAX_CATALOG_SAMPLE
        result[set_name] = names[:MAX_CATALOG_SAMPLE]
    return result, truncated


def _assert_set_field_exists(
    session: Session, source_model_id: int, top_key: str, set_name: str, field_name: str
) -> None:
    exists = session.execute(
        text(
            "SELECT EXISTS (SELECT 1 FROM ifc_entities WHERE source_model_id = :id "
            "AND canonical_json->:top_key->:set_name ? :field_name)"
        ),
        {"id": source_model_id, "top_key": top_key, "set_name": set_name, "field_name": field_name},
    ).scalar()
    if not exists:
        raise FieldNotFoundError(
            f"{top_key}.{set_name}.{field_name} not found for source_model_id={source_model_id}"
        )


def _find_across_sets(
    session: Session, source_model_id: int, top_key: str, field_name: str
) -> list[str]:
    rows = session.execute(
        text(
            f"SELECT DISTINCT set_name FROM ifc_entities, "  # noqa: S608 (top_key is a fixed literal, never user input)
            f"jsonb_object_keys(canonical_json->'{top_key}') AS set_name "
            "WHERE source_model_id = :id "
            f"AND canonical_json->'{top_key}'->set_name ? :field_name"
        ),
        {"id": source_model_id, "field_name": field_name},
    ).fetchall()
    return [r[0] for r in rows]


def resolve_field(session: Session, source_model_id: int, field_ref: FieldRef) -> ResolvedField:
    """Strict resolution of an already-disambiguated FieldRef (field_kind is given).

    Raises FieldNotFoundError if the field is not present in this model's
    schema, or AmbiguousFieldError if a DIMENSION name exists in more than
    one quantity set (spec_v003 §8: "return all relevant values rather than
    silently choosing one").
    """
    if field_ref.field_kind is FieldKind.ATTRIBUTE:
        if field_ref.field_name in _ATTRIBUTE_COLUMN_FIELDS:
            return ResolvedField(
                field_kind=FieldKind.ATTRIBUTE,
                set_name=None,
                field_name=field_ref.field_name,
                access_kind="column",
                column_name=_ATTRIBUTE_COLUMN_FIELDS[field_ref.field_name],
                json_path=(),
                declared_value_type="str",
                unit_capable=False,
                provenance="ifc_extracted",
            )
        if field_ref.field_name in _ATTRIBUTE_JSON_FIELDS:
            return ResolvedField(
                field_kind=FieldKind.ATTRIBUTE,
                set_name=None,
                field_name=field_ref.field_name,
                access_kind="jsonb",
                column_name=None,
                json_path=_ATTRIBUTE_JSON_FIELDS[field_ref.field_name],
                declared_value_type="str",
                unit_capable=False,
                provenance="ifc_extracted",
            )
        raise FieldNotFoundError(f"unknown attribute field {field_ref.field_name!r}")

    if field_ref.field_kind is FieldKind.TYPE_FACT:
        if field_ref.field_name not in _TYPE_FACT_JSON_FIELDS:
            raise FieldNotFoundError(f"unknown type_fact field {field_ref.field_name!r}")
        return ResolvedField(
            field_kind=FieldKind.TYPE_FACT,
            set_name=None,
            field_name=field_ref.field_name,
            access_kind="jsonb",
            column_name=None,
            json_path=_TYPE_FACT_JSON_FIELDS[field_ref.field_name],
            declared_value_type="str",
            unit_capable=False,
            provenance="ifc_extracted",
        )

    if field_ref.field_kind is FieldKind.PROPERTY:
        assert field_ref.set_name is not None  # enforced by FieldRef validator
        _assert_set_field_exists(
            session, source_model_id, "property_sets", field_ref.set_name, field_ref.field_name
        )
        return ResolvedField(
            field_kind=FieldKind.PROPERTY,
            set_name=field_ref.set_name,
            field_name=field_ref.field_name,
            access_kind="jsonb",
            column_name=None,
            json_path=("property_sets", field_ref.set_name, field_ref.field_name, "value"),
            declared_value_type=None,
            unit_capable=False,
            provenance="ifc_extracted",
        )

    if field_ref.field_kind is FieldKind.QUANTITY:
        assert field_ref.set_name is not None
        _assert_set_field_exists(
            session, source_model_id, "quantity_sets", field_ref.set_name, field_ref.field_name
        )
        return ResolvedField(
            field_kind=FieldKind.QUANTITY,
            set_name=field_ref.set_name,
            field_name=field_ref.field_name,
            access_kind="jsonb",
            column_name=None,
            json_path=("quantity_sets", field_ref.set_name, field_ref.field_name),
            declared_value_type="float",
            unit_capable=True,
            provenance="ifc_extracted",
        )

    if field_ref.field_kind is FieldKind.DIMENSION:
        # DIMENSION is a normalized *view* over quantity_sets (spec_v002 §9.1), not its own
        # storage location — FieldRef requires set_name=None, so search across all sets.
        matches = _find_across_sets(session, source_model_id, "quantity_sets", field_ref.field_name)
        if not matches:
            raise FieldNotFoundError(
                f"no quantity named {field_ref.field_name!r} found in any quantity set "
                f"for source_model_id={source_model_id}"
            )
        if len(matches) > 1:
            raise AmbiguousFieldError(
                f"{field_ref.field_name!r} exists in multiple quantity sets: {matches}",
                candidates=[
                    {"field_kind": "quantity", "set_name": m, "field_name": field_ref.field_name}
                    for m in matches
                ],
            )
        set_name = matches[0]
        return ResolvedField(
            field_kind=FieldKind.DIMENSION,
            set_name=set_name,
            field_name=field_ref.field_name,
            access_kind="jsonb",
            column_name=None,
            json_path=("quantity_sets", set_name, field_ref.field_name),
            declared_value_type="float",
            unit_capable=True,
            provenance="derived_exact",
        )

    raise FieldNotFoundError(f"unsupported field_kind {field_ref.field_kind!r}")


def resolve_concept(session: Session, source_model_id: int, field_name: str) -> list[ResolvedField]:
    """Search attribute, quantity, property, and type_fact sources for a bare
    field name. Returns every match with provenance rather than guessing
    (spec_v003 §8, tasks/task05.md item 6)."""
    matches: list[ResolvedField] = []

    if field_name in _ATTRIBUTE_COLUMN_FIELDS or field_name in _ATTRIBUTE_JSON_FIELDS:
        matches.append(
            resolve_field(
                session,
                source_model_id,
                FieldRef(field_kind=FieldKind.ATTRIBUTE, field_name=field_name),
            )
        )
    if field_name in _TYPE_FACT_JSON_FIELDS:
        matches.append(
            resolve_field(
                session,
                source_model_id,
                FieldRef(field_kind=FieldKind.TYPE_FACT, field_name=field_name),
            )
        )
    for set_name in _find_across_sets(session, source_model_id, "quantity_sets", field_name):
        matches.append(
            ResolvedField(
                field_kind=FieldKind.QUANTITY,
                set_name=set_name,
                field_name=field_name,
                access_kind="jsonb",
                column_name=None,
                json_path=("quantity_sets", set_name, field_name),
                declared_value_type="float",
                unit_capable=True,
                provenance="ifc_extracted",
            )
        )
    for set_name in _find_across_sets(session, source_model_id, "property_sets", field_name):
        matches.append(
            ResolvedField(
                field_kind=FieldKind.PROPERTY,
                set_name=set_name,
                field_name=field_name,
                access_kind="jsonb",
                column_name=None,
                json_path=("property_sets", set_name, field_name, "value"),
                declared_value_type=None,
                unit_capable=False,
                provenance="ifc_extracted",
            )
        )
    return matches


def normalize_quantity_value(raw_entry: dict, target_unit: str) -> tuple[float | None, str | None]:
    """Convert an ingested quantity_sets entry to a normalized-unit value
    (spec_v002 §9.1, spec_v003 §10).

    Only length ("mm") conversion is currently derivable: `bim_rag.ifc_parser`
    only computes a linear project-length-unit factor (normalized_unit="m"),
    not an area/volume-aware one. Returns (None, reason) rather than
    fabricating a value when conversion is not actually derivable — this is a
    real limitation of the v001 ingestion output, not something this module
    can safely paper over.
    """
    if target_unit == "mm":
        if raw_entry.get("normalized_unit") == "m" and isinstance(
            raw_entry.get("normalized_value"), (int, float)
        ):
            return round(float(raw_entry["normalized_value"]) * 1000.0, 6), None
        return (
            None,
            "length not normalizable: ingestion did not record a project-unit normalized_value",
        )
    if target_unit in ("mm2", "mm3"):
        return None, (
            f"{target_unit} conversion not available: ingestion only computes a linear length "
            "factor, not an area/volume-aware one"
        )
    if target_unit == "degrees":
        return None, "angle unit metadata is not captured by current ingestion output"
    return None, f"unsupported target_unit {target_unit!r}"


def classify_missing_value(present: bool, raw_value: object) -> MissingValueState | None:
    """Return the missing-value state, or None if the value is present and usable
    (spec_v003 §9 — never collapsed into one generic null)."""
    if not present:
        return MissingValueState.ABSENT
    if raw_value is None:
        return MissingValueState.PRESENT_NULL
    if raw_value in ("", [], {}):
        return MissingValueState.PRESENT_EMPTY
    return None
