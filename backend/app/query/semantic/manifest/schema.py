"""Reader-side model of the semantic manifest (task25 §2, §3).

The manifest is the SEMANTIC API between ingestion and the query pipeline: the
binder selects concepts by stable semantic ID and expresses intent, while
deterministic compilers own the physical database schema (§3.3).

This module turns the on-disk document into one uniform universe of
`ManifestConcept` records. That uniformity is the point — §3.1 requires the
binder to be able to select ANY valid semantic ID in the complete manifest, not
just entries from a bounded slate, so there must be a single flat namespace to
validate an arbitrary ID against.

Coverage is carried through unchanged, because the distinctions are load-bearing
downstream: `absent` is an exact zero and stays queryable, while the unsupported
states mean the pipeline genuinely cannot tell and must answer `unavailable`
with the limitation stated rather than silently widening the question (§5).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

MANIFEST_SCHEMA_VERSION = "v001"

COVERAGE_POPULATED = "populated"
COVERAGE_PARTIAL = "partial"
COVERAGE_ABSENT = "absent"
COVERAGE_UNSUPPORTED = "unsupported"
COVERAGE_EXTRACTION_FAILURE = "extraction_failure"
COVERAGE_UNSUPPORTED_SOURCE_STRUCTURE = "unsupported_source_structure"

#: Coverage states under which a concept must NOT be executed as a filter.
#: A bound question that depends on one of these resolves to `unavailable`.
NON_QUERYABLE_COVERAGE = frozenset(
    {COVERAGE_UNSUPPORTED, COVERAGE_EXTRACTION_FAILURE, COVERAGE_UNSUPPORTED_SOURCE_STRUCTURE}
)

# Concept kinds. Roles stay DISTINCT: an occurrence class, the type that defines
# it, a property of it, and a relationship it participates in are four different
# things, and conflating them is the family of defects §9.2 tests against.
KIND_CLASS = "class"
KIND_ATTRIBUTE = "attribute"
KIND_PROPERTY = "property"
KIND_QUANTITY = "quantity"
KIND_MATERIAL = "material"
KIND_CLASSIFICATION = "classification"
KIND_RELATIONSHIP = "relationship"
KIND_ENDPOINT_ROLE = "endpoint_role"
KIND_STOREY = "storey"

FIELD_KINDS = frozenset({KIND_ATTRIBUTE, KIND_PROPERTY, KIND_QUANTITY})


@dataclass(frozen=True)
class ManifestConcept:
    """One selectable semantic record, uniform across every section."""

    semantic_id: str
    kind: str
    label: str
    coverage: str = COVERAGE_POPULATED
    ifc_class: str | None = None
    set_name: str | None = None
    field_name: str | None = None
    data_type: str | None = None
    operators: tuple[str, ...] = ()
    populated_count: int = 0
    total_count: int = 0
    distinct_value_count: int = 0
    #: (value, occurrence_count), most frequent first. Empty when `searchable`.
    values: tuple[tuple[str, int], ...] = ()
    #: High-cardinality: the concept is queryable, but specific values are
    #: resolved by authoritative lookup at query time rather than enumerated.
    searchable: bool = False
    applies_to: tuple[str, ...] = ()
    #: Free text used for lexical and embedding matching during recommendation.
    text: str = ""
    #: Bounded explanation when this concept cannot be queried.
    limitation: str | None = None

    @property
    def is_field(self) -> bool:
        return self.kind in FIELD_KINDS

    @property
    def is_queryable(self) -> bool:
        """False only when the pipeline genuinely cannot determine values.

        `absent` is deliberately queryable: the honest answer is zero, which is
        a real answer and must not degrade into "unavailable".
        """
        return self.coverage not in NON_QUERYABLE_COVERAGE

    @property
    def coverage_ratio(self) -> float:
        if self.total_count <= 0:
            return 0.0
        return self.populated_count / self.total_count

    def has_value(self, candidate: str) -> bool:
        """Case-insensitive membership in the enumerated value vocabulary."""
        target = candidate.strip().casefold()
        return any(value.casefold() == target for value, _ in self.values)


@dataclass
class SemanticManifest:
    """A loaded, validated manifest for one source model."""

    source_model_id: int
    file_fingerprint: str
    file_name: str
    ifc_schema: str | None
    content_hash: str
    manifest_schema_version: str
    builder_version: str
    concepts: dict[str, ManifestConcept] = field(default_factory=dict)
    missing_capabilities: tuple[dict[str, Any], ...] = ()
    entity_total: int = 0
    #: The raw document, fed verbatim to the binder (§2.4 — no truncation).
    document: dict[str, Any] = field(default_factory=dict)

    # -- lookup ------------------------------------------------------------

    def concept(self, semantic_id: str) -> ManifestConcept | None:
        return self.concepts.get(semantic_id)

    def of_kind(self, *kinds: str) -> list[ManifestConcept]:
        wanted = frozenset(kinds)
        return [c for c in self.concepts.values() if c.kind in wanted]

    def classes(self) -> list[ManifestConcept]:
        return self.of_kind(KIND_CLASS)

    def fields(self) -> list[ManifestConcept]:
        return self.of_kind(KIND_ATTRIBUTE, KIND_PROPERTY, KIND_QUANTITY)

    def present_classes(self) -> frozenset[str]:
        return frozenset(c.ifc_class for c in self.classes() if c.ifc_class)

    def fields_for_class(self, ifc_class: str) -> list[ManifestConcept]:
        return [
            c
            for c in self.fields()
            if not c.applies_to or ifc_class in c.applies_to or c.ifc_class == ifc_class
        ]

    def unsupported_capabilities(self) -> tuple[dict[str, Any], ...]:
        return self.missing_capabilities

    def size_report(self) -> dict[str, int]:
        return {
            "concept_count": len(self.concepts),
            "class_count": len(self.classes()),
            "field_count": len(self.fields()),
            "missing_capability_count": len(self.missing_capabilities),
        }


# ---------------------------------------------------------------------------
# Document -> concepts
# ---------------------------------------------------------------------------


def parse_manifest(document: dict[str, Any]) -> SemanticManifest:
    """Flatten a validated document into the uniform concept namespace."""
    identity = document["identity"]
    content = document["content"]

    manifest = SemanticManifest(
        source_model_id=int(identity["source_model_id"]),
        file_fingerprint=identity["file_fingerprint"],
        file_name=identity.get("file_name", ""),
        ifc_schema=identity.get("ifc_schema"),
        content_hash=identity["content_hash"],
        manifest_schema_version=identity["manifest_schema_version"],
        builder_version=identity["builder_version"],
        missing_capabilities=tuple(content["global_level"].get("missing_capabilities", ())),
        entity_total=int(content["global_level"].get("entity_total", 0)),
        document=document,
    )

    for concept in _iter_concepts(content):
        manifest.concepts[concept.semantic_id] = concept
    return manifest


def _iter_concepts(content: dict[str, Any]):
    yield from _object_concepts(content["object_level"])
    yield from _type_property_concepts(content["type_property_level"])
    yield from _relationship_concepts(content["relationship_level"])
    yield from _global_concepts(content["global_level"])


def _object_concepts(section: dict[str, Any]):
    for klass in section.get("classes", ()):
        ifc_class = klass["ifc_class"]
        yield ManifestConcept(
            semantic_id=klass["id"],
            kind=KIND_CLASS,
            label=ifc_class,
            ifc_class=ifc_class,
            populated_count=int(klass.get("count", 0)),
            total_count=int(klass.get("count", 0)),
            text=_split_identifier(ifc_class),
        )
        for attribute in klass.get("attributes", ()):
            yield _field_concept(attribute, KIND_ATTRIBUTE, ifc_class=ifc_class)


def _type_property_concepts(section: dict[str, Any]):
    containers = (
        (KIND_PROPERTY, "property_containers"),
        (KIND_QUANTITY, "quantity_containers"),
    )
    for container_kind, key in containers:
        for container in section.get(key, ()):
            limitation = None
            diagnostic = container.get("structure_diagnostic")
            if diagnostic:
                limitation = diagnostic.get("reason")

            applies_to = tuple(container.get("applies_to", ()))
            # The container itself is selectable, so an unreliable one can be
            # cited as the REASON a question is unavailable.
            yield ManifestConcept(
                semantic_id=container["id"],
                kind=container_kind,
                label=container.get("container") or f"{container_kind} extraction failure",
                coverage=container.get("coverage", COVERAGE_POPULATED),
                set_name=container.get("container"),
                applies_to=applies_to,
                populated_count=int(container.get("occurrence_count", 0)),
                total_count=int(container.get("occurrence_count", 0)),
                distinct_value_count=int(container.get("distinct_field_count", 0)),
                text=_split_identifier(container.get("container") or ""),
                limitation=limitation or container.get("reason"),
            )
            for field_record in container.get("fields", ()):
                yield _field_concept(
                    field_record,
                    container_kind,
                    applies_to=applies_to,
                    set_name=container.get("container"),
                )

    for material in section.get("materials", ()):
        values = tuple((m["value"], int(m["count"])) for m in material.get("materials", ()))
        if not values:
            continue
        yield ManifestConcept(
            semantic_id=material["id"],
            kind=KIND_MATERIAL,
            label=f"{material['ifc_class']} materials",
            coverage=material.get("coverage", COVERAGE_POPULATED),
            ifc_class=material["ifc_class"],
            field_name="material",
            data_type="text",
            operators=("equals", "not_equals", "contains", "in"),
            values=values,
            distinct_value_count=len(values),
            populated_count=sum(c for _, c in values),
            total_count=sum(c for _, c in values),
            text=" ".join(v for v, _ in values),
        )

    for classification in section.get("classifications", ()):
        references = classification.get("references", ())
        values = tuple((ref["code"], int(ref["count"])) for ref in references if ref.get("code"))
        yield ManifestConcept(
            semantic_id=classification["id"],
            kind=KIND_CLASSIFICATION,
            label=f"{classification['ifc_class']} classifications",
            coverage=classification.get("coverage", COVERAGE_POPULATED),
            ifc_class=classification["ifc_class"],
            field_name="classification",
            data_type="text",
            operators=("equals", "not_equals", "contains", "in"),
            values=values,
            distinct_value_count=len(values),
            populated_count=sum(c for _, c in values),
            total_count=sum(c for _, c in values),
            text=" ".join(
                " ".join(filter(None, (r.get("system"), r.get("code"), r.get("description"))))
                for r in references
            ),
        )


def _relationship_concepts(section: dict[str, Any]):
    for relationship in section.get("relationship_classes", ()):
        ifc_class = relationship["ifc_class"]
        yield ManifestConcept(
            semantic_id=relationship["id"],
            kind=KIND_RELATIONSHIP,
            label=ifc_class,
            coverage=relationship.get("coverage", COVERAGE_POPULATED),
            ifc_class=ifc_class,
            populated_count=int(relationship.get("count", 0)),
            total_count=int(relationship.get("count", 0)),
            text=_split_identifier(ifc_class),
        )
        for role in relationship.get("endpoint_roles", ()):
            endpoints = tuple(
                e["endpoint_ifc_class"]
                for e in role.get("endpoints", ())
                if e.get("endpoint_ifc_class")
            )
            yield ManifestConcept(
                semantic_id=role["id"],
                kind=KIND_ENDPOINT_ROLE,
                label=f"{ifc_class}.{role['role']}",
                ifc_class=ifc_class,
                field_name=role["role"],
                applies_to=endpoints,
                populated_count=sum(int(e.get("count", 0)) for e in role.get("endpoints", ())),
                total_count=sum(int(e.get("count", 0)) for e in role.get("endpoints", ())),
                text=f"{_split_identifier(ifc_class)} {_split_identifier(role['role'])}",
            )


def _global_concepts(section: dict[str, Any]):
    for storey in section.get("storeys", ()):
        yield ManifestConcept(
            semantic_id=storey["id"],
            kind=KIND_STOREY,
            label=storey.get("name") or storey["global_id"],
            field_name="storey",
            data_type="text",
            operators=("equals", "in"),
            values=((storey.get("name") or storey["global_id"], 1),),
            distinct_value_count=1,
            text=storey.get("name") or "",
        )


def _field_concept(
    record: dict[str, Any],
    kind: str,
    *,
    ifc_class: str | None = None,
    applies_to: tuple[str, ...] = (),
    set_name: str | None = None,
) -> ManifestConcept:
    values = tuple((v["value"], int(v["count"])) for v in record.get("values", ()))
    field_name = record["field"]
    label = f"{set_name}.{field_name}" if set_name else field_name
    return ManifestConcept(
        semantic_id=record["id"],
        kind=kind,
        label=label,
        coverage=record.get("coverage", COVERAGE_POPULATED),
        ifc_class=ifc_class,
        set_name=set_name or record.get("set"),
        field_name=field_name,
        data_type=record.get("data_type"),
        operators=tuple(record.get("operators", ())),
        populated_count=int(record.get("populated_count", 0)),
        total_count=int(record.get("total_count", 0)),
        distinct_value_count=int(record.get("distinct_value_count", len(values))),
        values=values,
        searchable=bool(record.get("searchable")),
        applies_to=applies_to,
        text=f"{_split_identifier(set_name or '')} {_split_identifier(field_name)}".strip(),
    )


def _split_identifier(identifier: str) -> str:
    """`IfcWallStandardCase` -> `Ifc Wall Standard Case`, for lexical matching."""
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
    return "".join(out).strip()
