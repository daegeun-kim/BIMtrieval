"""`execute_sql` attaches viewer match identities for entity operations
(tasks/task13.md §2).

Offline: the entity operations are monkeypatched, so no PostgreSQL is touched.
This covers the wiring — that a COUNT operation, which previously returned only
`facts={"count": n}` and zero identities, now also carries the GlobalIds the
viewer needs to highlight what was counted.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.query.sql import dispatch
from app.query.sql import entities as entity_ops
from app.query.sql.schemas import CountEntitiesPlan, SqlOperation


@pytest.fixture()
def plan():
    return CountEntitiesPlan(source_model_id=1, entity_classes=["IfcDoor"], filters=None)


@pytest.fixture()
def stub_entities(monkeypatch):
    """Stub the DB layer; record the limit the dispatcher asks for."""
    calls = {}

    def _install(total: int, returned: int, histogram: dict[str, int]):
        def _count(_s, _p):
            return total

        def _identities(_s, _model_id, _classes, _filters, limit):
            calls["limit"] = limit
            rows = [
                SimpleNamespace(global_id=f"GID-{i}", ifc_class="IfcDoor") for i in range(returned)
            ]
            return entity_ops.ViewerIdentityResult(
                rows=rows, exact_total=total, truncated=total > returned
            )

        monkeypatch.setattr(entity_ops, "count_entities", _count)
        monkeypatch.setattr(entity_ops, "select_viewer_identities", _identities)
        monkeypatch.setattr(entity_ops, "count_by_class", lambda *_a: histogram)
        return calls

    return _install


def test_count_operation_now_carries_viewer_identities(plan, stub_entities):
    """ "How many doors are there?" -> exact count AND the matching GlobalIds."""
    stub_entities(total=205, returned=205, histogram={"IfcDoor": 205})

    res = dispatch.execute_sql(object(), SqlOperation.COUNT_ENTITIES, plan)

    assert res.facts == {"count": 205}
    assert res.exact_total == 205
    assert len(res.viewer_global_ids) == 205
    assert res.viewer_matches_total == 205
    assert res.viewer_matches_truncated is False
    assert res.class_histogram == {"IfcDoor": 205}
    assert res.warnings == []


def test_count_uses_the_configured_viewer_cap_as_the_identity_limit(plan, stub_entities):
    calls = stub_entities(total=10, returned=10, histogram={"IfcDoor": 10})
    dispatch.execute_sql(object(), SqlOperation.COUNT_ENTITIES, plan)
    assert calls["limit"] == 2000


def test_an_explicit_viewer_limit_overrides_the_setting(plan, stub_entities):
    calls = stub_entities(total=10, returned=10, histogram={"IfcDoor": 10})
    dispatch.execute_sql(object(), SqlOperation.COUNT_ENTITIES, plan, viewer_match_limit=5)
    assert calls["limit"] == 5


def test_exact_count_survives_viewer_truncation(plan, stub_entities):
    """Above the cap the viewer gets 2,000 ids but the count stays exact."""
    stub_entities(total=5000, returned=2000, histogram={"IfcDoor": 5000})

    res = dispatch.execute_sql(object(), SqlOperation.COUNT_ENTITIES, plan)

    assert res.facts == {"count": 5000}  # not reduced
    assert res.exact_total == 5000
    assert len(res.viewer_global_ids) == 2000
    assert res.viewer_matches_truncated is True
    # The class summary is computed over the FULL set, not the truncated slice.
    assert res.class_histogram == {"IfcDoor": 5000}
    assert any("5000 objects match" in w for w in res.warnings)
    assert any("exact total above is unaffected" in w for w in res.warnings)


def test_hybrid_suppresses_identity_retrieval(plan, monkeypatch):
    """In hybrid the highlighted set is the combined outcome, so this path's raw
    match set must not be fetched or reported (it would mislead)."""
    monkeypatch.setattr(entity_ops, "count_entities", lambda *_a: 205)
    monkeypatch.setattr(
        entity_ops,
        "select_viewer_identities",
        lambda *_a, **_kw: pytest.fail("hybrid must not run identity retrieval"),
    )

    res = dispatch.execute_sql(
        object(), SqlOperation.COUNT_ENTITIES, plan, with_viewer_identities=False
    )

    assert res.exact_total == 205
    assert res.viewer_matches_total is None
    assert res.viewer_global_ids == []
