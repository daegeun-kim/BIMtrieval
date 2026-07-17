"""Group-aware 50-example allocation (Task 17 §7).

Deterministically distributes a bounded budget of detailed primary examples
across evidence groups so that viable competing groups are represented before one
repeated class consumes the budget, and a small high-priority direct group is
included whole when it fits (the nine stairs must not be displaced by fifty
railings). Group SUMMARIES are always sent regardless of example allocation; this
only fills `allocated_examples`.
"""

from __future__ import annotations

from app.query.hybrid.groups.schemas import (
    AUTHORITY_EXACT,
    AUTHORITY_GENERAL,
    AUTHORITY_SEMANTIC,
    AUTHORITY_STRUCTURED,
    COVERAGE_BOUNDED,
    COVERAGE_COMPLETE,
    EvidenceGroup,
)

_ROLE_RANK = {"direct": 0, "supporting": 1, "context": 2, "uncertain": 3}
_AUTH_RANK = {
    AUTHORITY_EXACT: 0,
    AUTHORITY_STRUCTURED: 1,
    AUTHORITY_SEMANTIC: 2,
    AUTHORITY_GENERAL: 3,
}
_COV_RANK = {COVERAGE_COMPLETE: 0, COVERAGE_BOUNDED: 1}


def _rank_key(g: EvidenceGroup):
    return (
        _ROLE_RANK.get(g.role_hint, 3),
        _AUTH_RANK.get(g.authority, 4),
        0 if g.predicate_queryable else 1,
        _COV_RANK.get(g.coverage, 2),
        -g.similarity,
        g.group_id,
    )


def _ordered_examples(g: EvidenceGroup) -> list:
    """Within-group example order: RAG similarity when RAG ranked ids exist, else
    the deterministic representative order (§7.4-§7.5)."""
    reps = list(g.representative_entities)
    if g.candidate_entity_ids:
        rank = {eid: i for i, eid in enumerate(g.candidate_entity_ids)}
        reps.sort(key=lambda e: rank.get(e.entity_id, len(rank)))
    return reps


def allocate_examples(groups: list[EvidenceGroup], budget: int, small_group_threshold: int) -> dict:
    """Fill each group's `allocated_examples` (≤ budget total). Returns bounded
    per-group allocation metadata for trace/tests."""
    ranked = sorted(groups, key=_rank_key)
    pools = {g.group_id: _ordered_examples(g) for g in ranked}
    used: set[int] = set()
    remaining = budget
    for g in ranked:
        g.allocated_examples = []

    # Pass 1: fully include small high-priority direct groups that fit.
    for g in ranked:
        pool = [e for e in pools[g.group_id] if e.entity_id not in used]
        if (
            g.role_hint == "direct"
            and g.authority in (AUTHORITY_EXACT, AUTHORITY_STRUCTURED)
            and 0 < len(pool) <= small_group_threshold
            and len(pool) <= remaining
        ):
            for e in pool:
                g.allocated_examples.append(e)
                used.add(e.entity_id)
            remaining -= len(pool)

    # Pass 2: round-robin one example per group per round.
    progressed = True
    while remaining > 0 and progressed:
        progressed = False
        for g in ranked:
            if remaining <= 0:
                break
            for e in pools[g.group_id]:
                if e.entity_id not in used:
                    g.allocated_examples.append(e)
                    used.add(e.entity_id)
                    remaining -= 1
                    progressed = True
                    break

    meta = {}
    for g in ranked:
        shown = len(g.allocated_examples)
        total = g.exact_count if g.exact_count is not None else len(pools[g.group_id])
        g.allocation_truncated = total is not None and total > shown
        meta[g.group_id] = {"allocated": shown, "exact_or_sample_total": total}
    return {"total_allocated": budget - remaining, "per_group": meta}
