"""IFC semantic closure of a bound subject (Task 24 §3.1, §3.2).

Converts the subject candidate(s) an answer part selected into ONE authoritative
semantic result set, before anything executes.

§3.1 is the point of this module: "For an exact count or list, do not execute
semantically adjacent candidate classes and ask the final LLM to choose. One
answer part normally has one primary occurrence family."

The closure itself comes from `semantic.roles`, which derives it from IFC
inheritance. What this module adds is the per-answer-part policy around it:

- a union is honoured only when the binding explicitly declared one, and each
  member must be a result kind in its own right;
- type/style/property-definition classes never enter an occurrence result;
- a class the ontology cannot describe yields an UNRESOLVED closure rather than
  a bare-class fallback, because §3.3 forbids falling back to all entities of a
  nearby class.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.query.binding.schemas import CandidateSlate, SubjectCandidate
from app.query.semantic.roles import SchemaRole, is_result_kind

__all__ = ["SubjectClosure", "resolve_closure"]


@dataclass
class SubjectClosure:
    """The authoritative class set for one answer part."""

    #: Stored IFC classes to query. Empty when the closure could not be resolved
    #: or when the concept is genuinely absent from the model.
    ifc_classes: tuple[str, ...] = ()
    #: The schema role every member shares.
    role: str = SchemaRole.UNKNOWN.value
    #: Subject candidates this closure came from.
    subjects: tuple[SubjectCandidate, ...] = ()
    #: True when the concept was identified but the model contains none of it.
    #: A ZERO result — explicitly not the same as "unavailable" (§6).
    absent: bool = False
    #: Set when the closure cannot be established at all.
    unresolved_reason: str | None = None
    #: Non-empty for a logical (non-IFC-class) subject, e.g. `logical_floor`.
    logical_kind: str = ""
    #: Plain-language notes for the answer packet's "selected interpretation".
    notes: list[str] = field(default_factory=list)

    @property
    def resolved(self) -> bool:
        return self.unresolved_reason is None

    @property
    def executable(self) -> bool:
        """True when there is something to actually query."""
        return self.resolved and bool(self.ifc_classes)


def resolve_closure(
    slate: CandidateSlate,
    subject_candidate_id: str,
    union_candidate_ids: list[str] | tuple[str, ...] = (),
    *,
    require_result_kind: bool = True,
) -> SubjectClosure:
    """Resolve one answer part's subject binding to an authoritative class set.

    Args:
        slate: the request's candidate slate; the only source of legal IDs.
        subject_candidate_id: the part's single primary subject.
        union_candidate_ids: additional peer subjects, ONLY when the user asked
            for multiple peer concepts (§3.1).
        require_result_kind: whether the operation needs a physical/logical
            result. False for an operation that legitimately targets definition
            records (e.g. an explicit question about type definitions).
    """
    primary = slate.subject(subject_candidate_id)
    if primary is None:
        return SubjectClosure(
            unresolved_reason=(
                f"subject candidate {subject_candidate_id!r} is not in this request's slate"
            )
        )

    # A LOGICAL concept (currently only the elevation-band floor abstraction) has
    # no IFC class and no family; it is answered from the derived spatial model.
    # Resolving it here keeps §11.4's two floor concepts genuinely distinct
    # rather than collapsing one into an entity count.
    if primary.logical_kind:
        closure = SubjectClosure(
            ifc_classes=(),
            role=primary.schema_role,
            subjects=(primary,),
            absent=False,
            logical_kind=primary.logical_kind,
        )
        closure.notes = [
            f"answered as {primary.label}s derived from storey elevations, which is "
            "distinct from the raw storey entity count"
        ]
        return closure

    selected: list[SubjectCandidate] = [primary]
    for candidate_id in union_candidate_ids:
        candidate = slate.subject(candidate_id)
        if candidate is None:
            return SubjectClosure(
                unresolved_reason=(
                    f"union subject candidate {candidate_id!r} is not in this request's slate"
                )
            )
        if candidate.candidate_id != primary.candidate_id:
            selected.append(candidate)

    if require_result_kind:
        for candidate in selected:
            if not candidate.result_kind:
                # A requested occurrence may never silently become a type
                # definition, property definition, or other non-result record.
                return SubjectClosure(
                    unresolved_reason=(
                        f"{candidate.ifc_class} is a {candidate.schema_role} and cannot be "
                        "the result of a question about objects"
                    )
                )

    roles = {c.schema_role for c in selected}
    if len(roles) > 1:
        # Mixing an occurrence with a spatial structure entity in one total
        # would produce a figure that means nothing.
        return SubjectClosure(
            unresolved_reason=(
                "a single answer part cannot combine subjects of different kinds: "
                + ", ".join(sorted(roles))
            )
        )

    classes: list[str] = []
    unresolvable: list[str] = []
    for candidate in selected:
        if candidate.family_members:
            for member in candidate.family_members:
                if member not in classes:
                    classes.append(member)
        elif candidate.present:
            # Present but no ontology family: query it as itself.
            if candidate.ifc_class not in classes:
                classes.append(candidate.ifc_class)
        elif candidate.schema_role == SchemaRole.UNKNOWN.value:
            unresolvable.append(candidate.ifc_class)

    if unresolvable:
        return SubjectClosure(
            unresolved_reason=(
                "the IFC schema in use does not describe "
                + ", ".join(sorted(unresolvable))
                + ", so its family cannot be established"
            )
        )

    role = next(iter(roles), SchemaRole.UNKNOWN.value)
    closure = SubjectClosure(
        ifc_classes=tuple(classes),
        role=role,
        subjects=tuple(selected),
        # Identified correctly, but the model holds none of it. This is a ZERO
        # result and must not be reported as "unavailable" (§6).
        absent=not classes,
    )
    closure.notes = _closure_notes(selected, closure)
    return closure


def _closure_notes(selected: list[SubjectCandidate], closure: SubjectClosure) -> list[str]:
    """Plain-language description of what was actually selected (§8.2)."""
    notes: list[str] = []
    for candidate in selected:
        if not candidate.present:
            notes.append(
                f"{candidate.ifc_class} is not present in this model; "
                "this describes the model, not necessarily the real building"
            )
        elif len(candidate.family_members) > 1:
            notes.append(
                f"{candidate.ifc_class} includes its present subtypes: "
                + ", ".join(candidate.family_members)
            )
    if len(selected) > 1:
        notes.append(
            "answered as an explicit union of "
            + ", ".join(c.ifc_class for c in selected)
            + " because the question named them as peer concepts"
        )
    return notes[:6]


def operation_requires_result_kind(operation_value: str) -> bool:
    """Whether an operation's subject must be a physical/logical occurrence.

    Every current operation does: even `description` and `group_distribution`
    describe objects. This exists as an explicit hook so a future operation that
    legitimately targets definition records does not have to weaken the check
    for everything else.
    """
    return True


def is_result_role(role: str) -> bool:
    try:
        return is_result_kind(SchemaRole(role))
    except ValueError:
        return False
