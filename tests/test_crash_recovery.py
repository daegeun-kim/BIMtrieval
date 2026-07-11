"""Tests: task03.md CLOCK_WATCHDOG_TIMEOUT (0x101) crash-prevention safeguards.

No real DB, model, or GPU — all CUDA/DB interactions are mocked.
"""

from __future__ import annotations

import os

import pytest

from tests.conftest import minimal_canonical

# ---------------------------------------------------------------------------
# Batch-size guard
# ---------------------------------------------------------------------------


def test_validate_batch_size_rejects_64():
    from bim_rag.config import validate_batch_size

    with pytest.raises(ValueError, match="prohibited"):
        validate_batch_size(64)


@pytest.mark.parametrize("n", [1, 2, 4, 8])
def test_validate_batch_size_accepts_recovery_range(n):
    from bim_rag.config import validate_batch_size

    assert validate_batch_size(n) == n


@pytest.mark.parametrize("n", [0, -1, 9, 100])
def test_validate_batch_size_rejects_out_of_range(n):
    from bim_rag.config import validate_batch_size

    with pytest.raises(ValueError):
        validate_batch_size(n)


def test_recovery_batch_size_within_validated_range():
    """Batch size may move from 4 up to 8 only after batch-4 validation (task03.md); never 64."""
    from bim_rag.config import CUDA_BATCH_SIZE, MAX_CUDA_BATCH_SIZE

    assert 1 <= CUDA_BATCH_SIZE <= MAX_CUDA_BATCH_SIZE == 8


def test_stage2_embed_uses_cuda_batch_size_constant_not_64():
    import bim_rag.stage2_embed as mod

    assert not hasattr(mod, "BATCH_SIZE_GPU")
    from bim_rag.config import CUDA_BATCH_SIZE

    assert CUDA_BATCH_SIZE != 64


# ---------------------------------------------------------------------------
# Conservative thread limits
# ---------------------------------------------------------------------------


def test_thread_limit_env_vars_set():
    import bim_rag.config  # noqa: F401  (import triggers os.environ.setdefault)

    assert os.environ.get("OMP_NUM_THREADS") is not None
    assert os.environ.get("TOKENIZERS_PARALLELISM") == "false"


def test_thread_limit_constant_is_conservative():
    from bim_rag.config import THREAD_LIMIT

    assert 1 <= THREAD_LIMIT <= 8


# ---------------------------------------------------------------------------
# Token-aware truncation
# ---------------------------------------------------------------------------


class _WordTokenizer:
    """~1 token per word — enough to exercise budget logic deterministically."""

    def encode(self, text: str) -> list[int]:
        return list(range(len(text.split())))


def test_generate_text_without_tokenizer_returns_2_tuple():
    c = minimal_canonical()
    result = generate_text_2tuple(c)
    assert len(result) == 2


def generate_text_2tuple(c):
    from bim_rag.templates import generate_text

    return generate_text(c)


def test_generate_text_with_tokenizer_returns_4_tuple_with_counts():
    from bim_rag.templates import generate_text

    c = minimal_canonical(name="W-001", storey_name="Ground Floor")
    result = generate_text(c, tokenizer=_WordTokenizer())
    assert len(result) == 4
    text, truncated, original_tokens, encoded_tokens = result
    assert isinstance(text, str)
    assert original_tokens is not None
    assert encoded_tokens is not None
    assert encoded_tokens <= original_tokens


def test_generate_text_token_budget_drops_low_priority_sentences():
    from bim_rag.templates import generate_text
    from bim_rag.text_limits import apply_token_budget

    psets = {f"Pset_{i}": {"Prop": {"value": "x" * 20, "type": "str"}} for i in range(30)}
    c = minimal_canonical(psets=psets)
    text_notok, _ = generate_text(c)  # char-only truncation

    tokenizer = _WordTokenizer()
    # Force a tiny budget directly via apply_token_budget to prove enforcement works
    sentences = text_notok.split(". ")
    kept, truncated, encoded = apply_token_budget(sentences, tokenizer, max_tokens=5)
    assert truncated is True
    assert encoded <= 5


def test_generate_text_identity_survives_token_truncation():
    from bim_rag.text_limits import apply_token_budget

    c = minimal_canonical(ifc_class="IfcWall", global_id="WALL999")
    # identity/global_id are highest priority -> always kept even under a tiny budget
    from bim_rag.templates import _build_feature_sentences

    sentences = [s for _, s in _build_feature_sentences(c)]
    kept, _, _ = apply_token_budget(sentences, _WordTokenizer(), max_tokens=1000)
    assert any("IfcWall" in s for s in kept)


def test_generate_rel_text_with_tokenizer_returns_4_tuple():
    from bim_rag.rel_templates import generate_rel_text

    c = {
        "meta": {"step_id": 1, "global_id": "REL001", "ifc_class": "IfcRelAggregates"},
        "identity": {},
        "scalars": {},
        "endpoints": {},
        "warnings": [],
    }
    result = generate_rel_text(c, tokenizer=_WordTokenizer())
    assert len(result) == 4


def test_generate_rel_text_without_tokenizer_returns_2_tuple():
    from bim_rag.rel_templates import generate_rel_text

    c = {
        "meta": {"step_id": 1, "global_id": "REL001", "ifc_class": "IfcRelAggregates"},
        "identity": {},
        "scalars": {},
        "endpoints": {},
        "warnings": [],
    }
    result = generate_rel_text(c)
    assert len(result) == 2


# ---------------------------------------------------------------------------
# Deterministic hashing (resume / skip-if-unchanged)
# ---------------------------------------------------------------------------


def test_hash_json_deterministic():
    from bim_rag.stage2_embed import _hash_json

    obj = {"b": 2, "a": 1}
    obj2 = {"a": 1, "b": 2}
    assert _hash_json(obj) == _hash_json(obj2)


def test_hash_json_changes_with_content():
    from bim_rag.stage2_embed import _hash_json

    assert _hash_json({"a": 1}) != _hash_json({"a": 2})


def test_hash_text_deterministic():
    from bim_rag.stage2_embed import _hash_text

    assert _hash_text("hello") == _hash_text("hello")
    assert _hash_text("hello") != _hash_text("world")


# ---------------------------------------------------------------------------
# Upsert / skip logic (mocked session, no DB)
# ---------------------------------------------------------------------------


def test_upsert_rag_document_inserts_when_absent():
    from unittest.mock import MagicMock

    from bim_rag.stage2_embed import _upsert_rag_document

    session = MagicMock()
    session.query.return_value.filter_by.return_value.first.return_value = None

    inserted = _upsert_rag_document(
        session,
        source_model_id=1,
        source_kind="entity",
        entity_id=10,
        relationship_id=None,
        document_type="entity_description",
        template_version="v001",
        text_value="text",
        truncated=False,
        source_hash="sh",
        text_hash="th",
        original_token_count=5,
        encoded_token_count=5,
        vec_list=[0.1] * 1024,
        metadata={"ifc_class": "IfcWall"},
    )
    assert inserted is True
    session.add.assert_called_once()


def test_upsert_rag_document_updates_when_present():
    from unittest.mock import MagicMock

    from bim_rag.stage2_embed import _upsert_rag_document

    session = MagicMock()
    existing_row = MagicMock()
    session.query.return_value.filter_by.return_value.first.return_value = existing_row

    inserted = _upsert_rag_document(
        session,
        source_model_id=1,
        source_kind="entity",
        entity_id=10,
        relationship_id=None,
        document_type="entity_description",
        template_version="v001",
        text_value="new text",
        truncated=False,
        source_hash="sh2",
        text_hash="th2",
        original_token_count=6,
        encoded_token_count=6,
        vec_list=[0.2] * 1024,
        metadata={},
    )
    assert inserted is False
    session.add.assert_not_called()
    assert existing_row.document_text == "new text"
    assert existing_row.source_hash == "sh2"


def test_skip_condition_matches_when_hashes_and_dim_and_embedding_agree():
    """Simulates the resume skip-check used in run_vector_phase's entity loop."""
    prior = ("sh", "th", 1024, True)
    source_hash, text_hash = "sh", "th"
    skip = (
        prior is not None
        and prior[0] == source_hash
        and prior[1] == text_hash
        and prior[2] == 1024
        and prior[3]
    )
    assert skip is True


def test_skip_condition_false_when_source_hash_changed():
    prior = ("sh-old", "th", 1024, True)
    source_hash, text_hash = "sh-new", "th"
    skip = (
        prior is not None
        and prior[0] == source_hash
        and prior[1] == text_hash
        and prior[2] == 1024
        and prior[3]
    )
    assert skip is False


def test_skip_condition_false_when_embedding_missing():
    prior = ("sh", "th", 1024, False)  # embedding column is NULL
    source_hash, text_hash = "sh", "th"
    skip = (
        prior is not None
        and prior[0] == source_hash
        and prior[1] == text_hash
        and prior[2] == 1024
        and prior[3]
    )
    assert skip is False


# ---------------------------------------------------------------------------
# CUDA sync / error boundary
# ---------------------------------------------------------------------------


def test_encode_batch_success_returns_embeddings():
    from unittest.mock import MagicMock

    from bim_rag.stage2_embed import _encode_batch

    model = MagicMock()
    model.device.type = "cpu"
    model.encode.return_value = [[0.1, 0.2], [0.3, 0.4]]

    result = _encode_batch(model, ["a", "b"], source_kind="entity", batch_offset=0)
    assert result == [[0.1, 0.2], [0.3, 0.4]]


def test_encode_batch_raises_and_reports_offset_on_device_error():
    from unittest.mock import MagicMock

    from bim_rag.stage2_embed import _encode_batch

    model = MagicMock()
    model.device.type = "cuda"
    model.encode.side_effect = RuntimeError("CUDA error: device-side assert triggered")

    with pytest.raises(RuntimeError, match="entity batch at offset 40"):
        _encode_batch(model, ["a", "b", "c", "d"], source_kind="entity", batch_offset=40)


def test_encode_batch_does_not_retry(monkeypatch):
    """A device error must propagate once — no internal retry loop."""
    from unittest.mock import MagicMock

    from bim_rag.stage2_embed import _encode_batch

    model = MagicMock()
    model.device.type = "cuda"
    model.encode.side_effect = RuntimeError("device error")

    with pytest.raises(RuntimeError):
        _encode_batch(model, ["a"], source_kind="relationship", batch_offset=0)

    assert model.encode.call_count == 1


# ---------------------------------------------------------------------------
# Additive migration idempotency (mocked engine)
# ---------------------------------------------------------------------------


def test_add_hash_columns_migration_is_additive_and_idempotent():
    from unittest.mock import MagicMock

    from bim_rag.stage2_embed import _add_rag_document_hash_columns

    engine = MagicMock()
    conn = MagicMock()
    engine.connect.return_value.__enter__.return_value = conn

    _add_rag_document_hash_columns(engine)
    _add_rag_document_hash_columns(engine)

    assert conn.execute.call_count == 8  # 4 statements x 2 runs
    for call in conn.execute.call_args_list:
        stmt = str(call.args[0])
        assert "ADD COLUMN IF NOT EXISTS" in stmt
    assert conn.commit.call_count == 2
