"""Machine-readable IFC ontology schema (Task 16 §2).

These pydantic models define the committed JSON's shape. The JSON is the
authoritative, human-inspectable source of truth; the BGE-M3 index is a derived
artifact keyed to `OntologyDocument.content_hash` so a stale index is refused.

Design notes:
- **No synonym/alias gate.** There is deliberately no `aliases`/`synonyms`
  field. Class profiles are searched semantically (Task 16 §2 "No manual synonym
  gate", §16 Prohibited actions). Adding such a field here is a spec violation.
- **Version-agnostic format.** Nothing here assumes IFC2X3 inheritance or
  predefined-type sets — `IFC4`/`IFC4X3` can be added later as separate
  versioned resources (Task 16 §2 IFC2X3 scope).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class OntologyEntity(BaseModel):
    """One IFC entity declaration's schema-grounded profile.

    `schema` is a reserved BaseModel attribute name, so the python attribute is
    `schema_name` and it is aliased to `schema` in the JSON.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    ifc_class: str = Field(min_length=1, max_length=120)
    label: str = Field(min_length=1, max_length=200)
    short_definition: str = Field(min_length=1, max_length=1000)
    immediate_parent: str | None = Field(default=None, max_length=120)
    ancestors: list[str] = Field(default_factory=list)
    abstract: bool = False
    predefined_types: list[str] = Field(default_factory=list)
    direct_attributes: list[str] = Field(default_factory=list)
    schema_name: str = Field(min_length=1, max_length=40, alias="schema")


class OntologyDocument(BaseModel):
    """The full versioned ontology resource for one IFC schema version."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_name: str = Field(min_length=1, max_length=40, alias="schema")
    source: str
    release: str
    ontology_version: str
    profile_version: str
    content_hash: str
    entity_count: int
    entities: list[OntologyEntity]
