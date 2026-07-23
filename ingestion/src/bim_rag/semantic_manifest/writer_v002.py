"""Atomic v002 manifest writing (task26 §5.1).

Same location and fingerprint isolation as v001 —
`model_semantics/{source_model_id}/{fingerprint}.semantic.v002.json` — with a
versioned suffix so a v001 artifact under the same identity is never
overwritten.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from bim_rag.semantic_manifest.schema import (
    ManifestValidationError,
    canonical_json,
    estimate_tokens,
)
from bim_rag.semantic_manifest.schema_v002 import (
    MANIFEST_SUFFIX_V002,
    validate_document_v002,
)
from bim_rag.semantic_manifest.writer import manifest_dir


def manifest_path_v002(root: Path, source_model_id: int, file_fingerprint: str) -> Path:
    return manifest_dir(root, source_model_id) / f"{file_fingerprint}{MANIFEST_SUFFIX_V002}"


def write_manifest_v002(document: dict[str, Any], root: Path) -> dict[str, Any]:
    problems = validate_document_v002(document)
    if problems:
        raise ManifestValidationError(
            "refusing to write an invalid v002 semantic manifest: " + "; ".join(problems[:5])
        )

    identity = document["identity"]
    target = manifest_path_v002(root, identity["source_model_id"], identity["file_fingerprint"])
    target.parent.mkdir(parents=True, exist_ok=True)

    encoded = canonical_json(document).encode("utf-8")
    temp = target.with_name(f".{target.name}.tmp{os.getpid()}")
    try:
        with open(temp, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, target)
    finally:
        if temp.exists():
            temp.unlink()

    content = document["content"]
    return {
        "path": str(target),
        "bytes": len(encoded),
        "estimated_tokens": estimate_tokens(document),
        "content_hash": identity["content_hash"],
        "manifest_schema_version": identity["manifest_schema_version"],
        "builder_version": identity["builder_version"],
        "contract_version": identity["contract_version"],
        "capability_count": len(content["capabilities"]),
        "traversal_count": len(content["traversals"]),
        "floor_band_count": len(content["derived_floors"].get("bands", [])),
        "validated": True,
    }


def read_manifest_v002(path: Path) -> dict[str, Any]:
    with open(path, "rb") as handle:
        document = json.loads(handle.read().decode("utf-8"))
    problems = validate_document_v002(document)
    if problems:
        raise ManifestValidationError(
            f"v002 semantic manifest at {path.name} is invalid: " + "; ".join(problems[:5])
        )
    return document
