"""Candidate-slate construction (Task 24 §1, §13.2, §13.6).

Offline against the synthetic model in `conftest.py`. No DB, no OpenAI, no
embedding service (the slate must be buildable without one).

No test asserts a count or a class list taken from `specs/test_query.md`; the
synthetic model's numbers are invented for these tests.
"""

from __future__ import annotations

import json

import pytest

from app.query.binding.schemas import MatchTier, SlateCaps, SpatialKind
from app.query.binding.slate import SlateInputs, build_slate

from .conftest import SYNTHETIC_MODEL_ID


def _slate(question, **kw):
    return build_slate(
        session=None,
        inputs=SlateInputs(question=question, source_model_id=SYNTHETIC_MODEL_ID, **kw),
    )


def _subject_classes(slate) -> list[str]:
    return [c.ifc_class for c in slate.subjects]


# ---------------------------------------------------------------------------
# The three ways a subject can be named (§1.2)
# ---------------------------------------------------------------------------


def test_subject_found_by_class_name(slate_env):
    slate = _slate("how many curtain walls are there?")
    assert "IfcCurtainWall" in _subject_classes(slate)


def test_subject_found_by_a_stored_value_not_present_in_any_class_name(slate_env):
    """ "rooms" corresponds to no IFC class; the model records it as an object
    type on IfcSpace. Class-name matching alone would never find it."""
    slate = _slate("how many rooms are in this building?")
    space = next(c for c in slate.subjects if c.ifc_class == "IfcSpace")
    assert space.match_tier is MatchTier.OBSERVED_VALUE
    assert space.is_exact_match


def test_subject_found_by_a_schema_predefined_type(slate_env):
    """An absent concept must still be RECOGNIZED, so it can be reported absent
    rather than drifting to a present class (§1.3)."""
    slate = _slate("how many escalators are in this building?")
    assert any(c.match_tier is MatchTier.PREDEFINED_TYPE for c in slate.subjects)


# ---------------------------------------------------------------------------
# Exact-before-semantic and capping (§1.2, §1.4)
# ---------------------------------------------------------------------------


def test_every_explicit_noun_of_a_compound_question_survives(slate_env):
    """§1.2: a compound question naming several BIM nouns must not lose one."""
    slate = _slate("how many doors, walls and stairs are there?")
    classes = _subject_classes(slate)
    for expected in ("IfcDoor", "IfcWall", "IfcStair"):
        assert expected in classes, f"{expected} lost from the slate"


def test_exact_matches_are_ordered_before_semantic_supplements(slate_env):
    slate = _slate("how many doors and walls are there?")
    tiers = [c.match_tier for c in slate.subjects]
    exact_positions = [i for i, t in enumerate(tiers) if t is not MatchTier.SEMANTIC]
    semantic_positions = [i for i, t in enumerate(tiers) if t is MatchTier.SEMANTIC]
    assert not semantic_positions or max(exact_positions) < min(semantic_positions)


def test_slate_respects_its_caps(slate_env):
    caps = SlateCaps(subjects=2, fields=2, values=2, spatial=2, relationships=2)
    slate = build_slate(
        session=None,
        inputs=SlateInputs(
            question="doors walls stairs spaces external fire rating on the second floor",
            source_model_id=SYNTHETIC_MODEL_ID,
        ),
        caps=caps,
    )
    report = slate.size_report()
    assert report["subjects"] <= 2
    assert report["fields"] <= 2
    assert report["values"] <= 2
    assert report["spatial"] <= 2


def test_a_simple_question_produces_a_small_slate(slate_env):
    """§1.4: caps are maxima, not quotas. A simple exact question should get one
    obvious subject and only the implied fields."""
    slate = _slate("how many curtain walls are there?")
    assert slate.size_report()["subjects"] <= 3
    assert slate.size_report()["fields"] <= 2


# ---------------------------------------------------------------------------
# Role and family semantics carried into the slate (§1.3, §3.2)
# ---------------------------------------------------------------------------


def test_generic_superclass_candidate_carries_its_present_subtypes(slate_env):
    slate = _slate("how many walls are there?")
    wall = next(c for c in slate.subjects if c.ifc_class == "IfcWall")
    assert set(wall.family_members) == {"IfcWall", "IfcWallStandardCase"}
    # Cached counts only — the sum of the family, never a fresh COUNT(*).
    assert wall.exact_count == 100


def test_a_door_subject_does_not_absorb_the_co_present_door_style(slate_env):
    slate = _slate("how many doors are there?")
    door = next(c for c in slate.subjects if c.ifc_class == "IfcDoor")
    assert "IfcDoorStyle" not in door.family_members
    assert door.exact_count == 25


def test_a_type_definition_candidate_is_marked_as_not_a_result_kind(slate_env):
    slate = _slate("show me the door styles")
    styles = [c for c in slate.subjects if c.ifc_class == "IfcDoorStyle"]
    if styles:
        assert styles[0].result_kind is False
        assert styles[0].schema_role == "type_definition"


def test_a_stair_subject_does_not_absorb_stair_flights(slate_env):
    slate = _slate("how many stairs are there?")
    stair = next(c for c in slate.subjects if c.ifc_class == "IfcStair")
    assert "IfcStairFlight" not in stair.family_members
    assert stair.exact_count == 7


# ---------------------------------------------------------------------------
# Field and value candidates (§1.3, §4)
# ---------------------------------------------------------------------------


def test_field_candidates_are_implied_by_the_question(slate_env):
    slate = _slate("which walls have a fire rating?")
    assert any(f.field_name == "FireRating" for f in slate.fields)


def test_a_value_identified_subject_also_gets_its_field_offered(slate_env):
    """Regression guard for a defect this suite caught during implementation.

    "rooms" names no IFC class and no field name — it exists only as a stored
    object-type VALUE on spaces. The subject resolved correctly, but the field
    carrying that value was never offered, so the binder had no way to express
    "the spaces recorded as rooms" and would have answered with EVERY space.
    The evidence that identifies a subject must itself be bindable.
    """
    slate = _slate("how many rooms are in this building?")
    assert any(c.ifc_class == "IfcSpace" for c in slate.subjects)
    assert any(f.field_name == "object_type" for f in slate.fields), (
        "the field carrying the identifying value must be offered as a candidate"
    )
    assert any(v.value == "Rooms" for v in slate.values)


def test_value_candidates_reference_a_field_candidate_in_the_same_slate(slate_env):
    slate = _slate("which spaces are rooms?")
    for value in slate.values:
        assert slate.field_candidate(value.field_candidate_id) is not None


def test_field_coverage_state_is_reported_not_conflated_with_zero(slate_env):
    """§6: missing field coverage is not a zero value."""
    slate = _slate("which walls have a fire rating?")
    fire = next(f for f in slate.fields if f.field_name == "FireRating")
    assert fire.coverage_state == "partial"
    assert any("coverage is partial" in note for note in slate.coverage_notes)


def test_absent_class_is_reported_in_coverage_notes(slate_env):
    slate = _slate("how many escalators are in this building?")
    assert any("not present in this model" in note for note in slate.coverage_notes)


# ---------------------------------------------------------------------------
# Spatial candidates — scope vs condition (§1.3, §11.4)
# ---------------------------------------------------------------------------


def test_active_model_scope_is_always_offered(slate_env):
    slate = _slate("how many walls are in this building?")
    active = [c for c in slate.spatial if c.kind is SpatialKind.ACTIVE_MODEL]
    assert len(active) == 1
    assert active[0].is_scope_selection


def test_a_whole_model_question_offers_no_floor_condition(slate_env):
    """The general fix for a recorded family of failures: a question naming the
    building as a whole must not acquire a floor predicate."""
    slate = _slate("how many walls are in this building?")
    assert not [c for c in slate.spatial if c.kind is SpatialKind.FLOOR_BAND]
    assert all(c.is_scope_selection for c in slate.spatial)


@pytest.mark.parametrize(
    "question",
    [
        "how many doors are in this building?",
        "how many walls are in this building?",
        "give me a summary of this building",
    ],
)
def test_a_word_used_as_scope_does_not_also_become_a_subject(slate_env, question):
    """Regression guard for a defect a LIVE smoke run caught.

    Offering `IfcBuilding` as a countable subject for "…in this building" invited
    the binder to write a condition constraining on it, which validation then
    rejected — so a perfectly ordinary question failed. A word already consumed
    by a scope reference must not also advertise itself as a thing to count.
    """
    assert "IfcBuilding" not in _subject_classes(_slate(question))


def test_a_question_genuinely_about_buildings_still_gets_the_subject(slate_env):
    """The suppression must be narrow: plural "buildings" is not a scope
    reference, so the subject survives."""
    slate = _slate("how many buildings are in the model?")
    assert any(c.ifc_class == "IfcBuilding" for c in slate.subjects)


def test_selection_and_previous_result_are_scope_selections_not_conditions(slate_env):
    slate = _slate(
        "how many of those are external?",
        selected_entities=[{"entity_id": 1}],
        previous_scope=object(),
    )
    kinds = {c.kind for c in slate.spatial}
    assert SpatialKind.SELECTION in kinds
    assert SpatialKind.PREVIOUS_RESULT in kinds
    for candidate in slate.spatial:
        if candidate.kind in (SpatialKind.SELECTION, SpatialKind.PREVIOUS_RESULT):
            assert candidate.is_scope_selection


# ---------------------------------------------------------------------------
# Relationship candidates (§1.3)
# ---------------------------------------------------------------------------


def test_relationship_candidates_only_appear_for_connectivity_questions(slate_env):
    assert _slate("how many doors are there?").relationships == []
    connected = _slate("which spaces are connected to the stairs?")
    assert connected.relationships


def test_the_relevant_relationship_outranks_a_far_more_numerous_one(slate_env):
    """Regression guard for a defect this suite caught during implementation.

    Relationship candidates were ordered purely by instance count, so on a real
    model containment (a few hundred rows) fell outside the six-candidate cap
    beneath property and material associations (several thousand) — and a
    question saying "contained in" could not reach the containment relationship
    at all. Relevance to the question must outrank volume. Same defect shape as
    the subject-specificity and set-name cases: eligibility/ordering must follow
    meaning, not magnitude.
    """
    slate = _slate("which spaces are contained in the storeys?")
    assert slate.relationships
    assert slate.relationships[0].ifc_class == "IfcRelContainedInSpatialStructure"


def test_stem_matching_bridges_verb_forms_in_relationship_ranking(slate_env):
    """ "contained" must reach "containment"/"ContainedIn"; "connected" must
    reach "Connects". Plain token equality cannot do either."""
    from app.query.binding.lexical import stems_match

    assert stems_match("contained", "containment")
    assert stems_match("connected", "connects")
    assert not stems_match("wall", "walk")
    assert not stems_match("door", "floor")


def test_relationship_candidates_report_availability(slate_env):
    slate = _slate("which spaces are contained in the storeys?")
    for candidate in slate.relationships:
        assert candidate.available is (candidate.instance_count > 0)


# ---------------------------------------------------------------------------
# Anti-overfitting (§13.6)
# ---------------------------------------------------------------------------


def test_an_injected_high_count_irrelevant_class_does_not_take_over(slate_env):
    """The synthetic model's IfcBuildingElementProxy has by far the highest
    count. It must not displace the class the question actually names."""
    slate = _slate("how many curtain walls are there?")
    assert slate.subjects[0].ifc_class == "IfcCurtainWall"
    assert "IfcBuildingElementProxy" not in _subject_classes(slate)


@pytest.mark.parametrize(
    ("question", "specific", "broader"),
    [
        ("how many curtain walls are there?", "IfcCurtainWall", "IfcWall"),
        ("how many stair flights are there?", "IfcStairFlight", "IfcStair"),
    ],
)
def test_a_more_specific_reading_outranks_a_broader_one(slate_env, question, specific, broader):
    """Regression guard for a defect this suite caught during implementation.

    A compound noun exact-matches BOTH the specific class and its broader
    namesake ("curtain walls" matches `IfcCurtainWall` and also `IfcWall`,
    because "wall" is present). Ordering by instance count put the far more
    numerous generic class first, so a question about curtain walls would have
    been answered with every wall in the building. Specificity must outrank
    count. Asserted on two unrelated families.
    """
    slate = _slate(question)
    classes = _subject_classes(slate)
    assert classes[0] == specific
    if broader in classes:
        assert classes.index(specific) < classes.index(broader)


def test_absent_exact_candidate_is_not_replaced_by_a_broad_present_class(slate_env):
    """§1.3: 'an ontology candidate that is semantically exact but absent from
    the active model must remain eligible'."""
    slate = _slate("how many escalators are in this building?")
    assert slate.subjects, "an absent concept must still produce a candidate"
    assert all(c.ifc_class != "IfcBuildingElementProxy" for c in slate.subjects)


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("how many doors are there?", "what is the total number of doors?"),
        ("show me the curtain walls", "list every curtain wall"),
    ],
)
def test_rewording_without_changing_meaning_preserves_the_subject(slate_env, a, b):
    """§13.6: changing only wording preserves the same binding."""
    assert _subject_classes(_slate(a))[:1] == _subject_classes(_slate(b))[:1]


def test_occurrence_and_explicit_type_requests_differ(slate_env):
    """§13.6: changing from an occurrence request to an explicit type request
    changes the binding."""
    occurrence = _slate("how many doors are there?")
    type_request = _slate("how many door styles are there?")
    assert occurrence.subjects[0].ifc_class == "IfcDoor"
    assert any(c.ifc_class == "IfcDoorStyle" for c in type_request.subjects)


# ---------------------------------------------------------------------------
# Similarity may rank, never admit (measured decision — see slate._rank_semantically)
# ---------------------------------------------------------------------------


class _StubEmbedding:
    """Returns a vector for anything, so similarity is always computable.

    If similarity were allowed to ADMIT candidates, this stub would let every
    question fill the slate — which is precisely the behaviour under test.
    """

    def embed_query(self, text):
        import numpy as np

        return np.ones(1024, dtype="float32") / 32.0


def test_similarity_cannot_introduce_a_subject_with_no_exact_evidence(slate_env):
    """The measured failure this guards against.

    Embedding similarity over IFC definitions offers `IfcSpace` for a parking
    question and `IfcRailing` for a bicycle-rack question — the exact mechanism
    that once produced a confident "778 parking spaces" for a model containing
    none. §Non-negotiable rule: an exact empty representation outranks a
    semantically similar but different non-empty class.
    """
    without = build_slate(
        session=None,
        inputs=SlateInputs(
            question="how many parking spaces are there?", source_model_id=SYNTHETIC_MODEL_ID
        ),
    )
    with_embeddings = build_slate(
        session=None,
        inputs=SlateInputs(
            question="how many parking spaces are there?", source_model_id=SYNTHETIC_MODEL_ID
        ),
        embedding_service_getter=lambda: _StubEmbedding(),
    )
    assert _subject_classes(with_embeddings) == _subject_classes(without)


def test_a_meaningless_question_does_not_fill_the_slate(slate_env):
    """§1.4: caps are maxima, not quotas. Nonsense input must not produce a full
    slate of confident-looking candidates."""
    slate = build_slate(
        session=None,
        inputs=SlateInputs(question="asdkfj qwerty ??? ###", source_model_id=SYNTHETIC_MODEL_ID),
        embedding_service_getter=lambda: _StubEmbedding(),
    )
    assert slate.subjects == []


def test_an_unavailable_embedding_service_never_breaks_the_slate(slate_env):
    """Ranking is optional; losing it degrades order, not usability."""

    def _broken():
        raise RuntimeError("embedding service down")

    slate = build_slate(
        session=None,
        inputs=SlateInputs(
            question="how many doors and walls are there?", source_model_id=SYNTHETIC_MODEL_ID
        ),
        embedding_service_getter=_broken,
    )
    assert "IfcDoor" in _subject_classes(slate)
    assert "IfcWall" in _subject_classes(slate)


def test_slate_is_deterministic(slate_env):
    q = "how many external doors and walls are on the second floor?"
    first, second = _slate(q), _slate(q)
    assert first.size_report() == second.size_report()
    assert _subject_classes(first) == _subject_classes(second)


# ---------------------------------------------------------------------------
# Prompt payload bounds (§2.1, §10.2)
# ---------------------------------------------------------------------------


def test_prompt_payload_carries_no_forbidden_content(slate_env):
    """§2.1: no canonical JSON, no full vocabulary, no rows, no embeddings, no
    viewer identities."""
    slate = _slate("how many external doors are on the second floor?")
    blob = json.dumps(slate.to_prompt_payload())
    for forbidden in ("canonical_json", "global_id", "GlobalId", "similarity", "SELECT", "vector"):
        assert forbidden not in blob


def test_prompt_payload_omits_empty_structures(slate_env):
    """§10.2: omit null/irrelevant fields rather than serializing large empty
    structures."""
    payload = _slate("how many doors are there?").to_prompt_payload()
    assert "relationships" not in payload
    for subject in payload["subjects"]:
        assert None not in subject.values()
        assert [] not in subject.values()


def test_catalog_scope_slate_is_empty_but_valid(slate_env):
    slate = build_slate(
        session=None, inputs=SlateInputs(question="what models do you have?", source_model_id=None)
    )
    assert slate.subjects == [] and slate.fields == []
    assert slate.to_prompt_payload() is not None


@pytest.mark.parametrize(
    "question",
    [
        "how many external doors are on the second floor?",
        # Regression: inserting the logical-floor subject renumbered the others
        # and reused an id, so `slate.subject(id)` silently returned the WRONG
        # candidate — a graph question then seeded from the wrong family.
        "which walls are contained in the building storeys?",
        "how many floors does this building have?",
        "how many doors, walls and stairs are there?",
    ],
)
def test_candidate_ids_are_unique_and_stable(slate_env, question):
    slate = _slate(question)
    for group in (slate.subjects, slate.fields, slate.values, slate.spatial, slate.relationships):
        ids = [c.candidate_id for c in group]
        assert len(ids) == len(set(ids)), f"duplicate ids in {question!r}: {ids}"
        assert all(ids)
    # Every id must resolve back to the candidate it belongs to.
    for subject in slate.subjects:
        assert slate.subject(subject.candidate_id) is subject
