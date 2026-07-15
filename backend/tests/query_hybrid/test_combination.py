"""Canonical-ID combination semantics (spec_v005 §9). Pure, offline."""

from __future__ import annotations

from app.query.hybrid.combination import (
    intersection,
    rag_rank_of_sql,
    sql_filter_of_rag,
    union,
)


def test_intersection_keeps_only_common_ids_in_sql_order():
    out = intersection([3, 1, 2, 5], [2, 3, 9])
    assert out.primary_ids == [3, 2]
    assert out.groups["both"] == 2


def test_empty_intersection_is_not_widened_to_union():
    out = intersection([1, 2, 3], [7, 8, 9])
    assert out.primary_ids == []
    # explicit note, and NOT the union of the two sets (spec_v005 §9)
    assert any("empty intersection" in n for n in out.notes)
    assert set(out.primary_ids) != {1, 2, 3, 7, 8, 9}


def test_union_preserves_separate_groups():
    out = union([1, 2, 3], [3, 4])
    assert out.groups == {"both": 1, "sql_only": 2, "rag_only": 1}
    # exact SQL matches first, then semantic-only additions
    assert out.primary_ids == [1, 2, 3, 4]


def test_sql_filter_of_rag_keeps_rag_order_restricted_by_sql():
    # rag ranked order is [5,2,8,1]; sql eligibility is {1,2,5}
    out = sql_filter_of_rag([1, 2, 5], [5, 2, 8, 1])
    assert out.primary_ids == [5, 2, 1]
    assert out.groups["kept_after_sql_filter"] == 3


def test_sql_filter_of_rag_empty_when_no_overlap():
    out = sql_filter_of_rag([100], [5, 2, 8])
    assert out.primary_ids == []
    assert any("satisfied the exact SQL constraint" in n for n in out.notes)


def test_rag_rank_of_sql_orders_sql_by_score_then_unscored():
    scores = {2: 0.9, 5: 0.5}
    out = rag_rank_of_sql([1, 2, 5], scores)
    # 2 (0.9) and 5 (0.5) first by score desc, then unscored 1 keeps original order
    assert out.primary_ids == [2, 5, 1]
    assert out.groups["with_rag_score"] == 2


def test_dedupe_of_repeated_ids():
    out = union([1, 1, 2], [2, 2])
    assert out.primary_ids == [1, 2]
