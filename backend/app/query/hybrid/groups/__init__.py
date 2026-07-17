"""Evidence-group pipeline (Task 17 §3-§9).

Retrieval results are normalized into independently-selectable evidence groups —
one semantic claim per group, each with a stable id, a typed safe predicate, and
authority/coverage — so the answerer can accept/reject each group and so viewer
identities can be hydrated completely per accepted group.
"""

from app.query.hybrid.groups.allocation import allocate_examples
from app.query.hybrid.groups.builder import build_groups
from app.query.hybrid.groups.decision import resolve_group_answer
from app.query.hybrid.groups.schemas import (
    EvidenceGroup,
    GroupPredicate,
    PredicateKind,
)
from app.query.hybrid.groups.viewer import hydrate_accepted_viewer_identities

__all__ = [
    "EvidenceGroup",
    "GroupPredicate",
    "PredicateKind",
    "build_groups",
    "allocate_examples",
    "resolve_group_answer",
    "hydrate_accepted_viewer_identities",
]
