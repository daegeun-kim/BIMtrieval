"""task30 — the typed transfer contract, offline.

Every test here asks one question: does a decision the resolver made survive to
the stage that must act on it, with its type intact and without any later stage
re-deriving it from words?

Fixtures are neutral and synthetic. No benchmark question, expected answer, IFC
name, real semantic ID, or model fact appears.
"""

from __future__ import annotations

import pytest

from app.llm.schemas_grounding import GroundedBindings, SlotBinding
from app.llm.schemas_v2 import LogicalOperator, ResultKind, ViewerSetPolicy
from app.llm.schemas_v5 import (
    ConstraintKind,
    ConstraintOperator,
    EvidenceKind,
    IntentConstraint,
    IntentGrouping,
    IntentOperation,
    IntentOrdering,
    IntentOutput,
    IntentPart,
    IntentProvenance,
    IntentRelationship,
    IntentTarget,
    OrderDirection,
    RelationshipDirection,
    ResolvedIntent,
    TargetCoordination,
    VisualizationIntent,
)
from app.query.binding.assemble_v5 import assemble_plan
from app.query.binding.obligations import (
    ObligationKind,
    build_obligations,
    build_plan_skeleton,
    build_recall_ledger,
)
from app.query.binding.preservation import validate_semantic_preservation

CONCEPT = "kind:alpha"
FIELD = "attribute:beta"
AXIS = "axis:gamma"
PATH = "path:delta"


def _intent(**overrides) -> ResolvedIntent:
    base: dict = {
        "normalized_request": "count the alpha items",
        "parts": [
            IntentPart(
                part_id="P1",
                request_text="count the alpha items",
                operation=IntentOperation.COUNT,
                highlightable=True,
            )
        ],
        "targets": [IntentTarget(target_id="T1", part_id="P1", text="alpha items")],
        "visualization": VisualizationIntent.PRIMARY_ONLY,
    }
    base.update(overrides)
    return ResolvedIntent(**base)


def _bind(skeleton, mapping: dict[str, str | None], **kw) -> GroundedBindings:
    return GroundedBindings(
        bindings=[
            SlotBinding(
                slot_id=s.slot_id,
                semantic_id=mapping.get(s.slot_id),
                unsupported_reason=(
                    None if mapping.get(s.slot_id) else "this model records nothing of the kind"
                ),
                **(
                    {"path_semantic_ids": [PATH]}
                    if s.node_kind == "traverse" and mapping.get(s.slot_id)
                    else {}
                ),
            )
            for s in skeleton.slots
        ],
        **kw,
    )


def _pipeline(intent: ResolvedIntent):
    obligations = build_obligations(intent)
    skeleton = build_plan_skeleton(intent, obligations)
    return obligations, skeleton


# ---------------------------------------------------------------------------
# Lossless handle and provenance transfer
# ---------------------------------------------------------------------------


def test_every_material_handle_becomes_exactly_one_obligation():
    intent = _intent(
        constraints=[
            IntentConstraint(
                constraint_id="C1", part_id="P1", text="marked", kind=ConstraintKind.ATTRIBUTE
            )
        ],
        outputs=[IntentOutput(output_id="R1", part_id="P1", text="recorded finish")],
        groupings=[IntentGrouping(grouping_id="G1", part_id="P1", axis_text="by level")],
    )
    obligations, _ = _pipeline(intent)

    handles = [o.intent_handle for o in obligations]
    assert sorted(handles) == ["C1", "G1", "R1", "T1"]
    assert len(handles) == len(set(handles))


def test_provenance_survives_to_the_obligation():
    intent = _intent(provenance=[IntentProvenance(element_id="T1", turn_index=3)])
    obligations, _ = _pipeline(intent)

    target = next(o for o in obligations if o.intent_handle == "T1")
    assert intent.turn_for(target.intent_handle) == 3


def test_a_lost_handle_is_reported_not_ignored():
    intent = _intent(
        constraints=[
            IntentConstraint(
                constraint_id="C1", part_id="P1", text="marked", kind=ConstraintKind.ATTRIBUTE
            )
        ]
    )
    obligations, skeleton = _pipeline(intent)
    # Simulate a transfer that dropped the condition.
    obligations = [o for o in obligations if o.intent_handle != "C1"]

    plan = assemble_plan(intent, skeleton, obligations, _bind(skeleton, {}))
    report = validate_semantic_preservation(intent, obligations, skeleton, plan)

    assert "INTENT_HANDLE_LOST" in {i.code for i in report.issues}


# ---------------------------------------------------------------------------
# Coordinated targets versus qualified single targets
# ---------------------------------------------------------------------------


def test_coordinated_subjects_become_one_part_with_a_union():
    intent = _intent(
        normalized_request="count the alpha and gamma items together",
        targets=[
            IntentTarget(
                target_id="T1",
                part_id="P1",
                text="alpha items",
                coordination=TargetCoordination.UNION_MEMBER,
            ),
            IntentTarget(
                target_id="T2",
                part_id="P1",
                text="gamma items",
                coordination=TargetCoordination.UNION_MEMBER,
            ),
        ],
    )
    obligations, skeleton = _pipeline(intent)

    head = skeleton.slot("P1.t1")
    assert head is not None and head.union_slot_ids == ["P1.t2"]

    bindings = GroundedBindings(
        bindings=[
            SlotBinding(slot_id="P1.t1", semantic_id=CONCEPT, union_semantic_ids=["kind:gamma"]),
            SlotBinding(slot_id="P1.t2", semantic_id="kind:gamma"),
        ]
    )
    plan = assemble_plan(intent, skeleton, obligations, bindings)
    assert len(plan.answer_parts) == 1
    assert plan.answer_parts[0].target.union_semantic_ids == ["kind:gamma"]


def test_independent_subjects_become_separate_parts():
    intent = _intent(
        parts=[
            IntentPart(part_id="P1", request_text="count alphas", operation=IntentOperation.COUNT),
            IntentPart(part_id="P2", request_text="count gammas", operation=IntentOperation.COUNT),
        ],
        targets=[
            IntentTarget(target_id="T1", part_id="P1", text="alpha items"),
            IntentTarget(target_id="T2", part_id="P2", text="gamma items"),
        ],
    )
    obligations, skeleton = _pipeline(intent)
    plan = assemble_plan(
        intent, skeleton, obligations, _bind(skeleton, {"P1.t1": CONCEPT, "P2.t1": "kind:gamma"})
    )

    assert [p.part_id for p in plan.answer_parts] == ["P1", "P2"]


def test_a_qualified_single_subject_stays_one_part_with_a_condition():
    intent = _intent(
        constraints=[
            IntentConstraint(
                constraint_id="C1", part_id="P1", text="marked", kind=ConstraintKind.ATTRIBUTE
            )
        ]
    )
    obligations, skeleton = _pipeline(intent)
    plan = assemble_plan(
        intent, skeleton, obligations, _bind(skeleton, {"P1.t1": CONCEPT, "P1.f1": FIELD})
    )

    assert len(plan.answer_parts) == 1
    assert [f.semantic_id for f in plan.answer_parts[0].filters] == [FIELD]


# ---------------------------------------------------------------------------
# Typed comparisons, Boolean structure, negation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "operator,expected",
    [
        (ConstraintOperator.EQUALS, LogicalOperator.EQUALS),
        (ConstraintOperator.IS_PRESENT, LogicalOperator.IS_PRESENT),
        (ConstraintOperator.GREATER_THAN, LogicalOperator.GREATER_THAN),
        (ConstraintOperator.ONE_OF, LogicalOperator.ONE_OF),
    ],
)
def test_the_resolvers_comparison_reaches_the_plan_unchanged(operator, expected):
    intent = _intent(
        constraints=[
            IntentConstraint(
                constraint_id="C1",
                part_id="P1",
                text="a stated condition",
                kind=ConstraintKind.ATTRIBUTE,
                operator=operator,
                value_text="a value",
            )
        ]
    )
    obligations, skeleton = _pipeline(intent)
    plan = assemble_plan(
        intent, skeleton, obligations, _bind(skeleton, {"P1.t1": CONCEPT, "P1.f1": FIELD})
    )

    node = plan.answer_parts[0].filters[0]
    assert node.operator is expected
    assert node.value_text == "a value"


def test_negation_and_boolean_grouping_reach_the_plan_unchanged():
    intent = _intent(
        constraints=[
            IntentConstraint(
                constraint_id="C1",
                part_id="P1",
                text="one alternative",
                kind=ConstraintKind.ATTRIBUTE,
                or_group="A",
            ),
            IntentConstraint(
                constraint_id="C2",
                part_id="P1",
                text="the other alternative",
                kind=ConstraintKind.ATTRIBUTE,
                or_group="A",
                negated=True,
            ),
        ]
    )
    obligations, skeleton = _pipeline(intent)
    plan = assemble_plan(
        intent,
        skeleton,
        obligations,
        _bind(skeleton, {"P1.t1": CONCEPT, "P1.f1": FIELD, "P1.f2": "attribute:other"}),
    )

    part = plan.answer_parts[0]
    assert {f.bool_group for f in part.filters} == {"A"}
    assert [f.negated for f in part.filters] == [False, True]
    # Every condition sharing one group means the part combines them with "or".
    assert part.filter_bool_op == "or"


# ---------------------------------------------------------------------------
# Relationships, grouping, ordering, limits
# ---------------------------------------------------------------------------


def test_relationship_endpoint_and_direction_survive():
    intent = _intent(
        parts=[
            IntentPart(
                part_id="P1",
                request_text="what the alphas connect to",
                operation=IntentOperation.CONNECTION,
                evidence_kind=EvidenceKind.RELATIONSHIP,
            )
        ],
        relationships=[
            IntentRelationship(
                relationship_id="L1",
                part_id="P1",
                text="attached to",
                to_text="gamma items",
                direction=RelationshipDirection.TO_TARGET,
            )
        ],
    )
    obligations, skeleton = _pipeline(intent)

    obligation = next(o for o in obligations if o.kind is ObligationKind.RELATIONSHIP)
    assert obligation.direction == "to_target"
    assert obligation.endpoint_text == "gamma items"
    slot = skeleton.slot("P1.v1")
    assert slot is not None and slot.direction == "to_target"

    plan = assemble_plan(
        intent, skeleton, obligations, _bind(skeleton, {"P1.t1": CONCEPT, "P1.v1": PATH})
    )
    assert plan.answer_parts[0].result_kind is ResultKind.GRAPH_ENDPOINTS
    assert plan.answer_parts[0].traversals[0].path_semantic_ids == [PATH]


def test_an_extremum_gets_its_grouping_ordering_and_limit_without_a_model():
    intent = _intent(
        parts=[
            IntentPart(
                part_id="P1",
                request_text="which level holds the most alphas",
                operation=IntentOperation.EXTREMUM,
            )
        ],
        groupings=[IntentGrouping(grouping_id="G1", part_id="P1", axis_text="by level")],
        orderings=[
            IntentOrdering(ordering_id="S1", part_id="P1", direction=OrderDirection.DESC)
        ],
    )
    obligations, skeleton = _pipeline(intent)
    plan = assemble_plan(
        intent, skeleton, obligations, _bind(skeleton, {"P1.t1": CONCEPT, "P1.g1": AXIS})
    )

    part = plan.answer_parts[0]
    assert part.result_kind is ResultKind.DISTRIBUTION
    assert part.group is not None and part.group.semantic_id == AXIS
    assert part.order is not None and part.order.direction == "desc"
    assert part.limit == 1


def test_a_sample_is_limited_to_one_and_shows_the_sample():
    intent = _intent(
        parts=[
            IntentPart(
                part_id="P1",
                request_text="one alpha",
                operation=IntentOperation.SAMPLE,
                highlightable=True,
            )
        ]
    )
    obligations, skeleton = _pipeline(intent)
    plan = assemble_plan(intent, skeleton, obligations, _bind(skeleton, {"P1.t1": CONCEPT}))

    part = plan.answer_parts[0]
    assert part.result_kind is ResultKind.SAMPLE
    assert part.limit == 1
    assert part.viewer_set is ViewerSetPolicy.SAMPLE


def test_mixed_evidence_asks_for_qualitative_evidence_not_a_profile():
    intent = _intent(
        parts=[
            IntentPart(
                part_id="P1",
                request_text="describe the alphas",
                operation=IntentOperation.DESCRIPTION,
                evidence_kind=EvidenceKind.MIXED,
            )
        ]
    )
    obligations, skeleton = _pipeline(intent)
    plan = assemble_plan(intent, skeleton, obligations, _bind(skeleton, {"P1.t1": CONCEPT}))

    assert plan.answer_parts[0].result_kind is ResultKind.QUALITATIVE_EVIDENCE
    assert plan.answer_parts[0].evidence_theme


# ---------------------------------------------------------------------------
# Explicit dispositions — never a silent drop
# ---------------------------------------------------------------------------


def test_an_ungroundable_condition_is_reported_not_dropped():
    intent = _intent(
        constraints=[
            IntentConstraint(
                constraint_id="C1",
                part_id="P1",
                text="a condition this model lacks",
                kind=ConstraintKind.ATTRIBUTE,
            )
        ]
    )
    obligations, skeleton = _pipeline(intent)
    plan = assemble_plan(
        intent, skeleton, obligations, _bind(skeleton, {"P1.t1": CONCEPT, "P1.f1": None})
    )

    # The narrowed answer is not silently produced as though it were complete.
    assert plan.answer_parts[0].filters == []
    unavailable = [d for d in plan.dispositions if d.disposition.value == "unavailable"]
    assert [d.requirement_id for d in unavailable] == [
        next(o.obligation_id for o in obligations if o.intent_handle == "C1")
    ]

    report = validate_semantic_preservation(intent, obligations, skeleton, plan)
    assert "OBLIGATION_UNSUPPORTED" in {i.code for i in report.issues}


def test_a_slot_the_model_never_answered_is_unaccounted_and_correctable():
    intent = _intent(
        constraints=[
            IntentConstraint(
                constraint_id="C1", part_id="P1", text="marked", kind=ConstraintKind.ATTRIBUTE
            )
        ]
    )
    obligations, skeleton = _pipeline(intent)
    # A binding set that simply omits the condition's slot.
    bindings = GroundedBindings(
        bindings=[SlotBinding(slot_id="P1.t1", semantic_id=CONCEPT)]
    )
    plan = assemble_plan(intent, skeleton, obligations, bindings)
    report = validate_semantic_preservation(intent, obligations, skeleton, plan)

    issue = next(i for i in report.issues if i.code == "OBLIGATION_UNACCOUNTED")
    assert issue.correctable is True


def test_a_bound_obligation_is_accounted_and_the_plan_preserves_it():
    intent = _intent(
        constraints=[
            IntentConstraint(
                constraint_id="C1", part_id="P1", text="marked", kind=ConstraintKind.ATTRIBUTE
            )
        ]
    )
    obligations, skeleton = _pipeline(intent)
    plan = assemble_plan(
        intent, skeleton, obligations, _bind(skeleton, {"P1.t1": CONCEPT, "P1.f1": FIELD})
    )
    report = validate_semantic_preservation(intent, obligations, skeleton, plan)

    assert report.ok, [i.detail for i in report.issues]
    assert report.bound == 2


# ---------------------------------------------------------------------------
# Roles come from types, not from wording
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "wording",
    [
        "on the highest usable floor",
        "somewhere up on the last habitable deck",
        "wherever the top occupied level happens to be",
    ],
)
def test_a_spatial_condition_is_a_scope_however_it_is_worded(wording):
    """The resolver typed it spatial; no phrase-shape rule may re-decide that."""
    intent = _intent(
        constraints=[
            IntentConstraint(
                constraint_id="C1", part_id="P1", text=wording, kind=ConstraintKind.SPATIAL
            )
        ]
    )
    obligations, skeleton = _pipeline(intent)

    obligation = next(o for o in obligations if o.intent_handle == "C1")
    assert obligation.kind is ObligationKind.SCOPE
    assert skeleton.slot("P1.s1") is not None


@pytest.mark.parametrize(
    "wording",
    ["marked", "carrying the marking the user described", "MARKED"],
)
def test_an_attribute_condition_is_a_filter_however_it_is_worded(wording):
    intent = _intent(
        constraints=[
            IntentConstraint(
                constraint_id="C1", part_id="P1", text=wording, kind=ConstraintKind.ATTRIBUTE
            )
        ]
    )
    obligations, _ = _pipeline(intent)

    assert next(o for o in obligations if o.intent_handle == "C1").kind is ObligationKind.FILTER


def test_the_recall_ledger_is_marked_typed_so_words_are_only_hints():
    intent = _intent()
    obligations, _ = _pipeline(intent)
    ledger = build_recall_ledger(obligations, intent.normalized_request)

    assert ledger.typed is True
    assert [r.requirement_id for r in ledger.requirements] == [
        o.obligation_id for o in obligations
    ]


# ---------------------------------------------------------------------------
# Visualization membership is decided before grounding
# ---------------------------------------------------------------------------


def test_every_highlightable_part_gets_a_viewer_set():
    intent = _intent(
        parts=[
            IntentPart(
                part_id="P1", request_text="alphas", operation=IntentOperation.LIST,
                highlightable=True,
            ),
            IntentPart(
                part_id="P2", request_text="gammas", operation=IntentOperation.LIST,
                highlightable=True,
            ),
        ],
        targets=[
            IntentTarget(target_id="T1", part_id="P1", text="alpha items"),
            IntentTarget(target_id="T2", part_id="P2", text="gamma items"),
        ],
        visualization=VisualizationIntent.ALL_RESULTS,
    )
    obligations, skeleton = _pipeline(intent)
    plan = assemble_plan(
        intent, skeleton, obligations, _bind(skeleton, {"P1.t1": CONCEPT, "P2.t1": "kind:gamma"})
    )

    assert all(p.viewer_set is ViewerSetPolicy.REQUESTED for p in plan.answer_parts)
    assert all(p.is_primary_visual for p in plan.answer_parts)


def test_a_non_object_answer_highlights_nothing():
    intent = _intent(
        parts=[
            IntentPart(
                part_id="P1",
                request_text="describe the model",
                operation=IntentOperation.DESCRIPTION,
                highlightable=False,
            )
        ],
        visualization=VisualizationIntent.NONE,
    )
    obligations, skeleton = _pipeline(intent)
    plan = assemble_plan(intent, skeleton, obligations, _bind(skeleton, {"P1.t1": CONCEPT}))

    assert plan.answer_parts[0].viewer_set is ViewerSetPolicy.NONE


# ---------------------------------------------------------------------------
# task30 iteration 002 — an unsupported condition degrades, never cancels
# ---------------------------------------------------------------------------


def test_an_unsupported_condition_still_lets_its_part_execute():
    """Refusing an answerable request costs more than answering it with a caveat.

    The subject is bound, so the part must still produce its result; the
    condition this model cannot serve becomes a stated limitation.
    """
    intent = _intent(
        constraints=[
            IntentConstraint(
                constraint_id="C1",
                part_id="P1",
                text="a condition this model lacks",
                kind=ConstraintKind.ATTRIBUTE,
            )
        ]
    )
    obligations, skeleton = _pipeline(intent)
    plan = assemble_plan(
        intent, skeleton, obligations, _bind(skeleton, {"P1.t1": CONCEPT, "P1.f1": None})
    )

    assert len(plan.answer_parts) == 1
    part = plan.answer_parts[0]
    assert part.target.semantic_id == CONCEPT


def test_a_widened_part_is_marked_contextual_and_says_why():
    """The set is broader than asked, so it may never present itself as exact."""
    intent = _intent(
        parts=[
            IntentPart(
                part_id="P1",
                request_text="list the alpha items of the chosen kind",
                operation=IntentOperation.LIST,
                highlightable=True,
            )
        ],
        constraints=[
            IntentConstraint(
                constraint_id="C1",
                part_id="P1",
                text="of the chosen kind",
                kind=ConstraintKind.ATTRIBUTE,
            )
        ],
    )
    obligations, skeleton = _pipeline(intent)
    plan = assemble_plan(
        intent, skeleton, obligations, _bind(skeleton, {"P1.t1": CONCEPT, "P1.f1": None})
    )

    part = plan.answer_parts[0]
    assert part.viewer_set is ViewerSetPolicy.CONTEXT
    assert part.context_reason and "chosen kind" in part.context_reason


def test_a_fully_served_part_is_never_marked_contextual():
    intent = _intent(
        constraints=[
            IntentConstraint(
                constraint_id="C1", part_id="P1", text="marked", kind=ConstraintKind.ATTRIBUTE
            )
        ]
    )
    obligations, skeleton = _pipeline(intent)
    plan = assemble_plan(
        intent, skeleton, obligations, _bind(skeleton, {"P1.t1": CONCEPT, "P1.f1": FIELD})
    )

    part = plan.answer_parts[0]
    assert part.viewer_set is not ViewerSetPolicy.CONTEXT
    assert part.context_reason is None


def test_an_unbound_subject_still_cancels_its_own_part_only():
    """Without a subject there is nothing to execute — but only that part dies."""
    intent = _intent(
        parts=[
            IntentPart(part_id="P1", request_text="count alphas", operation=IntentOperation.COUNT),
            IntentPart(part_id="P2", request_text="count gammas", operation=IntentOperation.COUNT),
        ],
        targets=[
            IntentTarget(target_id="T1", part_id="P1", text="alpha items"),
            IntentTarget(target_id="T2", part_id="P2", text="gamma items"),
        ],
    )
    obligations, skeleton = _pipeline(intent)
    plan = assemble_plan(
        intent, skeleton, obligations, _bind(skeleton, {"P1.t1": CONCEPT, "P2.t1": None})
    )

    assert [p.part_id for p in plan.answer_parts] == ["P1"]
