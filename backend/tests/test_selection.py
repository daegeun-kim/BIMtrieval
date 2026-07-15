"""Trusted browser-selection resolution (Task 10 §5).

Offline unit tests: the DB resolver is injected, so nothing here touches
PostgreSQL or OpenAI.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.query.selection import (
    SelectionConflictError,
    normalize_global_ids,
    resolve_selection,
)

_ROWS = [
    SimpleNamespace(id=101, global_id="G1"),
    SimpleNamespace(id=102, global_id="G2"),
    SimpleNamespace(id=103, global_id="G3"),
]


def _resolver(rows):
    def inner(_session, _model_id, gids):
        return [r for r in rows if r.global_id in gids]

    return inner


def test_normalize_trims_drops_empty_and_dedupes_stable():
    assert normalize_global_ids([" G1 ", "G2", "", "G1", "  "]) == ["G1", "G2"]


def test_resolves_in_request_order():
    sel = resolve_selection(object(), 1, ["G3", "G1"], [], 5, resolver=_resolver(_ROWS))
    assert sel.entity_ids == [103, 101]
    assert sel.warnings == []


def test_unresolved_ids_produce_bounded_warning():
    sel = resolve_selection(object(), 1, ["G1", "UNKNOWN"], [], 5, resolver=_resolver(_ROWS))
    assert sel.entity_ids == [101]
    assert len(sel.warnings) == 1


def test_global_ids_without_active_model_raise():
    with pytest.raises(SelectionConflictError):
        resolve_selection(object(), None, ["G1"], [], 5, resolver=_resolver(_ROWS))


def test_deprecated_ids_used_when_no_global_ids():
    sel = resolve_selection(object(), 1, [], [55, 66], 5, resolver=_resolver(_ROWS))
    assert sel.entity_ids == [55, 66]


def test_disagreeing_integer_ids_are_rejected_not_overriding():
    # GlobalIds resolve to {101}; deprecated ids claim {999} -> conflict.
    with pytest.raises(SelectionConflictError):
        resolve_selection(object(), 1, ["G1"], [999], 5, resolver=_resolver(_ROWS))


def test_agreeing_integer_ids_are_accepted():
    sel = resolve_selection(object(), 1, ["G1", "G2"], [101, 102], 5, resolver=_resolver(_ROWS))
    assert sel.entity_ids == [101, 102]
