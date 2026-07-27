"""Semantic preservation as obligation accounting (task28 §7, task30 §5).

Validation elsewhere proves a plan is internally well formed — real ids,
compatible uses, applicable subjects, compilable nodes. This proves the plan
still expresses what the user meant.

Task 30 changes what that proof rests on. The v5 original compared words: it
asked whether a bound concept's label accounted for the tokens of a requirement
phrase, which punished ordinary wording and excused nothing that mattered.
Here the unit is the OBLIGATION — one per material decision the resolver made,
each carrying its type — and the question is whether every required one is
either discharged by a real backend identity or explicitly disposed as
unsupported or ambiguous.

That is strictly stronger than word overlap. An unbound slot has no identity at
all, so nothing can be quietly substituted for it; and a disposition is derived
from the actual binding rather than asserted by a model, so the plan cannot
claim to have bound something it did not.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.llm.schemas_v2 import LogicalPlan, ViewerSetPolicy
from app.llm.schemas_v5 import ResolvedIntent, VisualizationIntent
from app.query.binding.obligations import Obligation, ObligationKind, PlanSkeleton
from app.query.binding.validate_v2 import PlanValidation, ValidationIssue

__all__ = [
    "PreservationReport",
    "validate_semantic_preservation",
]


@dataclass
class PreservationReport:
    """Typed preservation issues, in the shape the per-part gates consume."""

    issues: list[ValidationIssue] = field(default_factory=list)
    #: Obligations discharged by a real identity.
    bound: int = 0
    #: Obligations honestly reported unsupported or ambiguous.
    disposed: int = 0

    @property
    def ok(self) -> bool:
        return not self.issues

    def correctable(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.correctable]

    def for_part(self, part_id: str) -> list[ValidationIssue]:
        return [i for i in self.issues if i.part_id == part_id]

    def to_payload(self) -> dict[str, Any]:
        return {
            "issues": [i.to_payload() for i in self.issues],
            "correctable": len(self.correctable()),
            "bound": self.bound,
            "disposed": self.disposed,
        }


def validate_semantic_preservation(
    intent: ResolvedIntent,
    obligations: list[Obligation],
    skeleton: PlanSkeleton,
    plan: LogicalPlan,
    validation: PlanValidation | None = None,
) -> PreservationReport:
    """Prove every required obligation is discharged or honestly disposed."""
    report = PreservationReport()
    plan_parts = {p.part_id: p for p in plan.answer_parts}

    _check_totality(intent, obligations, report)
    _check_obligations(obligations, plan_parts, report)
    _check_no_invented_narrowing(obligations, skeleton, plan, report)
    _check_visualization(intent, plan_parts, report)
    _check_blocking_slots(intent, plan, plan_parts, report)
    _ = validation
    return report


def _check_totality(
    intent: ResolvedIntent, obligations: list[Obligation], report: PreservationReport
) -> None:
    """Every material intent handle became exactly one obligation (§3)."""
    handles = [h for h in intent.handles() if not h.startswith(tuple())]
    part_ids = {p.part_id for p in intent.parts}
    expected = [h for h in handles if h not in part_ids]
    covered = [o.intent_handle for o in obligations]
    missing = [h for h in expected if h not in covered]
    for handle in missing:
        report.issues.append(
            ValidationIssue(
                "preservation",
                "INTENT_HANDLE_LOST",
                f"the resolved decision {handle!r} produced no obligation, so nothing "
                "downstream can answer or refuse it",
                correctable=False,
            )
        )
    duplicated = {h for h in covered if covered.count(h) > 1}
    for handle in sorted(duplicated):
        report.issues.append(
            ValidationIssue(
                "preservation",
                "INTENT_HANDLE_DUPLICATED",
                f"the resolved decision {handle!r} became more than one obligation",
                correctable=False,
            )
        )


def _check_obligations(
    obligations: list[Obligation],
    plan_parts: dict[str, Any],
    report: PreservationReport,
) -> None:
    """Bound by a real identity, or explicitly disposed. Never silent."""
    for obligation in obligations:
        if obligation.satisfied:
            report.bound += 1
            continue
        if obligation.explicitly_disposed:
            report.disposed += 1
            if not obligation.required:
                continue
            # An unsupported REQUIRED obligation is honest, but it must reach the
            # user as a limitation rather than vanish, so the part it belongs to
            # may not be reported as a complete answer.
            if obligation.part_id in plan_parts and obligation.kind in (
                ObligationKind.TARGET,
                ObligationKind.FILTER,
                ObligationKind.SCOPE,
                ObligationKind.RELATIONSHIP,
            ):
                report.issues.append(
                    ValidationIssue(
                        "preservation",
                        "OBLIGATION_UNSUPPORTED",
                        f"{obligation.retrieval_text!r} is not recorded in this model"
                        + (
                            f": {obligation.disposition_note}"
                            if obligation.disposition_note
                            else ""
                        ),
                        part_id=obligation.part_id,
                        requirement_id=obligation.obligation_id,
                        correctable=False,
                    )
                )
            continue
        if not obligation.required:
            continue
        report.issues.append(
            ValidationIssue(
                "preservation",
                "OBLIGATION_UNACCOUNTED",
                f"{obligation.retrieval_text!r} was neither bound to a recorded "
                "concept nor reported as unavailable",
                part_id=obligation.part_id,
                requirement_id=obligation.obligation_id,
                correctable=True,
            )
        )


def _check_no_invented_narrowing(
    obligations: list[Obligation],
    skeleton: PlanSkeleton,
    plan: LogicalPlan,
    report: PreservationReport,
) -> None:
    """Every narrowing node traces to a condition the user stated.

    Assembly builds filters only from filter slots, so this cannot normally
    fail; it is kept as a structural guard so a future change to assembly cannot
    reintroduce a narrowing node with no provenance.
    """
    filter_nodes = {
        (s.part_id, s.node_id)
        for s in skeleton.slots
        if s.node_kind == "filter"
        and any(
            o.obligation_id == s.obligation_id and o.kind is ObligationKind.FILTER
            for o in obligations
        )
    }
    for part in plan.answer_parts:
        for node in part.filters:
            if (part.part_id, node.node_id) in filter_nodes:
                continue
            report.issues.append(
                ValidationIssue(
                    "preservation",
                    "INTENT_CONSTRAINT_INVENTED",
                    f"filter node {node.node_id} ({node.semantic_id}) narrows the "
                    "answer but matches no condition in the resolved request",
                    part_id=part.part_id,
                    node_id=node.node_id,
                    correctable=True,
                )
            )


def _check_visualization(
    intent: ResolvedIntent,
    plan_parts: dict[str, Any],
    report: PreservationReport,
) -> None:
    """The requested visualization survives into the plan's viewer sets."""
    if intent.visualization is VisualizationIntent.NONE:
        return
    wanted = [p for p in intent.parts if p.highlightable and p.part_id in plan_parts]
    if not wanted:
        return
    if all(
        plan_parts[p.part_id].viewer_set is ViewerSetPolicy.NONE for p in wanted
    ):
        report.issues.append(
            ValidationIssue(
                "preservation",
                "INTENT_VISUALIZATION_DROPPED",
                "the request asks for the matching objects to be shown, but no "
                "answer part selects a viewer set",
                part_id=wanted[0].part_id,
                correctable=True,
            )
        )


def _check_blocking_slots(
    intent: ResolvedIntent,
    plan: LogicalPlan,
    plan_parts: dict[str, Any],
    report: PreservationReport,
) -> None:
    """A blocking unresolved slot cannot coexist with a ready result."""
    if plan.needs_clarification:
        return
    for slot in intent.blocking_slots():
        if slot.part_id is None or slot.part_id not in plan_parts:
            continue
        report.issues.append(
            ValidationIssue(
                "preservation",
                "UNRESOLVED_SLOT_EXECUTED",
                f"{slot.question} — this part cannot be answered as though a "
                "reading had been chosen",
                part_id=slot.part_id,
                correctable=False,
            )
        )
