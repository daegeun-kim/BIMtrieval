"""Load + validate the committed IFC ontology JSON and its BGE-M3 index
(Task 16 §2). Runtime-only: this module never imports IfcOpenShell — it reads
the artifacts the offline generator produced.

`profile_text()` and `compute_content_hash()` live here so the generator and the
backend runtime derive *identical* embedding text and identical hashes; a
mismatch between the committed JSON and the committed index is a hard error, not
a silently-stale index.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.query.semantic.ontology.schema import OntologyDocument, OntologyEntity

# Bump when `profile_text` changes so a regenerated index is required.
PROFILE_VERSION = "v001"

_ONTOLOGY_DIR = Path(__file__).resolve().parent
_GENERATED_DIR = _ONTOLOGY_DIR / "generated"

_CAMEL_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


def split_class_words(ifc_class: str) -> str:
    """`IfcWallStandardCase` -> `Wall Standard Case` (drops the `Ifc` prefix).

    Gives BGE-M3 a natural-language surface for the class name so semantic
    retrieval can match ordinary wording without any synonym table.
    """
    stem = ifc_class[3:] if ifc_class.startswith("Ifc") else ifc_class
    return _CAMEL_RE.sub(" ", stem).strip()


def profile_text(entity: OntologyEntity) -> str:
    """Deterministic embedding text for one ontology entity.

    Grounded only in schema facts (label, split class words, hierarchy,
    attributes, predefined-type literals, structural short definition) — never
    invented synonyms (Task 16 §2)."""
    words = split_class_words(entity.ifc_class)
    parts = [
        f"IFC class {entity.ifc_class} ({entity.schema_name}).",
        f"Name: {entity.label}." if entity.label else "",
        f"Terms: {words}." if words else "",
        entity.short_definition,
    ]
    if entity.immediate_parent:
        parts.append(f"Parent: {entity.immediate_parent}.")
    if entity.ancestors:
        parts.append("Type hierarchy: " + " > ".join(entity.ancestors) + ".")
    if entity.predefined_types:
        parts.append("Predefined types: " + ", ".join(entity.predefined_types) + ".")
    if entity.direct_attributes:
        parts.append("Attributes: " + ", ".join(entity.direct_attributes) + ".")
    return " ".join(p for p in parts if p)


def compute_content_hash(entities: list[OntologyEntity]) -> str:
    """SHA-256 over the canonical, order-independent ontology content.

    Deliberately excludes generator/runtime metadata (source, release) so the
    hash tracks only schema meaning; the same hash is embedded in the JSON and
    the index meta so drift is detectable."""
    payload = [
        {
            "ifc_class": e.ifc_class,
            "label": e.label,
            "short_definition": e.short_definition,
            "immediate_parent": e.immediate_parent,
            "ancestors": e.ancestors,
            "abstract": e.abstract,
            "predefined_types": e.predefined_types,
            "direct_attributes": e.direct_attributes,
            "schema": e.schema_name,
        }
        for e in sorted(entities, key=lambda x: x.ifc_class)
    ]
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def json_path(schema: str) -> Path:
    return _ONTOLOGY_DIR / f"{schema}.json"


def index_paths(schema: str) -> tuple[Path, Path]:
    base = _GENERATED_DIR / f"{schema}_bge_m3_{PROFILE_VERSION}"
    return base.with_suffix(".npy"), Path(str(base) + ".meta.json")


@lru_cache(maxsize=4)
def get_ontology(schema: str = "IFC2X3") -> OntologyDocument:
    """Load + validate a committed ontology JSON (cached).

    Verifies the stored `content_hash` matches the recomputed hash so a hand-
    edited JSON with a stale hash is rejected rather than trusted."""
    path = json_path(schema)
    if not path.exists():
        raise OntologyResourceError(f"ontology JSON not found for schema {schema!r} at {path}")
    doc = OntologyDocument.model_validate_json(path.read_text(encoding="utf-8"))
    recomputed = compute_content_hash(doc.entities)
    if recomputed != doc.content_hash:
        raise OntologyResourceError(
            f"ontology {schema} content_hash mismatch: file says {doc.content_hash[:12]}…, "
            f"recomputed {recomputed[:12]}…; regenerate the ontology JSON"
        )
    if doc.profile_version != PROFILE_VERSION:
        raise OntologyResourceError(
            f"ontology {schema} profile_version {doc.profile_version!r} != runtime "
            f"{PROFILE_VERSION!r}; regenerate the ontology"
        )
    return doc


@dataclass(frozen=True)
class OntologyIndex:
    """The committed semantic index: entities aligned row-for-row with vectors."""

    schema: str
    embedding_model: str
    embedding_dim: int
    entities: list[OntologyEntity]
    vectors: "object"  # numpy.ndarray (N, dim), L2-normalized

    def __len__(self) -> int:
        return len(self.entities)


@lru_cache(maxsize=4)
def get_ontology_index(schema: str = "IFC2X3") -> OntologyIndex:
    """Load the committed BGE-M3 ontology index (cached).

    Refuses a stale index: the meta must agree with the JSON content hash, the
    runtime embedding model/dim, the profile version, and the entity ordering."""
    import numpy as np

    from app.query.rag.embedding_service import EMBEDDING_DIM, EMBEDDING_MODEL_NAME

    doc = get_ontology(schema)
    npy_path, meta_path = index_paths(schema)
    if not npy_path.exists() or not meta_path.exists():
        raise OntologyResourceError(
            f"ontology index for {schema} missing ({npy_path.name}/{meta_path.name}); "
            "run the ontology index build"
        )
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    if meta.get("ontology_content_hash") != doc.content_hash:
        raise OntologyResourceError(
            f"ontology {schema} index is stale (content_hash mismatch); regenerate the index"
        )
    if meta.get("profile_version") != PROFILE_VERSION:
        raise OntologyResourceError(
            f"ontology {schema} index profile_version mismatch; regenerate the index"
        )
    if meta.get("embedding_model") != EMBEDDING_MODEL_NAME or meta.get("embedding_dim") != (
        EMBEDDING_DIM
    ):
        raise OntologyResourceError(
            f"ontology {schema} index embedding model/dim mismatch; regenerate the index"
        )
    vectors = np.load(npy_path)
    if vectors.shape[0] != len(doc.entities) or vectors.shape[1] != EMBEDDING_DIM:
        raise OntologyResourceError(
            f"ontology {schema} index shape {vectors.shape} does not match "
            f"{len(doc.entities)} entities x {EMBEDDING_DIM}"
        )
    if meta.get("ifc_classes") != [e.ifc_class for e in doc.entities]:
        raise OntologyResourceError(
            f"ontology {schema} index row ordering does not match the JSON entity order"
        )
    return OntologyIndex(
        schema=schema,
        embedding_model=str(meta["embedding_model"]),
        embedding_dim=int(meta["embedding_dim"]),
        entities=list(doc.entities),
        vectors=vectors,
    )


class OntologyResourceError(RuntimeError):
    """Raised when the ontology JSON/index is missing, malformed, or stale."""
