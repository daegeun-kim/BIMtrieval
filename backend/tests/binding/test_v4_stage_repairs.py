"""task27 — stage-boundary repairs, tested per owning stage (offline).

Every case uses a PARAPHRASE or a synthetic model, never a benchmark question,
model id, expected count, or IFC filename: the point is the reusable stage
invariant, not one recorded answer. The six groups mirror task27's fundamental
tests:

1. ledger construction — coordinated peers, compound counts, merged qualifier,
   sample-detail parsing, non-English normalization;
2. recall — target-compatible ranking and the configured dense channel;
3. binder bookkeeping — short local node ids, exact semantic ids, plan shapes,
   unique part ids, deterministic disposition linkage;
4. validation — accepting a valid plan while still rejecting dropped
   qualifiers, invented filters, and ambiguous repairs;
5. execution — material distribution, direct derived counts, thematic evidence
   subjects, and the catalog query's real schema;
6. answers — rejecting unsupported caveats and internal wording, with plain
   deterministic fallbacks.
"""

from __future__ import annotations

import pytest

from app.llm.schemas_v2 import (
    AggregateNode,
    AnswerPartV2,
    ClaimKind,
    DispositionKind,
    FilterNode,
    GroundedAnswerV2,
    GroundedClaim,
    GroupNode,
    LogicalOperator,
    LogicalPlan,
    RequirementDisposition,
    ResultKind,
    ScopeKindV2,
    ScopeNode,
    TargetNode,
    ViewerSetPolicy,
)
from app.query.binding.answer_validation_v2 import (
    build_fallback_answer_v2,
    validate_answer_v2,
)
from app.query.binding.compile_v2 import CompileFailure, array_group_spec, compile_part
from app.query.binding.ledger_v2 import (
    RequirementRole,
    ResolutionState,
    build_ledger_skeleton,
)
from app.query.binding.multilingual import english_equivalents
from app.query.binding.packet_v2 import build_answer_packet_v2
from app.query.binding.phrasing import (
    banned_terms_in,
    humanize_semantic_id,
    humanize_text,
)
from app.query.binding.plan_normalize import normalize_plan_bookkeeping
from app.query.binding.recall import resolve_ledger, run_recall
from app.query.binding.results_v2 import (
    DistributionBucketV2,
    DistributionResult,
    PartResultV2,
    ResultStatusV2,
    ScalarResult,
)
from app.query.binding.validate_v2 import GateStateV2, validate_plan
from app.query.semantic.manifest_v002.schema import parse_manifest_v002

# ---------------------------------------------------------------------------
# A small synthetic model: two peer occurrence classes, one field that applies
# to each, a material array field, and two floor bands.
# ---------------------------------------------------------------------------


def _class(semantic_id: str, label: str, aliases: list[str], count: int) -> dict:
    return {
        "id": semantic_id,
        "kind": "class",
        "label": label,
        "aliases": aliases,
        "grain": "entity",
        "uses": ["target", "topic_context"],
        "accessor": "entity.class",
        "executable": True,
        "applicability": [
            {
                "subject": semantic_id,
                "coverage": "present_complete",
                "known_count": count,
                "eligible_count": count,
                "can_prove_absence": True,
            }
        ],
        "value_policy": "none",
        "values": [],
        "provenance": [],
    }


def _field(semantic_id: str, label: str, aliases: list[str], subject: str) -> dict:
    container, _, name = semantic_id.partition(":")[2].rpartition(".")
    return {
        "id": semantic_id,
        "kind": "field",
        "label": label,
        "aliases": aliases,
        "grain": "entity",
        "uses": ["filter", "group", "report"],
        "data_type": "text",
        "operators": ["equals", "not_equals", "is_present", "is_missing"],
        "accessor": "json.property_value",
        "executable": True,
        "applicability": [
            {
                "subject": subject,
                "coverage": "present_complete",
                "known_count": 10,
                "eligible_count": 10,
                "can_prove_absence": True,
            }
        ],
        "value_policy": "none",
        "values": [],
        "provenance": [],
        "physical": {"source": "property_sets", "set": container, "field": name},
    }


def _document() -> dict:
    content = {
        "entity_total": 60,
        "class_inventory": {
            "IfcRailing": 12,
            "IfcRamp": 8,
            "IfcCovering": 40,
        },
        "capabilities": [
            _class("cls:IfcRailing", "Ifc Railing", ["railing", "railings"], 12),
            _class("cls:IfcRamp", "Ifc Ramp", ["ramp", "ramps"], 8),
            _class("cls:IfcCovering", "Ifc Covering", ["covering"], 40),
            _field(
                "prop:Pset_RailingCommon.IsExternal",
                "Pset_RailingCommon.IsExternal",
                ["external"],
                "cls:IfcRailing",
            ),
            _field(
                "prop:Pset_CoveringCommon.IsExternal",
                "Pset_CoveringCommon.IsExternal",
                ["external"],
                "cls:IfcCovering",
            ),
            {
                **_field(
                    "prop:Pset_RailingCommon.Category",
                    "Pset_RailingCommon.Category",
                    ["category"],
                    "cls:IfcRailing",
                ),
                "value_policy": "enumerated",
                "values": [{"value": "Handrail", "count": 9}],
            },
            {
                "id": "mat:material.name",
                "kind": "field",
                "label": "material",
                "aliases": ["materials", "made of"],
                "grain": "entity",
                "uses": ["filter", "group", "report"],
                "data_type": "text",
                "operators": ["equals", "contains", "is_present", "is_missing"],
                "accessor": "json.material_name",
                "executable": True,
                "applicability": [
                    {
                        "subject": "cls:IfcRailing",
                        "coverage": "present_complete",
                        "known_count": 12,
                        "eligible_count": 12,
                        "can_prove_absence": True,
                    }
                ],
                "value_policy": "none",
                "values": [],
                "provenance": [],
                "physical": {"source": "materials", "field": "name"},
            },
        ],
        "traversals": [],
        "derived_floors": {
            "derivation_version": "floors_v001",
            "reference_index": 0,
            "reference_basis": "lowest_band",
            "interpretation_note": "2 bands",
            "bands": [
                {
                    "id": "floor:band:0",
                    "index": 0,
                    "occupiable_ordinal": 1,
                    "storey_global_ids": ["s0"],
                    "storey_names": ["Level 0"],
                    "elevation_min": 0.0,
                    "elevation_max": 1.0,
                    "classification": "occupiable",
                    "confidence": "high",
                    "reasons": [],
                    "evidence": {},
                },
                {
                    "id": "floor:band:1",
                    "index": 1,
                    "occupiable_ordinal": None,
                    "storey_global_ids": ["s1"],
                    "storey_names": ["Roof"],
                    "elevation_min": 4.0,
                    "elevation_max": 5.0,
                    "classification": "non_occupiable_reference",
                    "confidence": "high",
                    "reasons": [],
                    "evidence": {},
                },
            ],
        },
        "profiles": [
            {
                "id": "derived:building_profile",
                "label": "building profile",
                "aliases": ["summary", "overview"],
                "accessor": "derived.building_profile",
                "uses": ["target"],
            },
            {
                "id": "derived:thematic_profile",
                "label": "thematic profile",
                "aliases": ["theme", "aspect"],
                "accessor": "derived.thematic_profile",
                "uses": ["target"],
            },
        ],
        "spatial_membership": {"by_class": []},
        "storeys": [],
    }
    content["class_inventory"] = [
        {"ifc_class": name, "count": count} for name, count in content["class_inventory"].items()
    ]
    return {
        "identity": {
            "source_model_id": 99,
            "file_fingerprint": "a" * 64,
            "file_name": "synthetic.ifc",
            "ifc_schema": "IFC4",
            "extraction_version": "v002",
            "manifest_schema_version": "v002",
            "builder_version": "v002",
            "contract_version": "v001",
            "content_hash": "n/a",
        },
        "content": content,
    }


@pytest.fixture()
def manifest():
    return parse_manifest_v002(_document())


def _resolved(manifest, question: str):
    ledger = build_ledger_skeleton(question)
    recall = run_recall(None, manifest, ledger)
    resolve_ledger(ledger, recall, manifest)
    return ledger, recall


def _roles(ledger, role: RequirementRole) -> list:
    return [r for r in ledger.requirements if r.role is role]


# ===========================================================================
# 1. Ledger construction
# ===========================================================================


def test_coordinated_peers_asked_as_one_total_stay_peer_targets_of_one_part():
    ledger = build_ledger_skeleton("What is the combined number of railings and ramps?")
    targets = _roles(ledger, RequirementRole.TARGET)
    assert [t.source_text for t in targets] == ["railings", "ramps"]
    assert {t.part_hint for t in targets} == {"P1"}
    assert not _roles(ledger, RequirementRole.FILTER)


def test_coordinated_independent_counts_get_separate_parts_and_targets():
    ledger = build_ledger_skeleton("How many railings, ramps and coverings are there?")
    targets = _roles(ledger, RequirementRole.TARGET)
    assert [t.source_text for t in targets] == ["railings", "ramps", "coverings"]
    assert len({t.part_hint for t in targets}) == 3
    assert not _roles(ledger, RequirementRole.FILTER)


def test_a_qualifier_is_not_turned_into_a_peer_target():
    """Only a COORDINATED noun becomes a peer; a plain qualifier stays a filter."""
    ledger = build_ledger_skeleton("show me external railings")
    assert [t.source_text for t in _roles(ledger, RequirementRole.TARGET)] == [
        "external railings"
    ]


def test_a_resolved_field_discharges_the_whole_qualifier_phrase(manifest):
    """The unresolvable fragment naming its sibling's field is not retained.

    "categorised as handrail" is ONE condition: the value resolves the Category
    field, and the word "categorised" names that same field, so keeping it as a
    second, unavailable requirement made the whole answer partial with a
    "not determinable" caveat over a result that was exact.
    """
    ledger, _ = _resolved(manifest, "how many railings are categorised as handrail?")
    duplicate = next(r for r in ledger.requirements if r.source_text == "categorised")
    assert not duplicate.required
    assert duplicate.resolution is ResolutionState.RESOLVABLE
    assert "already represented by" in (duplicate.resolution_note or "")


def test_sample_detail_language_makes_one_part_with_a_report_not_a_second_target():
    ledger = build_ledger_skeleton("Choose a sample ramp and list its details.")
    assert len(ledger.part_hints()) == 1
    targets = _roles(ledger, RequirementRole.TARGET)
    assert [t.source_text for t in targets] == ["ramp"]
    outputs = _roles(ledger, RequirementRole.OUTPUT)
    assert [o.source_text for o in outputs] == ["details"]
    assert not outputs[0].required
    limits = [r for r in ledger.requirements if r.role is RequirementRole.LIMIT]
    assert limits and limits[0].limit_value == 1


def test_a_verb_of_selection_is_never_an_occurrence_target():
    ledger = build_ledger_skeleton("Pick one railing.")
    assert "pick" not in {
        t.source_text.casefold() for t in _roles(ledger, RequirementRole.TARGET)
    }


def test_building_wide_topic_language_stays_context_in_any_language():
    for question in (
        "How many railings are in this building?",
        "Hur manga racken finns det i byggnaden?",
    ):
        ledger = build_ledger_skeleton(question)
        contexts = _roles(ledger, RequirementRole.TOPIC_CONTEXT)
        assert contexts, question
        assert all(not c.required for c in contexts)
        assert not _roles(ledger, RequirementRole.FILTER), question


def test_non_english_count_language_leaves_only_the_subject_as_the_target():
    ledger = build_ledger_skeleton("Hur manga racken finns det i byggnaden?")
    targets = _roles(ledger, RequirementRole.TARGET)
    assert len(targets) == 1
    assert "finns" not in targets[0].source_text.casefold()


def test_non_english_subject_nouns_map_onto_their_english_token():
    assert "window" in english_equivalents("Hur manga fonster finns det?")
    assert "door" in english_equivalents("Hoeveel deuren zijn er?")
    assert "wall" in english_equivalents("Wie viele Wande gibt es?")


def test_a_non_english_subject_resolves_to_the_same_concept(manifest):
    ledger, _ = _resolved(manifest, "Hur manga racken finns det?")
    target = _roles(ledger, RequirementRole.TARGET)[0]
    assert target.resolution is ResolutionState.RESOLVABLE
    assert "cls:IfcRailing" in target.candidate_ids


# ===========================================================================
# 2. Recall ranking and the dense channel
# ===========================================================================


def test_a_field_applicable_to_the_target_outranks_the_same_name_elsewhere(manifest):
    """Two classes carry an identically named field; the target's one wins."""
    ledger, recall = _resolved(manifest, "show me railings that are external")
    qualifier = next(r for r in ledger.requirements if r.source_text == "external")
    ranked = [r.concept_id for r in recall.for_requirement(qualifier.requirement_id)]
    assert ranked, "the qualifier got no recommendation at all"
    assert ranked[0] == "prop:Pset_RailingCommon.IsExternal"


def test_ranking_reorders_without_narrowing_eligibility(manifest):
    ledger, recall = _resolved(manifest, "show me railings that are external")
    qualifier = next(r for r in ledger.requirements if r.source_text == "external")
    ranked = [r.concept_id for r in recall.for_requirement(qualifier.requirement_id)]
    # The incompatible-class field is still offered, just not first.
    assert "prop:Pset_CoveringCommon.IsExternal" in ranked


def test_a_descriptive_output_resolves_to_the_derived_profile(manifest):
    ledger, _ = _resolved(manifest, "Give me a summary of this building.")
    output = next(r for r in ledger.requirements if r.role is RequirementRole.OUTPUT)
    assert output.resolution is ResolutionState.RESOLVABLE
    assert "derived:building_profile" in output.candidate_ids


def test_the_configured_dense_channel_is_reported_available(manifest):
    """The dense channel must use a batch method the embedding service really
    has; the recorded traces reported `dense_available: false` for every query
    because it called one that never existed."""

    class _Service:
        model_name = "fake-batch"

        def embed_documents(self, texts):
            return [[float(len(t) % 7), 1.0, 0.5] for t in texts]

        def embed_query(self, text):
            return [float(len(text) % 7), 1.0, 0.5]

    from app.query.binding.concept_vectors import clear_concept_vector_cache

    clear_concept_vector_cache()
    ledger = build_ledger_skeleton("how many railings are there?")
    recall = run_recall(
        None, manifest, ledger, embedding_service_getter=lambda: _Service()
    )
    assert recall.diagnostics["dense_available"] is True


def test_the_real_embedding_service_exposes_the_batch_method_recall_calls():
    from app.query.rag.embedding_service import EmbeddingService

    assert any(
        callable(getattr(EmbeddingService, name, None))
        for name in ("embed_texts", "embed_documents")
    )


# ===========================================================================
# 3. Binder bookkeeping (deterministic, no model call)
# ===========================================================================


def _part(**overrides) -> AnswerPartV2:
    defaults = dict(
        part_id="P1",
        request_text="how many railings",
        result_kind=ResultKind.SCALAR,
        target=TargetNode(node_id="t1", semantic_id="cls:IfcRailing"),
        aggregate=AggregateNode(node_id="a1"),
        viewer_set=ViewerSetPolicy.REQUESTED,
    )
    defaults.update(overrides)
    return AnswerPartV2(**defaults)


def test_node_ids_are_rewritten_to_short_local_handles():
    part = _part(
        target=TargetNode(node_id="cls:IfcRailing", semantic_id="cls:IfcRailing"),
        filters=[
            FilterNode(
                node_id="prop:Pset_RailingCommo",  # truncated at the schema bound
                semantic_id="prop:Pset_RailingCommon.IsExternal",
                value_text="true",
            )
        ],
        scope=ScopeNode(node_id="scope:active_model", kind=ScopeKindV2.ACTIVE_MODEL),
    )
    plan = LogicalPlan(answer_parts=[part])
    normalize_plan_bookkeeping(plan)
    assert part.target.node_id == "t1"
    assert part.filters[0].node_id == "f1"
    assert part.scope.node_id == "s1"


def test_a_disposition_naming_a_semantic_id_is_relinked_to_the_handle():
    part = _part(
        filters=[
            FilterNode(
                node_id="prop:Pset_RailingCommo",
                semantic_id="prop:Pset_RailingCommon.IsExternal",
                value_text="true",
            )
        ]
    )
    plan = LogicalPlan(
        answer_parts=[part],
        dispositions=[
            RequirementDisposition(
                requirement_id="L2",
                disposition=DispositionKind.BOUND,
                part_id="P1",
                node_ids=["cls:IfcRailing", "prop:Pset_RailingCommon.IsExternal"],
            )
        ],
    )
    normalize_plan_bookkeeping(plan)
    assert plan.dispositions[0].node_ids == ["t1", "f1"]


def test_a_uniquely_determined_reference_is_inferred_but_an_ambiguous_one_is_not():
    ledger = build_ledger_skeleton("show me external railings")
    filters = [
        FilterNode(node_id="x", semantic_id="prop:Pset_RailingCommon.IsExternal"),
    ]
    part = _part(result_kind=ResultKind.ENTITY_SET, aggregate=None, filters=filters)
    filter_requirement = next(
        r for r in ledger.requirements if r.role is RequirementRole.TARGET
    )
    plan = LogicalPlan(
        answer_parts=[part],
        dispositions=[
            RequirementDisposition(
                requirement_id=filter_requirement.requirement_id,
                disposition=DispositionKind.BOUND,
                part_id="P1",
                node_ids=["nonsense"],
            )
        ],
    )
    report = normalize_plan_bookkeeping(plan, ledger)
    assert plan.dispositions[0].node_ids == ["t1"]
    assert report.inferred_references == 1

    # Two filters of the same kind: the intended one is NOT unique, so nothing
    # is guessed and validation still sees the reference as unresolved.
    part2 = _part(
        result_kind=ResultKind.ENTITY_SET,
        aggregate=None,
        filters=[
            FilterNode(node_id="x", semantic_id="prop:Pset_RailingCommon.IsExternal"),
            FilterNode(node_id="y", semantic_id="prop:Pset_RailingCommon.Category"),
        ],
    )
    qualifier = next(
        r for r in ledger.requirements if r.role is RequirementRole.FILTER
    ) if _roles(ledger, RequirementRole.FILTER) else None
    plan2 = LogicalPlan(
        answer_parts=[part2],
        dispositions=[
            RequirementDisposition(
                requirement_id=(qualifier.requirement_id if qualifier else "L9"),
                disposition=DispositionKind.BOUND,
                part_id="P1",
                node_ids=["nonsense"],
            )
        ],
    )
    report2 = normalize_plan_bookkeeping(plan2, ledger)
    assert plan2.dispositions[0].node_ids == []
    assert report2.inferred_references == 0


def test_duplicate_part_ids_are_made_unique():
    plan = LogicalPlan(answer_parts=[_part(), _part()])
    report = normalize_plan_bookkeeping(plan)
    assert [p.part_id for p in plan.answer_parts] == ["P1", "P1_2"]
    assert report.renamed_parts == [("P1", "P1_2")]


def test_a_disposition_without_a_part_attaches_to_the_only_part():
    plan = LogicalPlan(
        answer_parts=[_part()],
        dispositions=[
            RequirementDisposition(
                requirement_id="L2", disposition=DispositionKind.BOUND, node_ids=["t1"]
            )
        ],
    )
    normalize_plan_bookkeeping(plan)
    assert plan.dispositions[0].part_id == "P1"


# ===========================================================================
# 4. Validation: accepts a valid plan, still rejects real defects
# ===========================================================================


def _validate(manifest, question: str, plan: LogicalPlan):
    ledger, _ = _resolved(manifest, question)
    return validate_plan(None, plan, ledger, manifest), ledger


def _bind_all(ledger, part_id: str, node_ids: list[str]) -> list[RequirementDisposition]:
    return [
        RequirementDisposition(
            requirement_id=r.requirement_id,
            disposition=DispositionKind.BOUND,
            part_id=part_id,
            node_ids=list(node_ids),
        )
        for r in ledger.required()
    ]


def test_a_valid_target_filter_and_scope_plan_is_accepted(manifest):
    question = "show me railings that are external"
    ledger, _ = _resolved(manifest, question)
    part = _part(
        request_text=question,
        result_kind=ResultKind.ENTITY_SET,
        aggregate=None,
        target=TargetNode(node_id="target", semantic_id="cls:IfcRailing"),
        filters=[
            FilterNode(
                node_id="whatever",
                semantic_id="prop:Pset_RailingCommon.IsExternal",
                value_text="true",
            )
        ],
        scope=ScopeNode(node_id="sc", kind=ScopeKindV2.ACTIVE_MODEL),
    )
    plan = LogicalPlan(
        answer_parts=[part],
        dispositions=_bind_all(ledger, "P1", ["t1", "f1"]),
    )
    validation = validate_plan(None, plan, ledger, manifest)
    assert [v.state for v in validation.verdicts] == [GateStateV2.READY], [
        i.detail for i in validation.all_issues()
    ]


def test_union_members_contribute_to_the_requirements_they_represent(manifest):
    question = "What is the combined number of railings and ramps?"
    ledger, _ = _resolved(manifest, question)
    part = _part(
        request_text=question,
        target=TargetNode(
            node_id="t", semantic_id="cls:IfcRamp", union_semantic_ids=["cls:IfcRailing"]
        ),
    )
    plan = LogicalPlan(answer_parts=[part], dispositions=_bind_all(ledger, "P1", ["t1"]))
    validation = validate_plan(None, plan, ledger, manifest)
    assert [v.state for v in validation.verdicts] == [GateStateV2.READY], [
        i.detail for i in validation.all_issues()
    ]


def test_a_dropped_qualifier_is_still_rejected(manifest):
    """Binding only the class for "external railings" leaves a word unaccounted."""
    question = "show me external railings"
    ledger, _ = _resolved(manifest, question)
    part = _part(
        request_text=question,
        result_kind=ResultKind.ENTITY_SET,
        aggregate=None,
        target=TargetNode(node_id="t", semantic_id="cls:IfcRailing"),
    )
    plan = LogicalPlan(answer_parts=[part], dispositions=_bind_all(ledger, "P1", ["t1"]))
    validation = validate_plan(None, plan, ledger, manifest)
    details = " ".join(i.detail for i in validation.all_issues())
    assert "external" in details
    assert validation.verdicts[0].state is GateStateV2.CORRECTABLE_BINDING_GAP


def test_an_invented_narrowing_filter_is_still_rejected(manifest):
    question = "how many railings are there?"
    ledger, _ = _resolved(manifest, question)
    part = _part(
        request_text=question,
        filters=[
            FilterNode(
                node_id="f",
                semantic_id="prop:Pset_RailingCommon.Category",
                operator=LogicalOperator.IS_PRESENT,
            )
        ],
    )
    plan = LogicalPlan(answer_parts=[part], dispositions=_bind_all(ledger, "P1", ["t1"]))
    validation = validate_plan(None, plan, ledger, manifest)
    details = " ".join(i.detail for i in validation.all_issues())
    assert "no ledger provenance" in details


def test_an_incompatible_field_is_still_rejected(manifest):
    question = "show me railings that are external"
    ledger, _ = _resolved(manifest, question)
    part = _part(
        request_text=question,
        result_kind=ResultKind.ENTITY_SET,
        aggregate=None,
        filters=[
            FilterNode(
                node_id="f",
                semantic_id="prop:Pset_CoveringCommon.IsExternal",
                value_text="true",
            )
        ],
    )
    plan = LogicalPlan(answer_parts=[part], dispositions=_bind_all(ledger, "P1", ["t1", "f1"]))
    validation = validate_plan(None, plan, ledger, manifest)
    codes = {i.code for i in validation.all_issues()}
    assert "MANIFEST_APPLICABILITY_ERROR" in codes


def test_an_invented_semantic_id_is_still_rejected(manifest):
    question = "how many railings are there?"
    ledger, _ = _resolved(manifest, question)
    part = _part(request_text=question, target=TargetNode(node_id="t", semantic_id="railings"))
    plan = LogicalPlan(answer_parts=[part], dispositions=_bind_all(ledger, "P1", ["t1"]))
    validation = validate_plan(None, plan, ledger, manifest)
    details = " ".join(i.detail for i in validation.all_issues())
    assert "not a semantic id" in details


def test_an_inflected_or_translated_phrase_does_not_fail_coverage(manifest):
    question = "Hur manga racken finns det?"
    ledger, _ = _resolved(manifest, question)
    part = _part(request_text=question)
    plan = LogicalPlan(answer_parts=[part], dispositions=_bind_all(ledger, "P1", ["t1"]))
    validation = validate_plan(None, plan, ledger, manifest)
    assert [v.state for v in validation.verdicts] == [GateStateV2.READY], [
        i.detail for i in validation.all_issues()
    ]


# ===========================================================================
# 5. Execution and evidence gaps
# ===========================================================================


def test_a_material_array_field_compiles_to_an_array_group(manifest):
    capability = manifest.capabilities["mat:material.name"]
    spec = array_group_spec("g1", capability)
    assert spec is not None
    assert (spec.kind, spec.array_key, spec.array_field) == (
        "array_element",
        "materials",
        "name",
    )


def test_a_material_distribution_compiles_where_a_scalar_path_does_not(manifest):
    part = AnswerPartV2(
        part_id="P1",
        request_text="what are the railings made of",
        result_kind=ResultKind.DISTRIBUTION,
        target=TargetNode(node_id="t1", semantic_id="cls:IfcRailing"),
        group=GroupNode(node_id="g1", semantic_id="mat:material.name"),
        aggregate=AggregateNode(node_id="a1"),
        viewer_set=ViewerSetPolicy.REQUESTED,
    )
    compiled = compile_part(None, part, manifest)
    assert compiled.group is not None and compiled.group.kind == "array_element"


def test_a_derived_floor_count_is_a_target_needing_no_row_scan(manifest):
    from app.query.semantic.manifest_v002.schema import (
        DERIVED_FLOOR_COUNT_ID,
        DERIVED_OCCUPIABLE_FLOOR_COUNT_ID,
    )

    assert manifest.capabilities[DERIVED_FLOOR_COUNT_ID].physical["value"] == 2
    assert manifest.capabilities[DERIVED_OCCUPIABLE_FLOOR_COUNT_ID].physical["value"] == 1
    part = AnswerPartV2(
        part_id="P1",
        request_text="how many floors",
        result_kind=ResultKind.SCALAR,
        target=TargetNode(node_id="t1", semantic_id=DERIVED_FLOOR_COUNT_ID),
        aggregate=AggregateNode(node_id="a1"),
        viewer_set=ViewerSetPolicy.NONE,
    )
    compiled = compile_part(None, part, manifest)
    assert compiled.derived_value == 2
    assert compiled.target_classes == ()


def test_a_derived_count_refuses_to_be_filtered(manifest):
    from app.query.semantic.manifest_v002.schema import DERIVED_FLOOR_COUNT_ID

    part = AnswerPartV2(
        part_id="P1",
        request_text="how many floors are external",
        result_kind=ResultKind.SCALAR,
        target=TargetNode(node_id="t1", semantic_id=DERIVED_FLOOR_COUNT_ID),
        filters=[
            FilterNode(node_id="f1", semantic_id="prop:Pset_RailingCommon.IsExternal")
        ],
        aggregate=AggregateNode(node_id="a1"),
        viewer_set=ViewerSetPolicy.NONE,
    )
    with pytest.raises(CompileFailure):
        compile_part(None, part, manifest)


def test_a_thematic_profile_reports_the_subjects_its_evidence_describes():
    from app.query.binding.results_v2 import QualitativeEvidenceResult

    evidence = QualitativeEvidenceResult(
        excerpts=[], subject_classes={"IfcRamp": 3, "IfcRailing": 2}
    )
    facts = {f["fact_id"]: f for f in evidence.facts("P1")}
    assert "P1:evidence_subjects" in facts
    assert facts["P1:evidence_subjects"]["value"] == {"IfcRamp": 3, "IfcRailing": 2}


def test_the_catalog_query_uses_the_recorded_schema():
    """Display metadata lives in the catalog-entry table, not the source-model
    table; the recorded run raised UndefinedColumn on `display_name`."""
    import sqlalchemy as sa

    from app.db.models import IfcSourceModel, SourceModelCatalogEntry
    from app.query.catalog_answer import load_catalog_models

    assert "display_name" not in IfcSourceModel.__table__.c
    assert "display_name" in SourceModelCatalogEntry.__table__.c

    captured: dict[str, str] = {}

    class _Session:
        def execute(self, statement):
            captured["sql"] = str(statement.compile(dialect=sa.dialects.postgresql.dialect()))

            class _Result:
                def mappings(self):
                    return []

            return _Result()

    load_catalog_models(_Session())
    assert "source_model_catalog_entries" in captured["sql"]
    assert "ifc_source_models" in captured["sql"]


# ===========================================================================
# 6. Answer validation and plain-language fallbacks
# ===========================================================================


def _exact_part(count: int = 12) -> PartResultV2:
    part = PartResultV2(
        part_id="P1",
        request_text="how many railings are there",
        result_kind="scalar",
        status=ResultStatusV2.EXACT,
        result=ScalarResult(
            function="count", value=count, covered_cardinality=count, eligible_cardinality=count
        ),
    )
    return part


def test_an_answer_denying_a_result_the_model_holds_is_rejected():
    packet = build_answer_packet_v2("how many railings", [_exact_part()])
    generated = GroundedAnswerV2(
        answer="12 objects were counted, but the packet does not provide a count.",
        claims=[GroundedClaim(kind=ClaimKind.FACT, cited_id="P1:count", value="12")],
        disclosed_limitation=True,
    )
    assert not validate_answer_v2(generated, packet).ok


def test_a_limitation_disclosed_without_one_recorded_is_rejected():
    packet = build_answer_packet_v2("how many railings", [_exact_part()])
    generated = GroundedAnswerV2(
        answer="There are 12 railings.",
        claims=[GroundedClaim(kind=ClaimKind.FACT, cited_id="P1:count", value="12")],
        disclosed_limitation=True,
    )
    assert not validate_answer_v2(generated, packet).ok


def test_uncertainty_added_to_an_exact_result_is_rejected():
    packet = build_answer_packet_v2("how many railings", [_exact_part()])
    generated = GroundedAnswerV2(
        answer="There are approximately 12 railings, though this cannot be determined exactly.",
        claims=[GroundedClaim(kind=ClaimKind.FACT, cited_id="P1:count", value="12")],
    )
    assert not validate_answer_v2(generated, packet).ok


def test_internal_pipeline_wording_is_rejected():
    packet = build_answer_packet_v2("how many railings", [_exact_part()])
    generated = GroundedAnswerV2(
        answer="The target class cls:IfcRailing has 12 matches in the packet.",
        claims=[GroundedClaim(kind=ClaimKind.FACT, cited_id="P1:count", value="12")],
    )
    assert not validate_answer_v2(generated, packet).ok


def test_a_plain_exact_answer_is_accepted():
    packet = build_answer_packet_v2("how many railings", [_exact_part()])
    generated = GroundedAnswerV2(
        answer="There are 12 railings in this model.",
        claims=[GroundedClaim(kind=ClaimKind.FACT, cited_id="P1:count", value="12")],
    )
    assert validate_answer_v2(generated, packet).ok


def test_a_grouped_extremum_may_be_cited_by_its_bucket_key():
    part = PartResultV2(
        part_id="P2",
        request_text="which floor has the most railings",
        result_kind="distribution",
        status=ResultStatusV2.EXACT,
        result=DistributionResult(
            base_cardinality=12,
            covered_cardinality=12,
            buckets=[DistributionBucketV2(key="floor:band:0", count=7, label="floor 1")],
            top_buckets=[DistributionBucketV2(key="floor:band:0", count=7, label="floor 1")],
        ),
    )
    packet = build_answer_packet_v2("which floor has the most railings", [part])
    generated = GroundedAnswerV2(
        answer="Floor 1 has the most, with 7.",
        claims=[
            GroundedClaim(kind=ClaimKind.FACT, cited_id="P2:top1", value="floor 1"),
            GroundedClaim(kind=ClaimKind.FACT, cited_id="P2:top1", value="7"),
        ],
    )
    validation = validate_answer_v2(generated, packet)
    assert validation.ok, validation.failures


@pytest.mark.parametrize(
    "status,result",
    [
        (ResultStatusV2.EXACT, ScalarResult(function="count", value=12)),
        (ResultStatusV2.ZERO, ScalarResult(function="count", value=0)),
        (
            ResultStatusV2.PARTIAL,
            ScalarResult(
                function="count",
                value=5,
                covered_cardinality=5,
                eligible_cardinality=12,
            ),
        ),
        (ResultStatusV2.UNAVAILABLE, None),
    ],
)
def test_the_deterministic_fallback_is_plain_language_for_every_status(status, result):
    part = PartResultV2(
        part_id="P1",
        request_text="how many railings are there",
        result_kind="scalar",
        status=status,
        result=result,
    )
    if status is ResultStatusV2.UNAVAILABLE:
        part.add_limitation(
            "MANIFEST_CAPABILITY_GAP",
            "prop:Pset_RailingCommon.Category is not recorded",
        )
    packet = build_answer_packet_v2("how many railings", [part])
    fallback = build_fallback_answer_v2(packet)
    assert fallback
    assert not banned_terms_in(fallback)


def test_limitation_text_is_recorded_in_readable_words():
    part = _exact_part()
    part.add_limitation(
        "COVERAGE_PROOF_GAP",
        "prop:Pset_RailingCommon.FireRating is partially covered on the target classes; "
        "a zero match cannot prove real-world absence",
    )
    text = part.limitations[0]["text"]
    assert "fire rating" in text
    assert not banned_terms_in(text)


def test_property_names_are_humanized():
    assert humanize_semantic_id("prop:Pset_WallCommon.FireRating") == "fire rating"
    assert humanize_semantic_id("cls:IfcWallStandardCase") == "wall standard case"
    assert humanize_semantic_id("mat:material.name") == "material"
    assert "fire rating" in humanize_text("prop:Pset_WallCommon.FireRating is unrecorded")
