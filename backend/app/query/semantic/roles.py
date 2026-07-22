"""IFC schema roles and occurrence-family closure (Task 24 §3.2).

Answers two questions that the query pipeline must never guess at:

1. **What KIND of thing is this IFC class?** An occurrence (a physical/logical
   object that can be a result), a type definition, a property definition, a
   spatial structure entity, a relationship, or something else. A requested
   occurrence may never silently become a type definition or a component
   (Task 24 §Non-negotiable generalization rule).
2. **Which stored classes satisfy a request for this class?** A generic
   superclass request includes its present occurrence subtypes; an explicitly
   requested subtype stays specific (Task 24 §3.2).

Both answers are derived from the committed IFC ontology's own inheritance
(`OntologyEntity.ancestors`), never from a table of query phrases mapped to
class lists — which §3.2 explicitly forbids. Three consequences of using
inheritance *correctly* replace what would otherwise be per-query patches:

- `IfcDoorStyle` descends from `IfcTypeProduct`/`IfcTypeObject`, so it is a
  TYPE DEFINITION and can never be added to a count of door occurrences.
- `IfcStairFlight` is **not** a descendant of `IfcStair` in IFC (both descend
  from `IfcBuildingElement`), so a stair request does not absorb stair flights.
  §3.2's "semantically related components are not descendants" needs no
  component blacklist — it is already true in the schema.
- `IfcWallStandardCase` **is** a descendant of `IfcWall`, so a generic wall
  request correctly widens to both, while a request for
  `IfcWallStandardCase` alone stays narrow.

Degrading truthfully
--------------------
A class the ontology does not describe (a vendor extension, or an IFC4 class
such as `IfcDoorType` when the model is IFC2X3) resolves to `UNKNOWN` with an
empty closure rather than being guessed into a role. Callers must treat
`UNKNOWN` as "cannot establish", never as "occurrence".
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from functools import lru_cache

from app.query.semantic.ontology.loader import OntologyResourceError, get_ontology

__all__ = [
    "SchemaRole",
    "ClassRoleInfo",
    "get_role_index",
    "schema_role",
    "family_closure",
    "is_result_kind",
    "RoleIndex",
]


class SchemaRole(str, Enum):
    """What a class IS in the IFC schema — decided by ancestry, not by name."""

    #: A physical or logical object occurrence: the normal result of a question
    #: about "how many doors", "show me the columns".
    OCCURRENCE = "occurrence"
    #: A type/style definition (`IfcTypeObject` and descendants, incl. the IFC2X3
    #: `Ifc*Style` classes). Describes occurrences; is not itself an occurrence.
    TYPE_DEFINITION = "type_definition"
    #: `IfcPropertyDefinition` and descendants (property sets, quantity sets).
    PROPERTY_DEFINITION = "property_definition"
    #: `IfcSpatialStructureElement` and descendants (site, building, storey,
    #: space). A distinct RESULT KIND from a logical floor band (§3.2, §11.4):
    #: counting `IfcBuildingStorey` entities is not counting building levels.
    SPATIAL_STRUCTURE = "spatial_structure"
    #: `IfcRelationship` and descendants. Evidence ABOUT endpoints, not an
    #: occurrence result unless explicitly requested (§3.2).
    RELATIONSHIP = "relationship"
    #: Groups/systems/actors/processes and other non-result metadata.
    OTHER = "other"
    #: Not described by the loaded ontology. Never treat as an occurrence.
    UNKNOWN = "unknown"


#: Ancestor markers, most specific first. The first marker found in a class's
#: ancestry (or the class's own name) decides its role. Order matters:
#: `IfcSpatialStructureElement` descends from `IfcProduct`, and every
#: `IfcTypeProduct` descends from `IfcTypeObject`, so the narrow markers must be
#: tested before `IfcProduct`/`IfcObject`.
#:
#: This is a schema-level role registry, not a query mapping: every entry names
#: a reusable IFC semantic rule and none of them mentions a question, a value,
#: or a model (§3.2).
_ROLE_MARKERS: tuple[tuple[str, SchemaRole], ...] = (
    ("IfcTypeObject", SchemaRole.TYPE_DEFINITION),
    ("IfcPropertyDefinition", SchemaRole.PROPERTY_DEFINITION),
    ("IfcRelationship", SchemaRole.RELATIONSHIP),
    ("IfcSpatialStructureElement", SchemaRole.SPATIAL_STRUCTURE),
    ("IfcElement", SchemaRole.OCCURRENCE),
    ("IfcProduct", SchemaRole.OCCURRENCE),
)

#: Roles that may be the primary result of an answer part. Spatial structure is
#: included because "how many spaces" is a legitimate exact question — but §11.4
#: still forbids substituting a storey-entity count for a logical floor count.
_RESULT_KINDS = frozenset({SchemaRole.OCCURRENCE, SchemaRole.SPATIAL_STRUCTURE})


@dataclass(frozen=True)
class ClassRoleInfo:
    ifc_class: str
    role: SchemaRole
    abstract: bool
    ancestors: tuple[str, ...]
    #: Every ontology class that declares this class among its ancestors.
    #: Schema-wide; intersect with the model's present classes for a closure.
    descendants: tuple[str, ...]


@dataclass(frozen=True)
class RoleIndex:
    """Immutable per-schema role/inheritance index."""

    schema: str
    classes: dict[str, ClassRoleInfo]

    def info(self, ifc_class: str) -> ClassRoleInfo | None:
        return self.classes.get(ifc_class)

    def role(self, ifc_class: str) -> SchemaRole:
        entry = self.classes.get(ifc_class)
        return entry.role if entry is not None else SchemaRole.UNKNOWN

    def closure(
        self, ifc_class: str, present_classes: frozenset[str] | set[str] | None = None
    ) -> tuple[str, ...]:
        """Stored classes that satisfy a request for `ifc_class` (§3.2).

        The class itself plus its descendants **of the same role**, optionally
        intersected with the classes actually present in the active model.
        Restricting to the same role is what stops a superclass request from
        dragging in a type definition; in practice IFC never mixes roles within
        one inheritance chain, so this is a guard rather than a filter.

        A class the ontology does not know returns an empty tuple: the caller
        must report that it cannot establish the family, not fall back to the
        bare class (§6 "an absent explicit representation describes the BIM
        model"; §3.3 forbids falling back to a nearby class).
        """
        entry = self.classes.get(ifc_class)
        if entry is None:
            return ()
        members = [ifc_class]
        members.extend(d for d in entry.descendants if self.role(d) is entry.role)
        if present_classes is not None:
            members = [c for c in members if c in present_classes]
        # Stable, deterministic: requested class first (when kept), then sorted.
        head = [c for c in members if c == ifc_class]
        rest = sorted(c for c in members if c != ifc_class)
        return tuple(head + rest)


def _role_for(ifc_class: str, ancestors: tuple[str, ...]) -> SchemaRole:
    """Role from the class's own name plus its ancestry, most specific first."""
    lineage = (ifc_class, *ancestors)
    for marker, role in _ROLE_MARKERS:
        if marker in lineage:
            return role
    return SchemaRole.OTHER


def _build_index(schema: str) -> RoleIndex:
    doc = get_ontology(schema)
    descendants: dict[str, list[str]] = {}
    for entity in doc.entities:
        for ancestor in entity.ancestors:
            descendants.setdefault(ancestor, []).append(entity.ifc_class)

    classes: dict[str, ClassRoleInfo] = {}
    for entity in doc.entities:
        ancestors = tuple(entity.ancestors)
        classes[entity.ifc_class] = ClassRoleInfo(
            ifc_class=entity.ifc_class,
            role=_role_for(entity.ifc_class, ancestors),
            abstract=entity.abstract,
            ancestors=ancestors,
            descendants=tuple(sorted(descendants.get(entity.ifc_class, ()))),
        )
    return RoleIndex(schema=doc.schema_name, classes=classes)


@lru_cache(maxsize=4)
def get_role_index(schema: str = "IFC2X3") -> RoleIndex:
    """Load (and cache) the role index for one IFC schema version.

    Raises `OntologyResourceError` when the ontology is missing/stale; callers
    that must stay usable without it should catch that and degrade to
    `SchemaRole.UNKNOWN` rather than inventing roles.
    """
    return _build_index(schema)


def _index_or_none(schema: str) -> RoleIndex | None:
    try:
        return get_role_index(schema)
    except OntologyResourceError:
        return None


def schema_role(ifc_class: str, schema: str = "IFC2X3") -> SchemaRole:
    """Role of one IFC class, or `UNKNOWN` when it cannot be established."""
    index = _index_or_none(schema)
    return index.role(ifc_class) if index is not None else SchemaRole.UNKNOWN


def family_closure(
    ifc_class: str,
    present_classes: frozenset[str] | set[str] | None = None,
    schema: str = "IFC2X3",
) -> tuple[str, ...]:
    """Stored classes satisfying a request for `ifc_class` (see `RoleIndex.closure`)."""
    index = _index_or_none(schema)
    return index.closure(ifc_class, present_classes) if index is not None else ()


def is_result_kind(role: SchemaRole) -> bool:
    """True when a class in this role may be an answer part's primary result."""
    return role in _RESULT_KINDS


#: IFC pairs a type/style definition with its occurrence class by NAME:
#: `IfcWallType`/`IfcWall`, `IfcDoorStyle`/`IfcDoor`,
#: `IfcTransportElementType`/`IfcTransportElement`. The ontology records the
#: inheritance of each class but does not link the two branches, so this is a
#: required invariant the schema does not expose — the narrow case §3.2 permits
#: a schema-level rule for. It is a reusable IFC naming rule, not a query
#: mapping, and every result is validated against the ontology before use.
_TYPE_SUFFIXES = ("Type", "Style")


def occurrence_for_type(ifc_class: str, schema: str = "IFC2X3") -> str | None:
    """The occurrence class a type/style definition describes, or None.

    Needed because IFC2X3 records predefined-type enumerations (ESCALATOR,
    ELEVATOR, …) on the `*Type` class only. Without this pairing a question
    about escalators reaches `IfcTransportElementType`, which is a definition
    record and cannot be an answer — so the honest "this model contains none"
    would be reported as "cannot be established" instead.

    Returns None unless the derived name really exists in the ontology AND is an
    occurrence, so a naming coincidence can never invent a class.
    """
    index = _index_or_none(schema)
    if index is None:
        return None
    entry = index.info(ifc_class)
    if entry is None or entry.role is not SchemaRole.TYPE_DEFINITION:
        return None
    for suffix in _TYPE_SUFFIXES:
        if ifc_class.endswith(suffix) and len(ifc_class) > len(suffix):
            candidate = ifc_class[: -len(suffix)]
            if index.role(candidate) is SchemaRole.OCCURRENCE:
                return candidate
    return None
