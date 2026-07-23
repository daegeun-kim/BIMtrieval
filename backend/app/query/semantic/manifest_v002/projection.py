"""Deterministic compact binder projection of a v002 manifest (task26 §5.8).

The projection is the COMPLETE binder-selectable universe in its smallest
faithful form: every executable semantic ID with enough information to choose
correctly — kind, label, bounded aliases, permitted uses/operators, per-subject
applicability with concise coverage, symbolic accessor, value policy — plus
derived floors, profiles, traversal contracts, and raw storeys.

It deliberately omits: full value vocabularies, duplicate class inventories,
verbose limitation prose, GlobalId sets, raw canonical JSON, physical paths
(provenance), and embeddings. Backend validation uses the FULL parsed manifest;
this form exists only to be serialized into the stable prompt prefix.

Determinism matters: the serialized JSON is byte-stable for a given manifest
content hash, so the projection hash keys the provider prompt cache.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from app.query.semantic.manifest_v002.schema import (
    Capability,
    ManifestV002,
)

#: Aliases per concept kept in the prompt (recall channels handle the rest).
_MAX_ALIASES = 4
#: Endpoint classes listed per traversal side before eliding with a count.
_MAX_ENDPOINT_CLASSES = 10


@dataclass(frozen=True)
class BinderProjection:
    """The serialized stable prompt prefix plus its identity."""

    payload: dict[str, Any]
    json_text: str
    projection_hash: str
    estimated_tokens: int


#: Facts stated once for the whole projection instead of once per entry.
#: `kind` and `accessor` are derivable from each ID's prefix; operators are
#: derivable from the data type; uses have kind/type defaults. Entries carry
#: only deviations, which is what keeps the complete universe within budget.
_LEGEND = {
    "id_prefixes": {
        "cls": {"kind": "class", "accessor": "entity.class", "uses": ["target", "topic_context"]},
        "attr": {"kind": "field", "accessor": "json.attribute"},
        "prop": {"kind": "field", "accessor": "json.property_value"},
        "qty": {"kind": "field", "accessor": "json.quantity_value"},
        "mat": {"kind": "field", "accessor": "json.material_name"},
        "cla": {"kind": "field", "accessor": "json.classification_field"},
        "spatial": {
            "kind": "spatial",
            "accessor": "spatial.effective_membership",
            "uses": ["scope", "group"],
        },
        "path": {"kind": "traversal", "accessor": "relationship.member_edge", "uses": ["traverse"]},
        "floor": {"kind": "derived_floor", "accessor": "derived.physical_floor",
                  "uses": ["scope", "group", "target"]},
        "derived": {"kind": "derived_profile", "uses": ["target"]},
        "storey": {"kind": "storey", "accessor": "entity.class"},
    },
    "field_defaults": {
        "uses": ["filter", "group", "report"],
        "numeric_full_uses": ["filter", "group", "report", "order", "aggregate"],
    },
    "operators_by_type": {
        "text": ["equals", "not_equals", "contains", "starts_with", "one_of",
                 "is_present", "is_missing"],
        "number": ["equals", "not_equals", "greater_than", "greater_or_equal", "less_than",
                   "less_or_equal", "between", "one_of", "is_present", "is_missing"],
        "boolean": ["equals", "not_equals", "is_present", "is_missing"],
    },
    "notes": (
        "applies maps subject class -> known/eligible counts; equal counts mean complete "
        "coverage. 'unit?' marks a numeric field whose unit contract is unproven: only "
        "is_present/is_missing apply, never comparison or aggregation (presence_only). "
        "value_lookup means exact stored values are resolved at request time."
    ),
}


def build_binder_projection(manifest: ManifestV002) -> BinderProjection:
    payload = {
        "model": {
            "source_model_id": manifest.source_model_id,
            "ifc_schema": manifest.ifc_schema,
            "entity_total": manifest.entity_total,
        },
        "legend": _LEGEND,
        "capabilities": [
            _capability_entry(c)
            for c in sorted(manifest.capabilities.values(), key=lambda c: c.semantic_id)
        ],
        "traversals": [
            _traversal_entry(t)
            for t in sorted(manifest.traversals.values(), key=lambda t: t.semantic_id)
        ],
        "floors": _floors_entry(manifest),
        "profiles": [
            {
                "id": p.semantic_id,
                "label": p.label,
                "aliases": list(p.aliases[:_MAX_ALIASES]),
                "uses": list(p.uses),
            }
            for p in sorted(manifest.profiles.values(), key=lambda p: p.semantic_id)
        ],
        "storeys": [
            {"id": s.semantic_id, "name": s.name, "elevation": s.elevation}
            for s in sorted(manifest.storeys.values(), key=lambda s: s.semantic_id)
        ],
    }
    json_text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return BinderProjection(
        payload=payload,
        json_text=json_text,
        projection_hash=hashlib.sha256(json_text.encode("utf-8")).hexdigest(),
        estimated_tokens=len(json_text.encode("utf-8")) // 3,
    )


def _normalized(value: str) -> str:
    return "".join(ch for ch in value.casefold() if ch.isalnum())


def _derived_label(semantic_id: str) -> str:
    """The label an entry gets for free from its ID."""
    _, _, rest = semantic_id.partition(":")
    return rest


def _capability_entry(capability: Capability) -> dict[str, Any]:
    entry: dict[str, Any] = {"id": capability.semantic_id}

    if _normalized(capability.label) != _normalized(_derived_label(capability.semantic_id)):
        entry["label"] = capability.label

    # Aliases the binder could not derive from the label itself.
    trivial = {_normalized(capability.label), _normalized(_derived_label(capability.semantic_id))}
    aliases = []
    for alias in capability.aliases:
        if _normalized(alias) not in trivial:
            aliases.append(alias)
            trivial.add(_normalized(alias))
        if len(aliases) >= 2:
            break
    if aliases:
        entry["aliases"] = aliases

    if capability.data_type:
        entry["type"] = capability.data_type

    # Uses only when they deviate from the legend's kind/type defaults.
    default_uses = _default_uses(capability)
    if tuple(capability.uses) != default_uses:
        entry["uses"] = list(capability.uses)
    if (
        capability.data_type == "number"
        and capability.operators
        and set(capability.operators) <= {"is_present", "is_missing"}
    ):
        entry["presence_only"] = True

    if not capability.executable:
        entry["executable"] = False
        if capability.limitation:
            entry["limitation"] = capability.limitation[:160]

    if capability.applicability:
        applies: dict[str, str | int] = {}
        for a in capability.applicability:
            subject = a.subject[4:] if a.subject.startswith("cls:") else a.subject
            if a.known_count == a.eligible_count:
                applies[subject] = a.known_count
            else:
                applies[subject] = f"{a.known_count}/{a.eligible_count}"
            if a.unit_state == "known" and a.unit:
                applies[subject] = f"{applies[subject]} {a.unit}"
            elif a.unit_state == "unknown" and capability.data_type == "number":
                applies[subject] = f"{applies[subject]} unit?"
        entry["applies"] = applies

    if capability.value_policy == "enumerated" and capability.values:
        entry["values"] = [v for v, _ in capability.values]
    elif capability.value_policy == "request_lookup":
        entry["value_lookup"] = True
    return entry


_KIND_DEFAULT_USES: dict[str, tuple[str, ...]] = {
    "class": ("target", "topic_context"),
    "spatial": ("scope", "group"),
    "derived_floor": ("scope", "group", "target"),
    "derived_profile": ("target",),
}


def _default_uses(capability: Capability) -> tuple[str, ...]:
    if capability.kind in _KIND_DEFAULT_USES:
        return _KIND_DEFAULT_USES[capability.kind]
    if capability.kind == "field":
        if capability.data_type == "number" and not (
            capability.operators and set(capability.operators) <= {"is_present", "is_missing"}
        ):
            return ("filter", "group", "report", "order", "aggregate")
        return ("filter", "group", "report")
    return ()


def _traversal_entry(traversal) -> dict[str, Any]:
    def _bounded(classes: tuple[str, ...]) -> list[str]:
        listed = list(classes[:_MAX_ENDPOINT_CLASSES])
        if len(classes) > _MAX_ENDPOINT_CLASSES:
            listed.append(f"+{len(classes) - _MAX_ENDPOINT_CLASSES} more")
        return listed

    return {
        "id": traversal.semantic_id,
        "rel": traversal.relationship,
        "from_role": traversal.from_role,
        "to_role": traversal.to_role,
        "direction": traversal.direction,
        "from": _bounded(traversal.from_classes),
        "to": _bounded(traversal.to_classes),
        "count": traversal.relationship_count,
        "max_hops": traversal.max_supported_hops,
    }


def _floors_entry(manifest: ManifestV002) -> dict[str, Any]:
    floors = manifest.floors
    return {
        "note": floors.interpretation_note,
        "bands": [
            {
                "id": band.semantic_id,
                "ordinal": band.occupiable_ordinal,
                "classification": band.classification,
                "confidence": band.confidence,
                "storey_count": len(band.storey_global_ids),
                "names": [n for n in band.storey_names if n][:4],
                "elevation": [band.elevation_min, band.elevation_max],
            }
            for band in floors.bands
        ],
    }
