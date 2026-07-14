"""Canonical-ID combination semantics (spec_v005 §9).

Pure functions over ordered id lists and RAG score maps — no database access,
so they are exhaustively unit-testable offline. Every combination is governed
by canonical entity ids (spec_v005 §9, acceptance criterion 4); RAG scores stay
internal and are only used for ordering, never surfaced as a comparable score
across SQL and RAG (§9 rank behavior).

Key invariant: an empty intersection is reported as empty. It is NEVER silently
turned into a union (spec_v005 §9, acceptance criterion 5).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CombinationOutcome:
    primary_ids: list[int] = field(default_factory=list)
    context_ids: list[int] = field(default_factory=list)
    groups: dict[str, int] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


def _dedupe(ids: list[int]) -> list[int]:
    seen: set[int] = set()
    out: list[int] = []
    for i in ids:
        if i not in seen:
            seen.add(i)
            out.append(i)
    return out


def intersection(sql_ids: list[int], rag_ids: list[int]) -> CombinationOutcome:
    sql_ordered = _dedupe(sql_ids)
    rag_set = set(rag_ids)
    both = [i for i in sql_ordered if i in rag_set]
    out = CombinationOutcome(
        primary_ids=both,
        groups={"both": len(both), "sql_total": len(sql_ordered), "rag_total": len(set(rag_ids))},
    )
    if not both:
        out.notes.append(
            "no object satisfied both the exact and the semantic constraint "
            "(empty intersection — not widened to a union)"
        )
    return out


def union(sql_ids: list[int], rag_ids: list[int]) -> CombinationOutcome:
    """Preserve separate evidence groups (spec_v005 §9): exact-only, semantic-only,
    and both. Order: SQL matches first (exact), then semantic-only additions."""
    sql_ordered = _dedupe(sql_ids)
    rag_ordered = _dedupe(rag_ids)
    sql_set = set(sql_ordered)
    rag_set = set(rag_ordered)
    both = [i for i in sql_ordered if i in rag_set]
    sql_only = [i for i in sql_ordered if i not in rag_set]
    rag_only = [i for i in rag_ordered if i not in sql_set]
    primary = _dedupe(sql_ordered + rag_only)
    return CombinationOutcome(
        primary_ids=primary,
        groups={
            "both": len(both),
            "sql_only": len(sql_only),
            "rag_only": len(rag_only),
        },
        notes=[],
    )


def sql_filter_of_rag(
    sql_ids: list[int], rag_ids_ranked: list[int]
) -> CombinationOutcome:
    """Semantic candidates restricted by an exact SQL constraint (SQL as boolean
    eligibility). Preserve RAG ranking order (spec_v005 §9 rank behavior)."""
    sql_set = set(sql_ids)
    kept = [i for i in _dedupe(rag_ids_ranked) if i in sql_set]
    out = CombinationOutcome(
        primary_ids=kept,
        groups={"rag_candidates": len(set(rag_ids_ranked)), "kept_after_sql_filter": len(kept)},
    )
    if not kept:
        out.notes.append("no semantic candidate also satisfied the exact SQL constraint")
    return out


def rag_rank_of_sql(
    sql_ids: list[int], rag_score_by_id: dict[int, float]
) -> CombinationOutcome:
    """Exact SQL set, ordered by semantic relevance. Objects with a RAG score come
    first (by score desc); the rest keep their original SQL order afterwards.
    Exact constraints remain boolean eligibility, not vector weights (§9)."""
    sql_ordered = _dedupe(sql_ids)
    scored = [i for i in sql_ordered if i in rag_score_by_id]
    scored.sort(key=lambda i: rag_score_by_id[i], reverse=True)
    unscored = [i for i in sql_ordered if i not in rag_score_by_id]
    return CombinationOutcome(
        primary_ids=scored + unscored,
        groups={"sql_total": len(sql_ordered), "with_rag_score": len(scored)},
    )
