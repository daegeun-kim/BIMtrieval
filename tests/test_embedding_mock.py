"""Tests: embedding dimension validation and Stage 2 precondition (no real model/DB)."""

from __future__ import annotations

import math

import pytest

EMBEDDING_DIM = 1024


def _fake_embedding(dim: int = EMBEDDING_DIM, valid: bool = True) -> list[float]:
    if not valid:
        vec = [float("nan")] * dim
        return vec
    return [1.0 / math.sqrt(dim)] * dim  # unit vector


def test_valid_embedding_has_correct_dimension():
    vec = _fake_embedding()
    assert len(vec) == EMBEDDING_DIM


def test_invalid_nan_embedding_detected():
    vec = _fake_embedding(valid=False)
    has_nan = any(math.isnan(x) or math.isinf(x) for x in vec)
    assert has_nan is True


def test_valid_embedding_no_nan_or_inf():
    vec = _fake_embedding()
    has_bad = any(math.isnan(x) or math.isinf(x) for x in vec)
    assert has_bad is False


def test_wrong_dimension_detected():
    vec = _fake_embedding(dim=768)
    assert len(vec) != EMBEDDING_DIM


def test_l2_norm_of_normalised_embedding():
    """L2-normalised vector should have norm ≈ 1."""
    vec = _fake_embedding()
    norm = math.sqrt(sum(x * x for x in vec))
    assert abs(norm - 1.0) < 1e-6


def test_stage2_precondition_raises_without_stage1(monkeypatch):
    """Stage 2 must refuse if Stage 1 data is absent (simulated with mock session)."""
    from unittest.mock import MagicMock

    from bim_rag.stage2_embed import _check_stage1_precondition

    mock_session = MagicMock()
    mock_session.query.return_value.first.return_value = None  # no source model

    with pytest.raises(RuntimeError, match="Stage 1 has not been run"):
        _check_stage1_precondition(mock_session)


def test_stage2_precondition_raises_when_entities_missing(monkeypatch):
    from unittest.mock import MagicMock

    from bim_rag.schema.models import IfcSourceModel
    from bim_rag.stage2_embed import _check_stage1_precondition

    mock_session = MagicMock()
    fake_model = MagicMock(spec=IfcSourceModel)
    fake_model.id = 1
    mock_session.query.return_value.first.return_value = fake_model
    mock_session.query.return_value.filter_by.return_value.count.return_value = 0

    with pytest.raises(RuntimeError, match="no entities"):
        _check_stage1_precondition(mock_session)


def test_stage2_precondition_passes_when_stage1_complete():
    from unittest.mock import MagicMock

    from bim_rag.schema.models import IfcSourceModel
    from bim_rag.stage2_embed import _check_stage1_precondition

    mock_session = MagicMock()
    fake_model = MagicMock(spec=IfcSourceModel)
    fake_model.id = 1

    def query_side_effect(cls):
        m = MagicMock()
        if cls == IfcSourceModel:
            m.first.return_value = fake_model
        else:
            fb = MagicMock()
            fb.count.return_value = 42
            m.filter_by.return_value = fb
        return m

    mock_session.query.side_effect = query_side_effect

    model_id, count = _check_stage1_precondition(mock_session)
    assert model_id == 1
    assert count == 42
