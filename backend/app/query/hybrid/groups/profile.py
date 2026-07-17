"""Deterministic factual profile for an evidence group (Task 17 §3).

The profile is built from stored data and the static ontology — never invented by
an LLM and never merely one ingestion `description` field. It reuses the bounded
model-vocabulary class profile (names, storeys, types, property/quantity sets)
already computed for resolution, plus the group's own exact count/class histogram.
The planner's `role_hint` is kept OUT of the factual profile.
"""

from __future__ import annotations

from typing import Any

from app.query.hybrid.groups.schemas import EvidenceGroup, PredicateKind


def build_factual_profile(group: EvidenceGroup, vocab: Any) -> dict:
    profile: dict[str, Any] = {}
    if group.exact_count is not None:
        profile["exact_count"] = group.exact_count
    if group.rag_candidate_count is not None:
        profile["rag_candidate_count"] = group.rag_candidate_count
    hist = (group.factual_profile or {}).get("class_histogram")
    if hist:
        profile["class_histogram"] = hist

    # Enrich a single-class predicate from the deterministic vocabulary profile.
    classes = group.predicate.ifc_classes
    if len(classes) == 1:
        cp = _class_profile(vocab, classes[0])
        if cp is not None:
            if cp.name_stems:
                profile["common_names"] = [v for v, _ in cp.name_stems[:6]]
            if cp.predefined_types:
                profile["predefined_types"] = [v for v, _ in cp.predefined_types[:6]]
            if cp.object_types:
                profile["object_types"] = [v for v, _ in cp.object_types[:6]]
            if cp.storey_names:
                profile["storeys"] = [v for v, _ in cp.storey_names[:6]]
            if cp.property_set_names:
                profile["property_sets"] = cp.property_set_names[:8]
            if cp.material_names:
                profile["materials"] = [v for v, _ in cp.material_names[:6]]
    if group.predicate.kind in (
        PredicateKind.PROPERTY_VALUE.value,
        PredicateKind.ATTRIBUTE_VALUE.value,
        PredicateKind.TYPE_VALUE.value,
    ):
        profile["predicate_field"] = group.predicate.field_name
        profile["predicate_value"] = group.predicate.value
    return profile


def _class_profile(vocab: Any, ifc_class: str):
    if vocab is None:
        return None
    for c in vocab.classes:
        if c.ifc_class == ifc_class:
            return c
    return None
