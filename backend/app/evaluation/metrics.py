"""Retrieval precision/recall metrics (spec_v002 Section 21).

Pure functions over canonical ID sets. "Retrieval precision and recall are
evaluation metrics, not training requirements" — they measure whether a
route returned the correct existing IFC records, given a benchmark case's
`relevant_canonical_ids`.
"""

from __future__ import annotations


def precision(retrieved_ids: list[int], relevant_ids: list[int]) -> float | None:
    if not retrieved_ids:
        return None
    relevant_set = set(relevant_ids)
    hits = sum(1 for rid in retrieved_ids if rid in relevant_set)
    return hits / len(retrieved_ids)


def recall(retrieved_ids: list[int], relevant_ids: list[int]) -> float | None:
    if not relevant_ids:
        return None
    retrieved_set = set(retrieved_ids)
    hits = sum(1 for rid in relevant_ids if rid in retrieved_set)
    return hits / len(relevant_ids)
