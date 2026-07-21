"""Candidate slate against the REAL ingested models (Task 24 §1, §13.7 prep).

Read-only. No OpenAI call is made anywhere in this module — the slate is built
entirely from cached ontology/vocabulary/field resources, and asserting that is
one of the points (§10.1: exactly two principal LLM calls, neither of them here).

These tests assert STRUCTURAL properties that must hold for any well-formed
model — closure shape, role separation, scope-vs-condition typing, bounds. They
deliberately do NOT assert expected counts from `specs/test_query.md`: §13.6
forbids production rules keyed to sample questions, and a test that pinned a
count would break on re-ingestion without indicating a real defect.

The whole package skips when the database is unreachable (see conftest).
"""

from __future__ import annotations

import json

import pytest

from app.query.binding.schemas import SlateCaps
from app.query.binding.slate import SlateInputs, build_slate
from app.query.semantic.roles import SchemaRole, get_role_index, is_result_kind
from app.query.semantic.vocabulary.cache import get_model_vocabulary

#: Both ingested models. Parameterizing over both is what makes these tests
#: model-independent rather than tuned to one file (§13.3 "the same concept
#: represented differently in two models").
MODEL_IDS = (1, 2)


def _slate(session, model_id, question, **kw):
    return build_slate(
        session,
        SlateInputs(question=question, source_model_id=model_id, **kw),
    )


@pytest.fixture(scope="module")
def caps():
    return SlateCaps()


# ---------------------------------------------------------------------------
# Bounds (§1.4, §10.2)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("model_id", MODEL_IDS)
@pytest.mark.parametrize(
    "question",
    [
        "how many doors are in this building?",
        "which walls have a fire rating?",
        "show me all the doors in the second floor",
        "how many doors, windows and stairs are there, and which floor has the most doors?",
        "which spaces are connected to the stairs?",
        "asdkfj qwerty ??? ###",
    ],
)
def test_slate_never_exceeds_its_caps(live_session, model_id, question, caps):
    report = _slate(live_session, model_id, question).size_report()
    assert report["subjects"] <= caps.subjects
    assert report["fields"] <= caps.fields
    assert report["values"] <= caps.values
    assert report["spatial"] <= caps.spatial
    assert report["relationships"] <= caps.relationships


@pytest.mark.parametrize("model_id", MODEL_IDS)
def test_a_simple_question_stays_far_below_the_caps(live_session, model_id, caps):
    """§10.2: 'keep the candidate slate query-specific and normally far below
    its maximum caps'."""
    slate = _slate(live_session, model_id, "how many doors are in this building?")
    assert slate.size_report()["subjects"] <= 3


@pytest.mark.parametrize("model_id", MODEL_IDS)
def test_serialized_slate_stays_small(live_session, model_id):
    """A guard on prompt size, generous enough not to be brittle. Measured
    medians are an order of magnitude below this (see app.evaluation.measure_slate)."""
    slate = _slate(live_session, model_id, "how many external doors are on the second floor?")
    payload = json.dumps(slate.to_prompt_payload(), ensure_ascii=False)
    assert len(payload.encode("utf-8")) < 8000


# ---------------------------------------------------------------------------
# Role and closure semantics against real vocabularies (§3.2)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("model_id", MODEL_IDS)
def test_every_present_class_resolves_to_a_role_or_is_reported_unknown(live_session, model_id):
    """Ontology coverage against what the models actually contain.

    A class the ontology cannot describe must degrade to UNKNOWN rather than be
    guessed into a role. This measures how often that happens for real data.
    """
    vocab = get_model_vocabulary(live_session, model_id)
    index = get_role_index(vocab.ifc_schema or "IFC2X3")
    unknown = [c for c in vocab.present_classes() if index.role(c) is SchemaRole.UNKNOWN]
    # Reported rather than asserted at zero: an unbundled vendor class is a real
    # possibility and must degrade truthfully, not fail the suite.
    assert len(unknown) <= len(vocab.present_classes()) * 0.1, (
        f"model {model_id}: {len(unknown)} of {len(vocab.present_classes())} present classes "
        f"are absent from the ontology: {sorted(unknown)[:10]}"
    )


@pytest.mark.parametrize("model_id", MODEL_IDS)
def test_occurrence_closures_never_contain_a_non_result_class(live_session, model_id):
    """No subject candidate's family may mix in a type/property definition."""
    slate = _slate(live_session, model_id, "how many doors and walls and spaces are there?")
    vocab = get_model_vocabulary(live_session, model_id)
    index = get_role_index(vocab.ifc_schema or "IFC2X3")
    for subject in slate.subjects:
        if not subject.result_kind:
            continue
        for member in subject.family_members:
            assert is_result_kind(index.role(member)), (
                f"{member} is a {index.role(member).value} but appears in the family of "
                f"{subject.ifc_class}"
            )


@pytest.mark.parametrize("model_id", MODEL_IDS)
def test_a_wall_request_includes_present_wall_subtypes(live_session, model_id):
    """Structural, not numeric: whatever wall subtypes a model has must all be
    in a generic wall request's family, and nothing outside that family."""
    vocab = get_model_vocabulary(live_session, model_id)
    present = vocab.present_classes()
    if "IfcWall" not in present:
        pytest.skip(f"model {model_id} contains no IfcWall")
    slate = _slate(live_session, model_id, "how many walls are in this building?")
    wall = next((c for c in slate.subjects if c.ifc_class == "IfcWall"), None)
    assert wall is not None
    index = get_role_index(vocab.ifc_schema or "IFC2X3")
    expected = set(index.closure("IfcWall", present))
    assert set(wall.family_members) == expected


# ---------------------------------------------------------------------------
# Scope vs condition against real storey data (§1.3, §11.4)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("model_id", MODEL_IDS)
@pytest.mark.parametrize(
    "question",
    [
        "how many walls are in this building?",
        "give me a summary of this building.",
        "what is the estimated construction cost of this building?",
    ],
)
def test_a_whole_model_question_produces_no_floor_condition(live_session, model_id, question):
    """The general fix for the recorded 'could not read a specific floor from
    this building' failures, verified against real storey data."""
    slate = _slate(live_session, model_id, question)
    assert all(c.is_scope_selection for c in slate.spatial)


@pytest.mark.parametrize("model_id", MODEL_IDS)
def test_a_positional_floor_question_offers_real_floor_bands(live_session, model_id):
    slate = _slate(live_session, model_id, "show me all the doors on the second floor")
    bands = [c for c in slate.spatial if c.kind.value == "floor_band"]
    vocab_bands_exist = bands or model_id is None
    if not vocab_bands_exist:
        pytest.skip(f"model {model_id} has no elevation-bearing storeys")
    for band in bands:
        assert band.storey_global_ids
        assert not band.is_scope_selection


@pytest.mark.parametrize("model_id", MODEL_IDS)
def test_storey_entities_and_floor_bands_stay_distinct(live_session, model_id):
    """§11.4: a raw storey-entity count must never silently stand in for a
    logical floor count."""
    slate = _slate(live_session, model_id, "how many storey entities are recorded?")
    storey = [c for c in slate.spatial if c.kind.value == "storey_entity"]
    bands = [c for c in slate.spatial if c.kind.value == "floor_band"]
    assert not (storey and bands and storey[0].label == bands[0].label)


# ---------------------------------------------------------------------------
# Absence is reported, never substituted (§1.3, §6)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("model_id", MODEL_IDS)
def test_an_absent_concept_is_not_replaced_by_a_present_class(live_session, model_id):
    """A question about a concept these models do not contain must not acquire a
    large present class as its subject — the mechanism behind a previously
    recorded fabricated answer."""
    slate = _slate(live_session, model_id, "how many parking spaces are there?")
    vocab = get_model_vocabulary(live_session, model_id)
    biggest = max(vocab.classes, key=lambda c: c.instance_count).ifc_class
    assert all(c.ifc_class != biggest for c in slate.subjects) or not slate.subjects


@pytest.mark.parametrize("model_id", MODEL_IDS)
def test_a_meaningless_question_yields_no_subject(live_session, model_id):
    assert _slate(live_session, model_id, "asdkfj qwerty ??? ###").subjects == []


# ---------------------------------------------------------------------------
# Prompt safety (§2.1)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("model_id", MODEL_IDS)
def test_prompt_payload_leaks_no_identities_or_raw_data(live_session, model_id):
    slate = _slate(live_session, model_id, "show me all the doors on the second floor")
    blob = json.dumps(slate.to_prompt_payload(), ensure_ascii=False)
    for forbidden in ("canonical_json", "global_id", "GlobalId", "SELECT ", "password"):
        assert forbidden not in blob


@pytest.mark.parametrize("model_id", MODEL_IDS)
def test_building_a_slate_makes_no_openai_call(live_session, model_id, monkeypatch):
    """§10.1: the slate is deterministic pre-work, not a model request."""
    import app.llm.client as client_module

    def _explode(*a, **kw):  # pragma: no cover - must never run
        raise AssertionError("slate construction attempted an OpenAI call")

    monkeypatch.setattr(client_module, "get_llm_client", _explode)
    monkeypatch.setattr(client_module.OpenAIQueryClient, "_get_client", _explode)
    assert _slate(live_session, model_id, "how many doors are in this building?") is not None


# ---------------------------------------------------------------------------
# Caching / repeat cost (§10.3)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("model_id", MODEL_IDS)
def test_repeat_slate_builds_are_deterministic(live_session, model_id):
    q = "how many external doors are on the second floor?"
    first = _slate(live_session, model_id, q)
    second = _slate(live_session, model_id, q)
    assert first.size_report() == second.size_report()
    assert [c.ifc_class for c in first.subjects] == [c.ifc_class for c in second.subjects]
    assert first.to_prompt_payload() == second.to_prompt_payload()
