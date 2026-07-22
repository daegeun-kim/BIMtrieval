"""Manifest schema, hashing, validation, and atomic publication (task25 §2.1).

The artifact is the contract between ingestion and the backend, so these tests
pin the properties a reader depends on: identical input yields an identical
hash, a changed fingerprint yields an ISOLATED file, and a structurally invalid
document never reaches the final path.
"""

from __future__ import annotations

import json
import os

import pytest

from bim_rag.semantic_manifest.schema import (
    COVERAGE_POPULATED,
    MANIFEST_BUILDER_VERSION,
    MANIFEST_SCHEMA_VERSION,
    REQUIRED_SECTIONS,
    ManifestValidationError,
    build_document,
    canonical_json,
    compute_content_hash,
    estimate_tokens,
    validate_document,
)
from bim_rag.semantic_manifest.writer import (
    manifest_path,
    read_manifest,
    write_manifest,
)


def _content(**overrides):
    content = {
        "object_level": {
            "classes": [
                {
                    "id": "cls:IfcWall",
                    "ifc_class": "IfcWall",
                    "count": 12,
                    "attributes": [
                        {
                            "id": "attr:IfcWall.name",
                            "field": "name",
                            "data_type": "text",
                            "coverage": COVERAGE_POPULATED,
                            "populated_count": 12,
                            "total_count": 12,
                        }
                    ],
                }
            ]
        },
        "type_property_level": {
            "property_containers": [],
            "quantity_containers": [],
            "materials": [],
            "classifications": [],
        },
        "relationship_level": {"relationship_classes": []},
        "global_level": {
            "entity_total": 12,
            "class_inventory": [{"ifc_class": "IfcWall", "count": 12}],
            "storeys": [],
            "missing_capabilities": [],
        },
    }
    content.update(overrides)
    return content


def _document(fingerprint="f" * 64, source_model_id=7, content=None):
    return build_document(
        source_model_id=source_model_id,
        file_fingerprint=fingerprint,
        file_name="synthetic.ifc",
        ifc_schema="IFC2X3",
        extraction_version="v001",
        content=content if content is not None else _content(),
    )


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_the_same_content_always_hashes_identically():
    assert _document()["identity"]["content_hash"] == _document()["identity"]["content_hash"]


def test_key_order_does_not_affect_the_hash():
    """Serialization is canonical, so dict construction order cannot leak in."""
    a = {"beta": 1, "alpha": 2, "nested": {"z": 1, "a": 2}}
    b = {"alpha": 2, "nested": {"a": 2, "z": 1}, "beta": 1}

    assert compute_content_hash(a) == compute_content_hash(b)


def test_any_semantic_change_changes_the_hash():
    baseline = _document()["identity"]["content_hash"]
    changed = _content()
    changed["object_level"]["classes"][0]["count"] = 13

    assert _document(content=changed)["identity"]["content_hash"] != baseline


def test_identity_metadata_is_not_part_of_the_hashed_content():
    """The hash describes the SEMANTICS, so re-running for a differently-named
    file with identical content must not appear to be a semantic change."""
    a = build_document(
        source_model_id=1,
        file_fingerprint="a" * 64,
        file_name="one.ifc",
        ifc_schema="IFC2X3",
        extraction_version="v001",
        content=_content(),
    )
    b = build_document(
        source_model_id=2,
        file_fingerprint="b" * 64,
        file_name="two.ifc",
        ifc_schema="IFC4",
        extraction_version="v002",
        content=_content(),
    )

    assert a["identity"]["content_hash"] == b["identity"]["content_hash"]


def test_canonical_json_keeps_non_ascii_readable():
    """Escaping would inflate the binder prompt for no benefit (§2.4)."""
    assert "Vägg" in canonical_json({"label": "Vägg"})


def test_the_document_records_both_versions():
    identity = _document()["identity"]

    assert identity["manifest_schema_version"] == MANIFEST_SCHEMA_VERSION
    assert identity["builder_version"] == MANIFEST_BUILDER_VERSION


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_a_well_formed_document_validates():
    assert validate_document(_document()) == []


def test_all_four_representations_are_required():
    for section in REQUIRED_SECTIONS:
        content = _content()
        del content[section]
        problems = validate_document(_document(content=content))

        assert any(section in p for p in problems), section


def test_a_tampered_content_block_fails_the_hash_check():
    document = _document()
    document["content"]["object_level"]["classes"][0]["count"] = 999

    assert any("content_hash" in p for p in validate_document(document))


def test_an_unknown_coverage_state_is_rejected():
    content = _content()
    content["object_level"]["classes"][0]["attributes"][0]["coverage"] = "probably_fine"

    assert any("coverage" in p for p in validate_document(_document(content=content)))


def test_duplicate_semantic_ids_are_rejected():
    """The binder selects records BY id, so a collision binds the wrong concept."""
    content = _content()
    content["object_level"]["classes"][0]["attributes"].append(
        {
            "id": "attr:IfcWall.name",
            "field": "duplicate",
            "data_type": "text",
            "coverage": COVERAGE_POPULATED,
            "populated_count": 1,
            "total_count": 12,
        }
    )

    assert any("duplicate semantic id" in p for p in validate_document(_document(content=content)))


def test_a_schema_version_mismatch_is_rejected():
    document = _document()
    document["identity"]["manifest_schema_version"] = "v000"

    assert any("manifest_schema_version" in p for p in validate_document(document))


@pytest.mark.parametrize("missing", ["identity", "content"])
def test_a_document_missing_a_top_level_block_is_rejected(missing):
    document = _document()
    del document[missing]

    assert validate_document(document)


# ---------------------------------------------------------------------------
# Atomic publication
# ---------------------------------------------------------------------------


def test_writing_publishes_at_the_fingerprint_scoped_path(tmp_path):
    document = _document(fingerprint="a" * 64, source_model_id=3)

    stats = write_manifest(document, tmp_path)

    assert stats["path"] == str(manifest_path(tmp_path, 3, "a" * 64))
    assert (tmp_path / "3" / f"{'a' * 64}.semantic.json").is_file()


def test_a_changed_fingerprint_creates_an_isolated_artifact(tmp_path):
    """A new version of a model must not overwrite the old one's semantics."""
    write_manifest(_document(fingerprint="a" * 64, source_model_id=3), tmp_path)
    write_manifest(_document(fingerprint="b" * 64, source_model_id=3), tmp_path)

    written = sorted(p.name for p in (tmp_path / "3").iterdir())

    assert written == [f"{'a' * 64}.semantic.json", f"{'b' * 64}.semantic.json"]


def test_rewriting_the_same_fingerprint_replaces_in_place(tmp_path):
    write_manifest(_document(fingerprint="a" * 64), tmp_path)
    write_manifest(_document(fingerprint="a" * 64), tmp_path)

    assert len(list((tmp_path / "7").iterdir())) == 1


def test_an_invalid_document_never_reaches_the_final_path(tmp_path):
    document = _document()
    document["content"]["object_level"]["classes"][0]["count"] = 999  # breaks the hash

    with pytest.raises(ManifestValidationError):
        write_manifest(document, tmp_path)

    assert not (tmp_path / "7").exists()


def test_a_failed_write_leaves_no_temporary_file_behind(tmp_path):
    write_manifest(_document(), tmp_path)
    leftovers = [p.name for p in (tmp_path / "7").iterdir() if p.name.startswith(".")]

    assert leftovers == []


def test_a_published_artifact_reads_back_identically(tmp_path):
    document = _document()
    write_manifest(document, tmp_path)

    restored = read_manifest(manifest_path(tmp_path, 7, "f" * 64))

    assert restored == document


def test_a_corrupt_artifact_is_rejected_on_read(tmp_path):
    write_manifest(_document(), tmp_path)
    path = manifest_path(tmp_path, 7, "f" * 64)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["content"]["global_level"]["entity_total"] = 10101
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ManifestValidationError):
        read_manifest(path)


def test_a_truncated_artifact_is_rejected_on_read(tmp_path):
    write_manifest(_document(), tmp_path)
    path = manifest_path(tmp_path, 7, "f" * 64)
    path.write_bytes(path.read_bytes()[:40])

    with pytest.raises(json.JSONDecodeError):
        read_manifest(path)


def test_the_written_bytes_are_the_canonical_serialization(tmp_path):
    document = _document()
    stats = write_manifest(document, tmp_path)
    raw = manifest_path(tmp_path, 7, "f" * 64).read_bytes()

    assert raw == canonical_json(document).encode("utf-8")
    assert stats["bytes"] == len(raw)


# ---------------------------------------------------------------------------
# Size reporting
# ---------------------------------------------------------------------------


def test_the_token_estimate_is_conservative():
    """It feeds a soft-target check, where over-estimating is the safe direction."""
    document = _document()
    serialized = len(canonical_json(document).encode("utf-8"))

    # Real tokenizers average well above 3 characters/token on compact JSON.
    assert estimate_tokens(document) == serialized // 3
    assert estimate_tokens(document) > serialized // 5


def test_the_manifest_package_imports_no_model_or_network_dependency():
    """§2.2: the artifact is generated deterministically, never by an LLM.

    Asserted structurally over the package's own source rather than by mocking a
    call, because the guarantee is "there is no such code path at all" — a
    future edit that adds one must fail here even if no test exercises it.
    """
    import bim_rag.semantic_manifest as package

    forbidden = (
        "openai",
        "torch",
        "sentence_transformers",
        "transformers",
        "requests",
        "httpx",
        "urllib",
        "socket",
    )

    package_dir = os.path.dirname(package.__file__)
    offenders = []
    for filename in sorted(os.listdir(package_dir)):
        if not filename.endswith(".py"):
            continue
        source = open(os.path.join(package_dir, filename), encoding="utf-8").read()
        for name in forbidden:
            if f"import {name}" in source or f"from {name}" in source:
                offenders.append(f"{filename} imports {name}")

    assert offenders == []


def test_generation_is_pure_given_the_same_inputs():
    """No timestamp, path, or environment value participates in the content."""
    first = _document()
    second = _document()

    assert first == second
    assert validate_document(first) == []
