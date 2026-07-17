"""Static versioned IFC schema ontology (Task 16 §2).

The authoritative resource is the committed JSON (`IFC2X3.json`) — a
human-inspectable map of the IFC2X3 TC1 `IfcRoot` hierarchy (301 declarations).
A committed BGE-M3 semantic index (`generated/IFC2X3_bge_m3_v001.*`) is derived
from that JSON by the offline dev generator so the backend never re-embeds
ontology documents per question.
"""

from app.query.semantic.ontology.loader import (
    get_ontology,
    get_ontology_index,
    profile_text,
)
from app.query.semantic.ontology.schema import OntologyDocument, OntologyEntity

__all__ = [
    "OntologyDocument",
    "OntologyEntity",
    "get_ontology",
    "get_ontology_index",
    "profile_text",
]
