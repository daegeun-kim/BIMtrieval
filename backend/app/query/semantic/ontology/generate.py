"""OFFLINE dev/build utility for the IFC ontology (Task 16 §2).

NOT imported by the backend runtime. Two independent steps:

    schema  — derive the IfcRoot hierarchy from an authoritative IFC schema via
              IfcOpenShell and write the authoritative JSON. Run under the
              `bim_rag` conda env (which has IfcOpenShell). Makes no OpenAI call.

    index   — read the committed JSON, embed each entity's deterministic profile
              text with BGE-M3, and write the committed `.npy` + `.meta.json`.
              Run under the backend Poetry env (reuses the backend embedding
              path). Makes no OpenAI call.

Usage (from backend/ with app on PYTHONPATH):

    python -m app.query.semantic.ontology.generate schema --schema IFC2X3
    python -m app.query.semantic.ontology.generate index  --schema IFC2X3

The JSON is authoritative and human-inspectable; the index is a derived,
regenerable artifact keyed to the JSON content hash.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.query.semantic.ontology.loader import (
    PROFILE_VERSION,
    compute_content_hash,
    index_paths,
    json_path,
    profile_text,
    split_class_words,
)
from app.query.semantic.ontology.schema import OntologyDocument, OntologyEntity

_ROOT = "IfcRoot"
_BRANCHES = ("IfcObjectDefinition", "IfcPropertyDefinition", "IfcRelationship")


# ---------------------------------------------------------------------------
# Step 1: schema extraction (IfcOpenShell) — dev env only
# ---------------------------------------------------------------------------


def _ancestors(decl) -> list[str]:
    chain: list[str] = []
    parent = decl.supertype()
    while parent is not None:
        chain.append(parent.name())
        parent = parent.supertype()
    return chain


def _enum_items(attr_type) -> list[str] | None:
    """Return the enumeration literals for an attribute type, unwrapping
    named/aggregation wrappers, else None."""
    import ifcopenshell.ifcopenshell_wrapper as w

    t = attr_type
    seen = 0
    while t is not None and seen < 8:
        if isinstance(t, w.enumeration_type):
            return [str(x) for x in t.enumeration_items()]
        declared = getattr(t, "declared_type", None)
        t = declared() if callable(declared) else None
        seen += 1
    return None


def _predefined_types(decl) -> list[str]:
    for attr in decl.all_attributes():
        if attr.name() == "PredefinedType":
            items = _enum_items(attr.type_of_attribute())
            if items:
                return items
    return []


def _branch(ifc_class: str, ancestors: list[str]) -> str:
    chain = [ifc_class] + ancestors
    for b in _BRANCHES:
        if b in chain:
            return b
    return _ROOT


def _short_definition(
    ifc_class: str, abstract: bool, parent: str | None, branch: str, predefined_types: list[str]
) -> str:
    label = split_class_words(ifc_class) or ifc_class
    kind = "an abstract" if abstract else "a concrete"
    branch_words = split_class_words(branch) or branch
    sentence = (
        f"{label} is {kind} IFC entity in the {branch_words} hierarchy"
        + (f", a subtype of {parent}" if parent else "")
        + "."
    )
    if predefined_types:
        listed = ", ".join(t for t in predefined_types if t not in ("USERDEFINED", "NOTDEFINED"))
        if listed:
            sentence += f" Predefined types include {listed}."
    return sentence


def extract_ontology(schema: str) -> OntologyDocument:
    """Derive the IfcRoot-hierarchy ontology for `schema` from IfcOpenShell."""
    import ifcopenshell
    import ifcopenshell.ifcopenshell_wrapper as w

    s = w.schema_by_name(schema)
    entities = [d for d in s.declarations() if isinstance(d, w.entity)]

    profiles: list[OntologyEntity] = []
    for decl in entities:
        name = decl.name()
        anc = _ancestors(decl)
        if name != _ROOT and _ROOT not in anc:
            continue  # only the IfcRoot hierarchy (Task 16 §2)
        parent = decl.supertype().name() if decl.supertype() is not None else None
        predefined = _predefined_types(decl)
        branch = _branch(name, anc)
        direct_attrs = [a.name() for a in decl.attributes()]
        profiles.append(
            OntologyEntity(
                ifc_class=name,
                label=name[3:] if name.startswith("Ifc") else name,
                short_definition=_short_definition(
                    name, decl.is_abstract(), parent, branch, predefined
                ),
                immediate_parent=parent,
                ancestors=anc,
                abstract=decl.is_abstract(),
                predefined_types=predefined,
                direct_attributes=direct_attrs,
                schema=schema,
            )
        )

    profiles.sort(key=lambda e: e.ifc_class)
    content_hash = compute_content_hash(profiles)
    return OntologyDocument(
        schema=schema,
        source="IfcOpenShell ifcopenshell_wrapper.schema_by_name",
        release=f"ifcopenshell {ifcopenshell.version}",
        ontology_version="v001",
        profile_version=PROFILE_VERSION,
        content_hash=content_hash,
        entity_count=len(profiles),
        entities=profiles,
    )


def write_json(doc: OntologyDocument, schema: str) -> Path:
    path = json_path(schema)
    path.write_text(
        json.dumps(doc.model_dump(by_alias=True), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path


# ---------------------------------------------------------------------------
# Step 2: index build (BGE-M3) — reads JSON only, no IfcOpenShell
# ---------------------------------------------------------------------------


def build_index(schema: str) -> tuple[Path, Path]:
    import numpy as np

    from app.query.rag.embedding_service import (
        EMBEDDING_DIM,
        EMBEDDING_MODEL_NAME,
        get_embedding_service,
    )
    from app.query.semantic.ontology.loader import get_ontology

    doc = get_ontology(schema)
    texts = [profile_text(e) for e in doc.entities]
    service = get_embedding_service()
    vectors = np.asarray(service.embed_documents(texts), dtype=np.float32)
    if vectors.shape != (len(doc.entities), EMBEDDING_DIM):
        raise RuntimeError(f"unexpected embedding shape {vectors.shape}")

    npy_path, meta_path = index_paths(schema)
    npy_path.parent.mkdir(parents=True, exist_ok=True)
    np.save(npy_path, vectors)
    meta = {
        "schema": schema,
        "embedding_model": EMBEDDING_MODEL_NAME,
        "embedding_dim": EMBEDDING_DIM,
        "profile_version": PROFILE_VERSION,
        "ontology_content_hash": doc.content_hash,
        "count": len(doc.entities),
        "ifc_classes": [e.ifc_class for e in doc.entities],
    }
    meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return npy_path, meta_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="IFC ontology generator (offline dev utility)")
    parser.add_argument("step", choices=["schema", "index"])
    parser.add_argument("--schema", default="IFC2X3")
    args = parser.parse_args(argv)

    if args.step == "schema":
        doc = extract_ontology(args.schema)
        path = write_json(doc, args.schema)
        print(
            f"[ontology] wrote {path} — {doc.entity_count} entities, hash {doc.content_hash[:12]}…"
        )
    else:
        npy_path, meta_path = build_index(args.schema)
        print(f"[ontology] wrote {npy_path.name} + {meta_path.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
