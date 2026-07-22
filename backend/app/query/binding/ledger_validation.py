"""Deterministic ledger-coverage validation (task25 §3.2, §3.3).

Replaces Task 24's `_validate_question_coverage` / `_unaccounted_tokens` token
heuristic in `validate.py`. That machinery collected question tokens, collected
"explainers" from the binding, and flagged the difference. It failed because the
explainer set included `output_field_candidate_ids`, which carry no filtering
semantics — so a binding that merely REPORTED `Pset_WallCommon.IsExternal`
appeared to account for the word "external" while executing a predicate that
counted every wall.

The rule here is about ROLE, not vocabulary:

    a required ledger item is discharged only by a disposition
    whose kind matches what the item asked for

An item with role `condition` needs `bound_condition`. `bound_output` will not
do, and no amount of prompt wording can make it. That is the structural half of
the fix; the prompt-side half is `binder_v002.md` telling the model to filter
rather than report.

Two further checks keep the ledger honest in the other direction:

- a claimed `bound_condition` must correspond to a condition that actually
  exists in the named part, so the disposition cannot be asserted without doing
  the work;
- an extra condition citing no ledger item is rejected, so the binder cannot
  invent a filter the user never asked for.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.llm.schemas import BindingPlan, LedgerDispositionKind
from app.query.binding.ledger import ConstraintLedger, LedgerItem, LedgerRole

__all__ = ["LedgerCoverage", "validate_ledger_coverage"]


#: Which disposition kinds legitimately discharge each ledger role.
#:
#: The `CONDITION -> {BOUND_CONDITION, ...}` row is the load-bearing one, and
#: `BOUND_OUTPUT` is deliberately absent from it.
_ACCEPTABLE: dict[LedgerRole, frozenset[LedgerDispositionKind]] = {
    LedgerRole.SUBJECT: frozenset(
        {
            LedgerDispositionKind.BOUND_SUBJECT,
            LedgerDispositionKind.BOUND_CONDITION,
            LedgerDispositionKind.REDUNDANT_WITH,
            LedgerDispositionKind.AMBIGUOUS,
            LedgerDispositionKind.UNAVAILABLE,
        }
    ),
    LedgerRole.CONDITION: frozenset(
        {
            LedgerDispositionKind.BOUND_CONDITION,
            # A qualifier can legitimately be part of the subject concept itself
            # ("curtain" in "curtain walls" selects IfcCurtainWall rather than
            # filtering IfcWall), so binding it as the subject is valid.
            LedgerDispositionKind.BOUND_SUBJECT,
            LedgerDispositionKind.BOUND_SCOPE,
            LedgerDispositionKind.REDUNDANT_WITH,
            LedgerDispositionKind.AMBIGUOUS,
            LedgerDispositionKind.UNAVAILABLE,
        }
    ),
    LedgerRole.SCOPE: frozenset(
        {
            LedgerDispositionKind.BOUND_SCOPE,
            LedgerDispositionKind.BOUND_CONDITION,
            LedgerDispositionKind.REDUNDANT_WITH,
            LedgerDispositionKind.AMBIGUOUS,
            LedgerDispositionKind.UNAVAILABLE,
        }
    ),
    LedgerRole.OUTPUT: frozenset(
        {
            LedgerDispositionKind.BOUND_OUTPUT,
            LedgerDispositionKind.BOUND_SUBJECT,
            LedgerDispositionKind.REDUNDANT_WITH,
            LedgerDispositionKind.AMBIGUOUS,
            LedgerDispositionKind.UNAVAILABLE,
        }
    ),
    LedgerRole.RELATIONSHIP: frozenset(
        {
            LedgerDispositionKind.BOUND_RELATIONSHIP,
            LedgerDispositionKind.REDUNDANT_WITH,
            LedgerDispositionKind.AMBIGUOUS,
            LedgerDispositionKind.UNAVAILABLE,
        }
    ),
}

#: Dispositions that mean "this request could not be answered as asked".
_HONEST_FAILURES = frozenset({LedgerDispositionKind.AMBIGUOUS, LedgerDispositionKind.UNAVAILABLE})


@dataclass
class LedgerCoverage:
    """The verdict, with enough detail to drive a corrective call (§4)."""

    #: Items with no disposition at all.
    undisposed: list[LedgerItem] = field(default_factory=list)
    #: (item, claimed disposition) pairs whose kind does not fit the item's role.
    mismatched: list[tuple[LedgerItem, LedgerDispositionKind]] = field(default_factory=list)
    #: Dispositions claiming work that the named part does not contain.
    unsupported: list[str] = field(default_factory=list)
    #: Conditions that cite no ledger item — invented filters.
    invented: list[str] = field(default_factory=list)
    #: Items honestly reported as ambiguous or unavailable.
    declared_failures: list[LedgerItem] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not (self.undisposed or self.mismatched or self.unsupported or self.invented)

    @property
    def recoverable(self) -> bool:
        """True when a targeted second attempt could plausibly succeed (§4).

        An honest `unavailable` or `ambiguous` is NOT recoverable — retrying it
        would only pressure the model into inventing something. Only a mechanical
        gap (missing, mis-kinded, or unsupported disposition) is.
        """
        return not self.ok

    def undisposed_texts(self) -> list[str]:
        return [i.text for i in self.undisposed]

    def failures(self) -> list[str]:
        out = [f"{i.text!r} ({i.role.value}) was not accounted for" for i in self.undisposed]
        out += [
            f"{i.text!r} is a {i.role.value} but was recorded as {d.value}"
            for i, d in self.mismatched
        ]
        out += self.unsupported
        out += self.invented
        return out

    def clarification(self) -> str | None:
        if self.declared_failures:
            return "; ".join(
                f"{i.text!r}: could not be resolved" for i in self.declared_failures[:3]
            )
        failures = self.failures()
        return failures[0] if failures else None


def validate_ledger_coverage(plan: BindingPlan, ledger: ConstraintLedger) -> LedgerCoverage:
    """Check that every required ledger item was properly accounted for."""
    coverage = LedgerCoverage()
    by_item = {d.item_id: d for d in plan.ledger_dispositions}
    parts = {p.part_id: p for p in plan.answer_parts}

    for item in ledger.required_items():
        disposition = by_item.get(item.item_id)
        if disposition is None:
            coverage.undisposed.append(item)
            continue

        kind = disposition.disposition
        if kind not in _ACCEPTABLE.get(item.role, frozenset()):
            coverage.mismatched.append((item, kind))
            continue

        if kind in _HONEST_FAILURES:
            coverage.declared_failures.append(item)
            continue

        problem = _verify_claim(item, disposition, parts, ledger)
        if problem:
            coverage.unsupported.append(problem)

    coverage.invented = _invented_conditions(plan, ledger)
    return coverage


def _verify_claim(item, disposition, parts, ledger: ConstraintLedger) -> str | None:
    """A claimed binding must correspond to work the plan actually contains.

    Without this, `bound_condition` degrades into a word the model can emit to
    silence the check — which is how the previous mechanism failed.
    """
    kind = disposition.disposition

    if kind is LedgerDispositionKind.REDUNDANT_WITH:
        other = disposition.redundant_with_item_id
        if not other or ledger.item(other) is None:
            return f"{item.text!r} was called redundant but cites no other ledger item"
        return None

    part = parts.get(disposition.part_id) if disposition.part_id else None
    if part is None:
        return f"{item.text!r} was recorded as {kind.value} but names no existing answer part"

    if kind is LedgerDispositionKind.BOUND_CONDITION:
        if not part.conditions:
            return (
                f"{item.text!r} was recorded as a bound condition, but part "
                f"{part.part_id!r} has no conditions"
            )
    elif kind is LedgerDispositionKind.BOUND_OUTPUT:
        if not part.output_field_candidate_ids:
            return (
                f"{item.text!r} was recorded as a bound output, but part "
                f"{part.part_id!r} reports no fields"
            )
    elif kind is LedgerDispositionKind.BOUND_RELATIONSHIP:
        if not part.relationship_candidate_id:
            return (
                f"{item.text!r} was recorded as a bound relationship, but part "
                f"{part.part_id!r} binds none"
            )
    return None


def _invented_conditions(plan: BindingPlan, ledger: ConstraintLedger) -> list[str]:
    """Every executed condition must trace back to something the user asked for.

    §3.2: an extra constraint is valid only if it cites an exact request span the
    pre-pass missed. A condition citing neither a ledger item nor a verbatim span
    of the question is an invented filter, and silently narrows the answer.
    """
    cited = {d.item_id for d in plan.ledger_dispositions}
    question = (ledger.question or "").casefold()
    out: list[str] = []

    for part in plan.answer_parts:
        for condition in part.conditions:
            if condition.inherited_from_scope:
                continue
            span = (condition.source_span or "").strip()
            if span and span.casefold() in question:
                continue
            if condition.condition_id in cited:
                continue
            out.append(
                f"condition {condition.condition_id!r} cites no ledger item and no "
                "exact span of the question"
            )
    return out
