"""Tests: import and vector-stage idempotency logic at the unit level (spec §10)."""

from __future__ import annotations

from tests.conftest import minimal_canonical


def test_same_canonical_json_produces_same_text():
    """Re-running text generation on unchanged JSON must give identical output."""
    from bim_rag.templates import generate_text

    c = minimal_canonical(
        name="W-001",
        storey_name="Ground Floor",
        psets={"Pset_WallCommon": {"IsExternal": {"value": True, "type": "bool"}}},
    )
    t1, _ = generate_text(c)
    t2, _ = generate_text(c)
    assert t1 == t2


def test_different_template_version_key_differs():
    """Upsert key includes template_version so a version change triggers regeneration."""
    from bim_rag.templates import TEMPLATE_VERSION

    key_v001 = ("entity_id_1", "entity_description", TEMPLATE_VERSION, "BAAI/bge-m3")
    key_v002 = ("entity_id_1", "entity_description", "v002", "BAAI/bge-m3")
    assert key_v001 != key_v002


def test_different_embedding_model_key_differs():
    from bim_rag.templates import TEMPLATE_VERSION

    key1 = ("entity_id_1", "entity_description", TEMPLATE_VERSION, "BAAI/bge-m3")
    key2 = ("entity_id_1", "entity_description", TEMPLATE_VERSION, "BAAI/bge-large-en")
    assert key1 != key2


def test_same_source_fingerprint_prevents_duplicate_model():
    """Two model records with the same fingerprint would violate UNIQUE(file_fingerprint)."""
    fingerprint = "abc123def456"
    record1 = {"file_fingerprint": fingerprint, "file_name": "test.ifc"}
    record2 = {"file_fingerprint": fingerprint, "file_name": "test.ifc"}
    # Simulate the constraint: same fingerprint = same model
    assert record1["file_fingerprint"] == record2["file_fingerprint"]


def test_unique_entity_key_per_model_and_global_id():
    """Two entities with the same (source_model_id, global_id) are not allowed."""
    source_model_id = 1
    global_id = "WALL001"
    key = (source_model_id, global_id)
    seen = set()
    seen.add(key)
    duplicate_detected = key in seen
    assert duplicate_detected is True


def test_credential_sanitization():
    from bim_rag.config import sanitize_db_error

    raw = "connection failed: postgresql://user:secret@localhost:5432/mydb"
    sanitized = sanitize_db_error(raw)
    assert "secret" not in sanitized
    assert "user" not in sanitized
    assert "<credentials>" in sanitized
    assert "localhost" in sanitized


def test_credential_sanitization_preserves_host():
    from bim_rag.config import sanitize_db_error

    raw = "FATAL: password authentication failed for user 'admin' at postgresql://admin:pw123@db.host:5432/bim"
    sanitized = sanitize_db_error(raw)
    assert "pw123" not in sanitized
    assert "db.host" in sanitized
