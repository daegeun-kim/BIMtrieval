"""Complete viewer-identity hydration (Task 17 §9). Pure unit via monkeypatch —
proves the 2,000-ID cap is gone and missing ids are reported separately."""

from __future__ import annotations

import app.query.hybrid.groups.viewer as viewer_mod
from app.query.hybrid.groups.decision import GroupDecision
from app.query.hybrid.groups.execute import IdentityResult
from app.query.hybrid.groups.schemas import (
    AUTHORITY_EXACT,
    COVERAGE_COMPLETE,
    EvidenceGroup,
    GroupPredicate,
    PredicateKind,
)


def _group(gid, cls):
    return EvidenceGroup(
        group_id=gid,
        facet_id="f",
        label=f"{cls} objects",
        predicate=GroupPredicate(kind=PredicateKind.ENTITY_CLASS.value, ifc_classes=(cls,)),
        role_hint="direct",
        authority=AUTHORITY_EXACT,
        coverage=COVERAGE_COMPLETE,
        predicate_queryable=True,
    )


def test_viewer_returns_all_identities_above_old_cap(monkeypatch):
    # 5,000 identities — far above the retired 2,000 cap.
    ids = [f"g{i}" for i in range(5000)]
    monkeypatch.setattr(
        viewer_mod,
        "all_identities",
        lambda session, predicate, sid: IdentityResult(
            global_ids=ids, exact_total=5000, missing_count=0
        ),
    )
    dec = GroupDecision()
    g = _group("walls", "IfcWall")
    dec.accepted_primary.append(g)
    dec.viewer_primary.append(g)
    hyd = viewer_mod.hydrate_accepted_viewer_identities(None, dec, 1)
    assert hyd.viewer_matches_total == 5000
    assert len(hyd.primary_global_ids) == 5000
    va = hyd.viewer_actions()
    assert va.viewer_matches_truncated is False  # no truncation from a cap
    assert len(va.primary_global_ids) == 5000


def test_missing_global_ids_reported_separately(monkeypatch):
    monkeypatch.setattr(
        viewer_mod,
        "all_identities",
        lambda session, predicate, sid: IdentityResult(
            global_ids=["g1", "g2"], exact_total=5, missing_count=3
        ),
    )
    dec = GroupDecision()
    g = _group("x", "IfcX")
    dec.viewer_primary.append(g)
    hyd = viewer_mod.hydrate_accepted_viewer_identities(None, dec, 1)
    assert hyd.missing_identity_count == 3
    assert any("no usable viewer GlobalId" in w for w in hyd.warnings)  # not called truncation


def test_dedup_across_primary_and_context(monkeypatch):
    calls = {"n": 0}

    def fake(session, predicate, sid):
        calls["n"] += 1
        # both groups return an overlapping id 'shared'
        return IdentityResult(
            global_ids=["shared", f"only{calls['n']}"], exact_total=2, missing_count=0
        )

    monkeypatch.setattr(viewer_mod, "all_identities", fake)
    dec = GroupDecision()
    pg, cg = _group("p", "IfcA"), _group("c", "IfcB")
    dec.viewer_primary.append(pg)
    dec.viewer_context.append(cg)
    hyd = viewer_mod.hydrate_accepted_viewer_identities(None, dec, 1)
    assert "shared" in hyd.primary_global_ids
    assert "shared" not in hyd.context_global_ids  # deduped, primary keeps it
