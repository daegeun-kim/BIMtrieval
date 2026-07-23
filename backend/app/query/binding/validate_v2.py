"""Deterministic plan validation: the ten §9.1 layers with per-part gates.

Every layer emits typed issues carrying a stable failure code from the task26
taxonomy (§2) and whether the defect is MECHANICAL (correctable by the one
targeted corrective call) or an honest limitation that must never be
"corrected" into a broader answer (§9.4).

The proof-carrying chain (§3.4) is walked here: requirement -> selected
concept -> permitted use -> applicable subject -> accessor -> dry-compiled
physical node -> result-set contribution. A model cannot silence the ledger by
mentioning a concept; only a compatible node contribution discharges a
requirement (§6.4).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from sqlalchemy.orm import Session

from app.llm.schemas_v2 import (
    AnswerPartV2,
    DispositionKind,
    LogicalPlan,
    LogicalOperator,
    RequirementDisposition,
    ResultKind,
    ViewerSetPolicy,
)
from app.query.binding.compile_v2 import CompiledPart, CompileFailure, compile_part
from app.query.binding.ledger_v2 import (
    LedgerRequirement,
    LedgerV2,
    RequirementRole,
    ResolutionState,
)
from app.query.binding.lexical import identifier_tokens, singularize, stems_match
from app.query.semantic.manifest_v002.schema import Capability, ManifestV002

__all__ = [
    "GateStateV2",
    "ValidationIssue",
    "PartVerdict",
    "PlanValidation",
    "validate_plan",
]


class GateStateV2(str, Enum):
    READY = "ready"
    PARTIAL_EXECUTABLE = "partial_executable"
    CORRECTABLE_BINDING_GAP = "correctable_binding_gap"
    NEEDS_CLARIFICATION = "needs_clarification"
    UNAVAILABLE = "unavailable"
    INVALID = "invalid"


@dataclass(frozen=True)
class ValidationIssue:
    layer: str
    code: str
    detail: str
    part_id: str | None = None
    node_id: str | None = None
    requirement_id: str | None = None
    correctable: bool = False

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"layer": self.layer, "code": self.code, "detail": self.detail}
        for key, value in (
            ("part_id", self.part_id),
            ("node_id", self.node_id),
            ("requirement_id", self.requirement_id),
        ):
            if value:
                payload[key] = value
        return payload


@dataclass
class PartVerdict:
    part: AnswerPartV2
    state: GateStateV2 = GateStateV2.INVALID
    issues: list[ValidationIssue] = field(default_factory=list)
    compiled: CompiledPart | None = None
    #: Requirements this part reports as honestly unavailable, with policies.
    unavailable_requirements: list[LedgerRequirement] = field(default_factory=list)


@dataclass
class PlanValidation:
    verdicts: list[PartVerdict] = field(default_factory=list)
    plan_issues: list[ValidationIssue] = field(default_factory=list)
    needs_clarification: bool = False
    clarification_question: str | None = None

    def all_issues(self) -> list[ValidationIssue]:
        out = list(self.plan_issues)
        for verdict in self.verdicts:
            out.extend(verdict.issues)
        return out

    def correctable_issues(self) -> list[ValidationIssue]:
        return [i for i in self.all_issues() if i.correctable]

    def executable_verdicts(self) -> list[PartVerdict]:
        return [
            v
            for v in self.verdicts
            if v.state in (GateStateV2.READY, GateStateV2.PARTIAL_EXECUTABLE)
        ]

    def layer_summary(self) -> dict[str, int]:
        tally: dict[str, int] = {}
        for issue in self.all_issues():
            tally[issue.layer] = tally.get(issue.layer, 0) + 1
        return tally


def _tokens(text: str) -> set[str]:
    return {singularize(t) for t in identifier_tokens(text.casefold())} - {"ifc", ""}


_ROLE_TO_NODE_KIND: dict[RequirementRole, str] = {
    RequirementRole.TARGET: "target",
    RequirementRole.FILTER: "filter",
    RequirementRole.SCOPE: "scope",
    RequirementRole.GROUP: "group",
    RequirementRole.AGGREGATE: "aggregate",
    RequirementRole.ORDER: "order",
    RequirementRole.TRAVERSAL: "traverse",
    RequirementRole.OUTPUT: "report",
}


def normalize_plan(plan: LogicalPlan, manifest: ManifestV002) -> None:
    """Deterministic pre-validation clean-ups that need no model call.

    The union field holds peer subject classes; which one the binder marks
    "primary" is arbitrary, so when the primary `target.semantic_id` is not a
    manifest id but a union member is, promote that member. This tolerates the
    common binder slip of listing every class in `union_semantic_ids` and
    leaving the primary blank, without a corrective call.
    """
    for part in plan.answer_parts:
        if manifest.get(part.target.semantic_id) is None and part.target.union_semantic_ids:
            valid = [
                uid
                for uid in part.target.union_semantic_ids
                if manifest.get(uid) is not None
            ]
            if valid:
                part.target.semantic_id = valid[0]
                part.target.union_semantic_ids = [u for u in valid[1:]]


def validate_plan(
    session: Session,
    plan: LogicalPlan,
    ledger: LedgerV2,
    manifest: ManifestV002,
    *,
    selection_entity_ids: list[int] | None = None,
    previous_scope_entity_ids: list[int] | None = None,
) -> PlanValidation:
    normalize_plan(plan, manifest)
    validation = PlanValidation(
        needs_clarification=plan.needs_clarification,
        clarification_question=plan.clarification_question,
    )

    # ---- layer 1: schema/structural ---------------------------------------
    part_ids = [p.part_id for p in plan.answer_parts]
    if len(part_ids) != len(set(part_ids)):
        validation.plan_issues.append(
            ValidationIssue("structural", "TRACE_INCOMPLETE", "duplicate part ids", correctable=True)
        )
    node_index: dict[str, dict[str, tuple[str, str]]] = {}
    for part in plan.answer_parts:
        nodes = _part_nodes(part)
        node_index[part.part_id] = nodes
        validation.plan_issues.extend(_structural_issues(part, nodes))

    # ---- layers 2-4, 6-8 per part -----------------------------------------
    verdicts = {p.part_id: PartVerdict(part=p) for p in plan.answer_parts}
    for part in plan.answer_parts:
        verdict = verdicts[part.part_id]
        verdict.issues.extend(_identity_and_capability_issues(part, manifest))
        if not any(i.layer in ("identity", "capability") for i in verdict.issues):
            verdict.issues.extend(_applicability_issues(part, manifest))
        # layer 8: dry compile only when the earlier layers passed.
        if not verdict.issues:
            try:
                verdict.compiled = compile_part(
                    session,
                    part,
                    manifest,
                    selection_entity_ids=selection_entity_ids,
                    previous_scope_entity_ids=previous_scope_entity_ids,
                )
            except CompileFailure as exc:
                verdict.issues.append(
                    ValidationIssue(
                        "dry_compile",
                        exc.code,
                        exc.detail,
                        part_id=part.part_id,
                        node_id=exc.node_id,
                        correctable=exc.code == "COMPILER_ACCESS_GAP",
                    )
                )

    # ---- layer 5: ledger contribution --------------------------------------
    contribution_issues, unavailable_map = _contribution_issues(
        plan, ledger, manifest, node_index
    )
    for issue in contribution_issues:
        if issue.part_id and issue.part_id in verdicts:
            verdicts[issue.part_id].issues.append(issue)
        else:
            validation.plan_issues.append(issue)
    for part_id, requirements in unavailable_map.items():
        if part_id in verdicts:
            verdicts[part_id].unavailable_requirements.extend(requirements)

    # ---- layer 10: result-shape / viewer-set coherence ---------------------
    for part in plan.answer_parts:
        verdicts[part.part_id].issues.extend(
            _result_shape_issues(part, verdicts[part.part_id], ledger)
        )

    # ---- per-part gate ------------------------------------------------------
    ambiguous_requirements = [
        r
        for r in ledger.required()
        if r.resolution is ResolutionState.AMBIGUOUS
    ]
    for part in plan.answer_parts:
        verdict = verdicts[part.part_id]
        verdict.state = _gate(part, verdict, ambiguous_requirements, plan)
        validation.verdicts.append(verdict)

    if not plan.answer_parts and not plan.needs_clarification:
        validation.plan_issues.append(
            ValidationIssue(
                "structural",
                "BINDING_OMISSION",
                "the plan contains no answer parts and no clarification",
                correctable=True,
            )
        )
    return validation


# ---------------------------------------------------------------------------
# Node bookkeeping
# ---------------------------------------------------------------------------


def _part_nodes(part: AnswerPartV2) -> dict[str, tuple[str, str]]:
    """{node_id: (node_kind, semantic_id)} for one part."""
    nodes: dict[str, tuple[str, str]] = {part.target.node_id: ("target", part.target.semantic_id)}
    for node in part.filters:
        nodes[node.node_id] = ("filter", node.semantic_id)
    if part.scope is not None:
        nodes[part.scope.node_id] = ("scope", part.scope.semantic_id or part.scope.kind.value)
    for node in part.traversals:
        nodes[node.node_id] = ("traverse", ",".join(node.path_semantic_ids))
    if part.group is not None:
        nodes[part.group.node_id] = ("group", part.group.semantic_id)
    if part.aggregate is not None:
        nodes[part.aggregate.node_id] = ("aggregate", part.aggregate.semantic_id or "count")
    if part.order is not None:
        nodes[part.order.node_id] = ("order", part.order.by)
    return nodes


def _structural_issues(
    part: AnswerPartV2, nodes: dict[str, tuple[str, str]]
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if len(nodes) < (
        1
        + len(part.filters)
        + (1 if part.scope else 0)
        + len(part.traversals)
        + (1 if part.group else 0)
        + (1 if part.aggregate else 0)
        + (1 if part.order else 0)
    ):
        issues.append(
            ValidationIssue(
                "structural",
                "TRACE_INCOMPLETE",
                f"part {part.part_id} has duplicate node ids",
                part_id=part.part_id,
                correctable=True,
            )
        )
    if part.result_kind is ResultKind.SAMPLE and part.limit != 1:
        issues.append(
            ValidationIssue(
                "structural",
                "RESULT_SET_MISMATCH",
                "a sample result requires limit 1",
                part_id=part.part_id,
                correctable=True,
            )
        )
    if part.result_kind is ResultKind.SCALAR and part.aggregate is None:
        issues.append(
            ValidationIssue(
                "structural",
                "UNSUPPORTED_LOGICAL_SHAPE",
                "a scalar result requires an aggregate node",
                part_id=part.part_id,
                correctable=True,
            )
        )
    if part.result_kind is ResultKind.GRAPH_ENDPOINTS and not part.traversals:
        issues.append(
            ValidationIssue(
                "structural",
                "UNSUPPORTED_LOGICAL_SHAPE",
                "a graph result requires a traversal node",
                part_id=part.part_id,
                correctable=True,
            )
        )
    if part.order is not None and part.group is None and part.order.by == "aggregate":
        issues.append(
            ValidationIssue(
                "structural",
                "UNSUPPORTED_LOGICAL_SHAPE",
                "ordering by aggregate requires a group node",
                part_id=part.part_id,
                correctable=True,
            )
        )
    return issues


# ---------------------------------------------------------------------------
# Layers 2-4
# ---------------------------------------------------------------------------


def _identity_and_capability_issues(
    part: AnswerPartV2, manifest: ManifestV002
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    all_ids = None  # computed lazily

    def _check_exists(semantic_id: str, node_id: str) -> Any | None:
        nonlocal all_ids
        record = manifest.get(semantic_id)
        if record is None:
            issues.append(
                ValidationIssue(
                    "identity",
                    "BINDING_OMISSION",
                    f"{semantic_id!r} is not a semantic id of the active manifest",
                    part_id=part.part_id,
                    node_id=node_id,
                    correctable=True,
                )
            )
        return record

    target = _check_exists(part.target.semantic_id, part.target.node_id)
    if isinstance(target, Capability):
        if not target.supports_use("target"):
            issues.append(
                ValidationIssue(
                    "capability",
                    "LEDGER_ROLE_ERROR",
                    f"{target.semantic_id} cannot be a target (uses: {', '.join(target.uses)})",
                    part_id=part.part_id,
                    node_id=part.target.node_id,
                    correctable=True,
                )
            )
        if not target.executable:
            issues.append(
                ValidationIssue(
                    "capability",
                    "MANIFEST_CAPABILITY_GAP",
                    f"{target.semantic_id} is descriptive only: {target.limitation}",
                    part_id=part.part_id,
                    node_id=part.target.node_id,
                )
            )
    for union_id in part.target.union_semantic_ids:
        _check_exists(union_id, part.target.node_id)

    for node in part.filters:
        capability = _check_exists(node.semantic_id, node.node_id)
        if not isinstance(capability, Capability):
            continue
        if not capability.executable:
            issues.append(
                ValidationIssue(
                    "capability",
                    "MANIFEST_CAPABILITY_GAP",
                    f"{capability.semantic_id} is descriptive only: {capability.limitation}",
                    part_id=part.part_id,
                    node_id=node.node_id,
                )
            )
            continue
        if not capability.supports_use("filter"):
            issues.append(
                ValidationIssue(
                    "capability",
                    "LEDGER_ROLE_ERROR",
                    f"{capability.semantic_id} cannot filter",
                    part_id=part.part_id,
                    node_id=node.node_id,
                    correctable=True,
                )
            )
        if not capability.supports_operator(node.operator.value):
            issues.append(
                ValidationIssue(
                    "capability",
                    "UNSUPPORTED_LOGICAL_SHAPE",
                    f"{capability.semantic_id} does not support {node.operator.value}",
                    part_id=part.part_id,
                    node_id=node.node_id,
                    correctable=True,
                )
            )

    if part.scope is not None and part.scope.semantic_id:
        _check_exists(part.scope.semantic_id, part.scope.node_id)
    if part.group is not None:
        group = _check_exists(part.group.semantic_id, part.group.node_id)
        if isinstance(group, Capability) and not group.supports_use("group"):
            issues.append(
                ValidationIssue(
                    "capability",
                    "LEDGER_ROLE_ERROR",
                    f"{group.semantic_id} cannot group",
                    part_id=part.part_id,
                    node_id=part.group.node_id,
                    correctable=True,
                )
            )
    if part.aggregate is not None and part.aggregate.semantic_id:
        aggregate = _check_exists(part.aggregate.semantic_id, part.aggregate.node_id)
        if isinstance(aggregate, Capability) and not aggregate.supports_use("aggregate"):
            issues.append(
                ValidationIssue(
                    "capability",
                    "COVERAGE_PROOF_GAP",
                    f"{aggregate.semantic_id} cannot be aggregated (unproven unit contract)",
                    part_id=part.part_id,
                    node_id=part.aggregate.node_id,
                )
            )
    for semantic_id in part.projections:
        projection = _check_exists(semantic_id, part.part_id)
        if isinstance(projection, Capability) and not projection.supports_use("report"):
            issues.append(
                ValidationIssue(
                    "capability",
                    "LEDGER_ROLE_ERROR",
                    f"{projection.semantic_id} cannot be reported",
                    part_id=part.part_id,
                    correctable=True,
                )
            )
    for node in part.traversals:
        for path_id in node.path_semantic_ids:
            record = manifest.traversals.get(path_id)
            if record is None:
                issues.append(
                    ValidationIssue(
                        "identity",
                        "BINDING_OMISSION",
                        f"{path_id!r} is not a traversal contract of the active manifest",
                        part_id=part.part_id,
                        node_id=node.node_id,
                        correctable=True,
                    )
                )
    return issues


def _applicability_issues(part: AnswerPartV2, manifest: ManifestV002) -> list[ValidationIssue]:
    """Layer 4: a real field bound to an incompatible class fails BEFORE SQL."""
    issues: list[ValidationIssue] = []
    target = manifest.capabilities.get(part.target.semantic_id)
    if target is None or target.kind != "class" or not target.ifc_class:
        return issues
    family = set(family_closure_safe(target.ifc_class, manifest))

    def _check(capability_id: str, node_id: str | None) -> None:
        capability = manifest.capabilities.get(capability_id)
        if capability is None or capability.kind != "field":
            return
        subjects = {
            a.subject[4:] if a.subject.startswith("cls:") else a.subject
            for a in capability.applicability
        }
        if subjects and not (subjects & family):
            issues.append(
                ValidationIssue(
                    "applicability",
                    "MANIFEST_APPLICABILITY_ERROR",
                    f"{capability_id} applies to {sorted(subjects)[:4]}, not to the "
                    f"{target.ifc_class} family — selecting it would validate a query "
                    "that can only return a false zero",
                    part_id=part.part_id,
                    node_id=node_id,
                    correctable=True,
                )
            )

    for node in part.filters:
        _check(node.semantic_id, node.node_id)
    if part.group is not None:
        _check(part.group.semantic_id, part.group.node_id)
    if part.aggregate is not None and part.aggregate.semantic_id:
        _check(part.aggregate.semantic_id, part.aggregate.node_id)
    for semantic_id in part.projections:
        _check(semantic_id, None)

    # Layer 7 lives here too: the first hop must be traversable FROM the target.
    for node in part.traversals:
        first = manifest.traversals.get(node.path_semantic_ids[0])
        if first is not None and family and not (set(first.from_classes) & family):
            issues.append(
                ValidationIssue(
                    "traversal",
                    "MANIFEST_APPLICABILITY_ERROR",
                    f"{first.semantic_id} does not start from the {target.ifc_class} family",
                    part_id=part.part_id,
                    node_id=node.node_id,
                    correctable=True,
                )
            )
    return issues


def family_closure_safe(ifc_class: str, manifest: ManifestV002) -> tuple[str, ...]:
    from app.query.semantic.roles import family_closure

    try:
        family = family_closure(
            ifc_class, manifest.present_classes(), manifest.ifc_schema or "IFC2X3"
        )
        return tuple(family) if family else (ifc_class,)
    except Exception:  # noqa: BLE001 - ontology issues degrade to the class itself
        return (ifc_class,)


# ---------------------------------------------------------------------------
# Layer 5: contribution, not mention (§6.4)
# ---------------------------------------------------------------------------


def _contribution_issues(
    plan: LogicalPlan,
    ledger: LedgerV2,
    manifest: ManifestV002,
    node_index: dict[str, dict[str, tuple[str, str]]],
) -> tuple[list[ValidationIssue], dict[str, list[LedgerRequirement]]]:
    issues: list[ValidationIssue] = []
    unavailable_map: dict[str, list[LedgerRequirement]] = {}
    by_requirement: dict[str, list[RequirementDisposition]] = {}
    for disposition in plan.dispositions:
        by_requirement.setdefault(disposition.requirement_id, []).append(disposition)

    for requirement in ledger.required():
        dispositions = by_requirement.get(requirement.requirement_id, [])
        if not dispositions:
            issues.append(
                ValidationIssue(
                    "contribution",
                    "BINDING_OMISSION",
                    f"required requirement {requirement.requirement_id} "
                    f"({requirement.source_text!r}) has no disposition",
                    requirement_id=requirement.requirement_id,
                    correctable=True,
                )
            )
            continue
        disposition = dispositions[0]

        if disposition.disposition is DispositionKind.TOPIC_CONTEXT:
            if requirement.role not in (RequirementRole.TOPIC_CONTEXT,):
                issues.append(
                    ValidationIssue(
                        "contribution",
                        "LEDGER_ROLE_ERROR",
                        f"{requirement.source_text!r} is a {requirement.role.value} "
                        "requirement; a topic-context disposition cannot discharge it",
                        requirement_id=requirement.requirement_id,
                        part_id=disposition.part_id,
                        correctable=True,
                    )
                )
            continue

        if disposition.disposition is DispositionKind.REDUNDANT_WITH:
            other = disposition.redundant_with_requirement_id
            if not other or ledger.requirement(other) is None:
                issues.append(
                    ValidationIssue(
                        "contribution",
                        "BINDING_OMISSION",
                        f"redundant_with on {requirement.requirement_id} names no valid "
                        "other requirement",
                        requirement_id=requirement.requirement_id,
                        correctable=True,
                    )
                )
            continue

        if disposition.disposition in (DispositionKind.AMBIGUOUS, DispositionKind.UNAVAILABLE):
            if requirement.resolution is ResolutionState.RESOLVABLE and requirement.role in (
                RequirementRole.TARGET,
                RequirementRole.FILTER,
                RequirementRole.SCOPE,
                RequirementRole.GROUP,
            ):
                issues.append(
                    ValidationIssue(
                        "contribution",
                        "BINDING_OMISSION",
                        f"{requirement.source_text!r} resolved against the manifest but was "
                        f"declared {disposition.disposition.value}; bind it or explain a "
                        "mechanical reason",
                        requirement_id=requirement.requirement_id,
                        correctable=True,
                    )
                )
            elif disposition.disposition is DispositionKind.UNAVAILABLE:
                part_id = disposition.part_id or requirement.part_hint
                unavailable_map.setdefault(part_id, []).append(requirement)
            continue

        # disposition == BOUND
        part_id = disposition.part_id
        nodes = node_index.get(part_id or "", {})
        referenced = [nodes[n] for n in disposition.node_ids if n in nodes]
        if not referenced:
            issues.append(
                ValidationIssue(
                    "contribution",
                    "BINDING_OMISSION",
                    f"{requirement.source_text!r} is declared bound but references no "
                    "existing logical node",
                    requirement_id=requirement.requirement_id,
                    part_id=part_id,
                    correctable=True,
                )
            )
            continue
        expected_kind = _ROLE_TO_NODE_KIND.get(requirement.role)
        kinds = {kind for kind, _sid in referenced}
        satisfied = _kind_satisfied(requirement.role, kinds, plan, part_id)
        if expected_kind and not satisfied:
            issues.append(
                ValidationIssue(
                    "contribution",
                    "LEDGER_ROLE_ERROR",
                    f"{requirement.source_text!r} requires a {expected_kind} contribution; "
                    f"the referenced nodes are {sorted(kinds)}",
                    requirement_id=requirement.requirement_id,
                    part_id=part_id,
                    correctable=True,
                )
            )
            continue

        # Token coverage for phrase requirements: every content token of the
        # phrase must be covered by the bound concepts/values, or the qualifier
        # was silently dropped (the "205 doors on the second floor" defect).
        if requirement.role in (RequirementRole.TARGET, RequirementRole.FILTER):
            uncovered = _uncovered_tokens(requirement, referenced, plan, part_id, manifest)
            if uncovered:
                issues.append(
                    ValidationIssue(
                        "contribution",
                        "BINDING_OMISSION",
                        f"the words {sorted(uncovered)} of {requirement.source_text!r} are "
                        "not accounted for by the bound concepts",
                        requirement_id=requirement.requirement_id,
                        part_id=part_id,
                        correctable=True,
                    )
                )

    # Invented narrowing nodes: every filter node must be referenced by a bound
    # disposition (its provenance), §9.1 layer 5.
    referenced_nodes: set[tuple[str | None, str]] = set()
    for disposition in plan.dispositions:
        for node_id in disposition.node_ids:
            referenced_nodes.add((disposition.part_id, node_id))
    for part in plan.answer_parts:
        for node in part.filters:
            if (part.part_id, node.node_id) not in referenced_nodes:
                issues.append(
                    ValidationIssue(
                        "contribution",
                        "BINDING_OMISSION",
                        f"filter node {node.node_id} ({node.semantic_id}) has no ledger "
                        "provenance — narrowing conditions cannot be invented",
                        part_id=part.part_id,
                        node_id=node.node_id,
                        correctable=True,
                    )
                )
    return issues, unavailable_map


def _kind_satisfied(
    role: RequirementRole, kinds: set[str], plan: LogicalPlan, part_id: str | None
) -> bool:
    if role is RequirementRole.TARGET:
        # A phrase target decomposes: "parking spaces" -> target IfcSpace + a
        # filter; "what rating" -> a group axis. The requirement is discharged
        # by ANY narrowing/grouping/target contribution — the separate
        # token-coverage check is what actually catches a dropped qualifier, so
        # the node kind here stays permissive to avoid needless corrections.
        return bool(kinds & {"target", "filter", "traverse", "group", "aggregate"})
    if role is RequirementRole.FILTER:
        return bool(kinds & {"filter", "scope", "traverse", "target", "group"})
    if role is RequirementRole.SCOPE:
        return "scope" in kinds
    if role is RequirementRole.GROUP:
        return "group" in kinds
    if role is RequirementRole.ORDER:
        part = next((p for p in plan.answer_parts if p.part_id == part_id), None)
        return part is not None and part.order is not None and part.limit is not None
    if role is RequirementRole.AGGREGATE:
        return "aggregate" in kinds
    if role is RequirementRole.TRAVERSAL:
        return "traverse" in kinds
    if role is RequirementRole.OUTPUT:
        part = next((p for p in plan.answer_parts if p.part_id == part_id), None)
        return bool(kinds & {"aggregate", "group"}) or bool(part and part.projections)
    return True


def _uncovered_tokens(
    requirement: LedgerRequirement,
    referenced: list[tuple[str, str]],
    plan: LogicalPlan,
    part_id: str | None,
    manifest: ManifestV002,
) -> set[str]:
    phrase_tokens = _tokens(requirement.source_text)
    if not phrase_tokens:
        return set()
    covering: set[str] = set()
    part = next((p for p in plan.answer_parts if p.part_id == part_id), None)
    for _kind, semantic_id in referenced:
        record = manifest.get(semantic_id.split(",")[0])
        if record is not None:
            covering |= _tokens(getattr(record, "search_text", getattr(record, "label", "")))
    if part is not None:
        # Union peer subjects cover their own words: "stairs and ramps" ->
        # union [cls:IfcStair, cls:IfcRamp] covers both "stairs" and "ramps".
        for union_id in part.target.union_semantic_ids:
            record = manifest.get(union_id)
            if record is not None:
                covering |= _tokens(getattr(record, "search_text", getattr(record, "label", "")))
        for node in part.filters:
            for value in (node.value_text, *node.value_list):
                if value:
                    covering |= _tokens(value)
        if part.evidence_theme:
            covering |= _tokens(part.evidence_theme)
    # Morphology-tolerant: "rated" is covered by "rating", "bearing" by
    # "bears". This check exists to catch a DROPPED qualifier, so a near-miss
    # on inflection must not trigger a pointless correction: two tokens of
    # length >= 4 sharing a 3-character prefix count as covered.
    def _covered(token: str) -> bool:
        for candidate in covering:
            if stems_match(token, candidate):
                return True
            if len(token) >= 4 and len(candidate) >= 4 and token[:3] == candidate[:3]:
                return True
        return False

    return {token for token in phrase_tokens if len(token) > 2 and not _covered(token)}


# ---------------------------------------------------------------------------
# Layer 10 + gate
# ---------------------------------------------------------------------------


def _result_shape_issues(
    part: AnswerPartV2, verdict: PartVerdict, ledger: LedgerV2
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if part.viewer_set is ViewerSetPolicy.CONTEXT:
        # The ledger's partial policy is the authority on whether a contextual
        # base set exists (§6.5); the prose model never invents one.
        allowed = bool(verdict.unavailable_requirements) or any(
            r.partial_policy == "return_base_set_as_context_only" for r in ledger.requirements
        )
        if not part.context_reason:
            issues.append(
                ValidationIssue(
                    "result_shape",
                    "RESULT_SET_MISMATCH",
                    "a context viewer set requires a context_reason",
                    part_id=part.part_id,
                    correctable=True,
                )
            )
        elif not allowed:
            issues.append(
                ValidationIssue(
                    "result_shape",
                    "RESULT_SET_MISMATCH",
                    "no ledger policy allows a contextual base set for this part",
                    part_id=part.part_id,
                    correctable=True,
                )
            )
    if part.viewer_set is ViewerSetPolicy.SAMPLE and part.result_kind is not ResultKind.SAMPLE:
        issues.append(
            ValidationIssue(
                "result_shape",
                "RESULT_SET_MISMATCH",
                "a sample viewer set requires a sample result",
                part_id=part.part_id,
                correctable=True,
            )
        )
    return issues


def _gate(
    part: AnswerPartV2,
    verdict: PartVerdict,
    ambiguous_requirements: list[LedgerRequirement],
    plan: LogicalPlan,
) -> GateStateV2:
    if plan.needs_clarification:
        return GateStateV2.NEEDS_CLARIFICATION
    part_ambiguous = [
        r for r in ambiguous_requirements if r.part_hint == part.part_id or len(plan.answer_parts) == 1
    ]
    hard = [i for i in verdict.issues if not i.correctable]
    correctable = [i for i in verdict.issues if i.correctable]
    if hard:
        # Honest limitations: descriptive-only concepts, unprovable units.
        return GateStateV2.UNAVAILABLE
    if correctable:
        return GateStateV2.CORRECTABLE_BINDING_GAP
    if part_ambiguous:
        return GateStateV2.NEEDS_CLARIFICATION
    if verdict.unavailable_requirements:
        return GateStateV2.PARTIAL_EXECUTABLE
    return GateStateV2.READY
