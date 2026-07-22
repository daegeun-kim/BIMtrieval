"""Artifact path resolution and atomic manifest writing (task25 §2.1).

One file per source model::

    model_semantics/{source_model_id}/{full_file_fingerprint}.semantic.json

A changed fingerprint therefore creates an ISOLATED artifact rather than
overwriting the previous model's, and a stale artifact is detectable by name
alone. Writing is temp-sibling → validate → atomic replace, so a partially
written or structurally invalid document never occupies the final path: a
reader either sees the previous good artifact or none at all.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from bim_rag.semantic_manifest.schema import (
    MANIFEST_SUFFIX,
    ManifestValidationError,
    canonical_json,
    estimate_tokens,
    validate_document,
)


def manifest_dir(root: Path, source_model_id: int) -> Path:
    return Path(root) / str(source_model_id)


def manifest_path(root: Path, source_model_id: int, file_fingerprint: str) -> Path:
    """The one legal path for this (model, fingerprint) pair."""
    return manifest_dir(root, source_model_id) / f"{file_fingerprint}{MANIFEST_SUFFIX}"


def write_manifest(document: dict[str, Any], root: Path) -> dict[str, Any]:
    """Validate then atomically publish `document`. Returns write diagnostics.

    Raises `ManifestValidationError` before touching the final path if the
    document is structurally invalid — §2.1 requires validation to precede the
    replace, not follow it.
    """
    problems = validate_document(document)
    if problems:
        raise ManifestValidationError(
            "refusing to write an invalid semantic manifest: " + "; ".join(problems[:5])
        )

    identity = document["identity"]
    target = manifest_path(root, identity["source_model_id"], identity["file_fingerprint"])
    target.parent.mkdir(parents=True, exist_ok=True)

    payload = canonical_json(document)
    encoded = payload.encode("utf-8")

    # Temp sibling in the SAME directory so os.replace stays on one filesystem
    # and is therefore genuinely atomic.
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

    return {
        "path": str(target),
        "bytes": len(encoded),
        "estimated_tokens": estimate_tokens(document),
        "content_hash": identity["content_hash"],
        "manifest_schema_version": identity["manifest_schema_version"],
        "builder_version": identity["builder_version"],
        "validated": True,
    }


def read_manifest(path: Path) -> dict[str, Any]:
    """Read and structurally validate an artifact from disk."""
    import json

    with open(path, "rb") as handle:
        document = json.loads(handle.read().decode("utf-8"))
    problems = validate_document(document)
    if problems:
        raise ManifestValidationError(
            f"semantic manifest at {path.name} is invalid: " + "; ".join(problems[:5])
        )
    return document
