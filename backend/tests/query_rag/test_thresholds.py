"""Named threshold profile lookup (spec_v004 §8). No database access."""

from __future__ import annotations

import pytest

from app.query.rag.thresholds import THRESHOLD_PROFILES, get_threshold
from app.shared.errors import UnsupportedOperationError


def test_default_v001_profile_exists():
    assert "default_v001" in THRESHOLD_PROFILES
    assert 0.0 <= get_threshold("default_v001") <= 1.0


def test_unknown_profile_rejected():
    with pytest.raises(UnsupportedOperationError):
        get_threshold("not_a_real_profile")
