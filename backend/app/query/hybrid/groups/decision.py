"""Apply the group-level answerer decision (Task 17 §8).

Validates every group id the answerer returned against the executed package,
fails safely on unknown/overlapping/contradictory ids (never adds viewer
identities from them), derives the accepted primary/supporting/context groups and
the viewer groups, and picks an evidence-dependent `answer_basis`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.query.hybrid.groups.schemas import (
    AUTHORITY_EXACT,
    AUTHORITY_GENERAL,
    AUTHORITY_SEMANTIC,
    AUTHORITY_STRUCTURED,
    EvidenceGroup,
)
from app.shared.types import AnswerBasis


@dataclass
class GroupDecision:
    accepted_primary: list[EvidenceGroup] = field(default_factory=list)
    accepted_supporting: list[EvidenceGroup] = field(default_factory=list)
    accepted_context: list[EvidenceGroup] = field(default_factory=list)
    rejected_ids: list[str] = field(default_factory=list)
    viewer_primary: list[EvidenceGroup] = field(default_factory=list)
    viewer_context: list[EvidenceGroup] = field(default_factory=list)
    answer_basis: AnswerBasis = AnswerBasis.INSUFFICIENT_EVIDENCE
    inference_used: bool = False
    warnings: list[str] = field(default_factory=list)

    def accepted(self) -> list[EvidenceGroup]:
        return self.accepted_primary + self.accepted_supporting + self.accepted_context


def resolve_group_answer(groups: list[EvidenceGroup], output: Any) -> GroupDecision:
    by_id = {g.group_id: g for g in groups}
    decision = GroupDecision()

    def _known(ids: list[str], label: str) -> list[str]:
        known = [i for i in ids if i in by_id]
        unknown = [i for i in ids if i not in by_id]
        if unknown:
            decision.warnings.append(f"answerer named unknown {label} group id(s): {unknown[:5]}")
        return known

    primary = _known(output.primary_group_ids, "primary")
    supporting = _known(output.supporting_group_ids, "supporting")
    context = _known(output.context_group_ids, "context")
    rejected = set(_known(output.rejected_group_ids, "rejected"))

    # Contradiction: a group both accepted and rejected → fail safe (exclude it).
    accepted_ids: list[str] = []
    for role_ids, bucket in (
        (primary, decision.accepted_primary),
        (supporting, decision.accepted_supporting),
        (context, decision.accepted_context),
    ):
        for gid in role_ids:
            if gid in rejected:
                decision.warnings.append(f"group {gid!r} both accepted and rejected; excluded")
                continue
            if gid in accepted_ids:
                continue  # a group can't hold two roles; first wins
            accepted_ids.append(gid)
            bucket.append(by_id[gid])
    decision.rejected_ids = sorted(rejected)

    accepted_set = set(accepted_ids)
    # Viewer groups must be a subset of accepted, entity-bearing groups (§9).
    for vid in _known(output.viewer_primary_group_ids, "viewer_primary"):
        g = by_id[vid]
        if vid in accepted_set and g.predicate_queryable:
            decision.viewer_primary.append(g)
    for vid in _known(output.viewer_context_group_ids, "viewer_context"):
        g = by_id[vid]
        if (
            vid in accepted_set
            and g.predicate_queryable
            and vid not in {x.group_id for x in decision.viewer_primary}
        ):
            decision.viewer_context.append(g)

    decision.inference_used = bool(output.inference_used)
    decision.answer_basis = _derive_basis(output, decision.accepted())
    return decision


def _derive_basis(output: Any, accepted: list[EvidenceGroup]) -> AnswerBasis:
    if not accepted or not output.model_evidence_sufficient:
        return AnswerBasis.INSUFFICIENT_EVIDENCE
    authorities = {g.authority for g in accepted}
    if authorities == {AUTHORITY_EXACT}:
        return AnswerBasis.EXACT_SQL
    if authorities <= {AUTHORITY_SEMANTIC, AUTHORITY_GENERAL}:
        return AnswerBasis.SEMANTIC_RETRIEVAL
    if authorities & {AUTHORITY_EXACT, AUTHORITY_STRUCTURED}:
        return AnswerBasis.HYBRID_EVIDENCE
    return AnswerBasis.SEMANTIC_RETRIEVAL
