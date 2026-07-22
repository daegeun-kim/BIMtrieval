"""Authoritative execution against the REAL models (Task 24 §5, §6, §13.4).

Read-only. **No OpenAI call is made anywhere in this module** — bindings are
constructed directly, which is exactly the "deterministic binding fixture"
§13.1 asks for. That also means these tests exercise execution without paying
for or depending on a model call.

Assertions are structural and cross-checked against the database itself (e.g.
"the count equals an independent COUNT(*) over the same classes") rather than
against numbers copied from `specs/test_query.md` — §13.6 forbids pinning
sample-specific expected counts, and a re-ingest must not break the suite.

The whole package skips when the database is unreachable (see conftest).
"""

from __future__ import annotations

import pytest
import sqlalchemy as sa

from app.db.models import IfcEntity
from app.llm.schemas import (
    AnswerPart,
    BindingPlan,
    BoundCondition,
    BoundOperator,
    OutputOperation,
    ScopeKind,
)
from app.query.binding.evidence import ResultStatus, RetrievalMode
from app.query.binding.execute import ExecutionContext, execute_answer_part
from app.query.binding.profile import build_building_profile
from app.query.binding.slate import SlateInputs, build_slate
from app.query.binding.validate import validate_binding

MODEL_IDS = (1, 2)
_ET = IfcEntity.__table__


def _slate(session, model_id, question, **kw):
    return build_slate(session, SlateInputs(question=question, source_model_id=model_id, **kw))


def _subject_id(slate, ifc_class):
    return next((c.candidate_id for c in slate.subjects if c.ifc_class == ifc_class), None)


def _run(session, model_id, slate, part, **ctx_kw):
    """Validate then execute one hand-built answer part."""
    plan = BindingPlan(answer_parts=[part])
    validation = validate_binding(plan, slate)
    context = ExecutionContext(session, model_id, slate, **ctx_kw)
    return execute_answer_part(validation.parts[0], context)


def _count_classes(session, model_id, classes) -> int:
    return session.execute(
        sa.select(sa.func.count())
        .select_from(_ET)
        .where(_ET.c.source_model_id == model_id, _ET.c.ifc_class.in_(list(classes)))
    ).scalar_one()


# ---------------------------------------------------------------------------
# One structured operation per answer part (§5.2)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("model_id", MODEL_IDS)
def test_a_count_matches_an_independent_count_over_the_same_family(live_session, model_id):
    """The executed result must equal the database's own answer for the family
    the closure selected — proving the family, not a number, is what is under
    test."""
    slate = _slate(live_session, model_id, "how many walls are in this building?")
    subject_id = _subject_id(slate, "IfcWall")
    if subject_id is None:
        pytest.skip(f"model {model_id} contains no IfcWall")
    part = AnswerPart(
        part_id="p1",
        request_text="how many walls",
        operation=OutputOperation.COUNT,
        subject_candidate_id=subject_id,
    )
    result = _run(live_session, model_id, slate, part)
    assert result.status is ResultStatus.EXACT
    family = slate.subject(subject_id).family_members
    assert result.exact_total == _count_classes(live_session, model_id, family)


@pytest.mark.parametrize("model_id", MODEL_IDS)
def test_a_simple_count_costs_a_small_bounded_number_of_statements(live_session, model_id):
    """§5.2: 'an answer part should normally require one typed structured
    query'. The count plus a bounded example fetch is the whole cost — there is
    no per-candidate query."""
    slate = _slate(live_session, model_id, "how many doors are in this building?")
    subject_id = _subject_id(slate, "IfcDoor")
    if subject_id is None:
        pytest.skip(f"model {model_id} contains no IfcDoor")
    result = _run(
        live_session,
        model_id,
        slate,
        AnswerPart(
            part_id="p1",
            request_text="how many doors",
            operation=OutputOperation.COUNT,
            subject_candidate_id=subject_id,
        ),
    )
    assert result.statement_count <= 3, result.statement_count
    assert result.modes_executed == (RetrievalMode.SQL,)


@pytest.mark.parametrize("model_id", MODEL_IDS)
def test_family_expansion_never_leaks_a_type_definition_into_a_count(live_session, model_id):
    """A door count must not include door STYLES, even when both are present."""
    slate = _slate(live_session, model_id, "how many doors are in this building?")
    subject_id = _subject_id(slate, "IfcDoor")
    if subject_id is None:
        pytest.skip(f"model {model_id} contains no IfcDoor")
    result = _run(
        live_session,
        model_id,
        slate,
        AnswerPart(
            part_id="p1",
            request_text="how many doors",
            operation=OutputOperation.COUNT,
            subject_candidate_id=subject_id,
        ),
    )
    assert "IfcDoorStyle" not in result.predicate.ifc_classes
    assert result.exact_total == _count_classes(live_session, model_id, ["IfcDoor"])


# ---------------------------------------------------------------------------
# Evidence status against real data (§6)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("model_id", MODEL_IDS)
def test_an_absent_concept_yields_zero_not_unavailable(live_session, model_id):
    """§6: 'zero is not unavailable'."""
    slate = _slate(live_session, model_id, "how many escalators are in this building?")
    absent = next((c for c in slate.subjects if not c.present and c.result_kind), None)
    if absent is None:
        pytest.skip(f"model {model_id} happens to contain the probed concept")
    result = _run(
        live_session,
        model_id,
        slate,
        AnswerPart(
            part_id="p1",
            request_text="how many escalators",
            operation=OutputOperation.COUNT,
            subject_candidate_id=absent.candidate_id,
        ),
    )
    assert result.status is ResultStatus.ZERO
    assert result.exact_total == 0
    assert "not necessarily the real building" in (result.limitation or "")


@pytest.mark.parametrize("model_id", MODEL_IDS)
def test_an_unresolvable_value_yields_unavailable_and_never_a_broader_count(live_session, model_id):
    """§6 final rule. The broad count must NOT be reported when a required
    condition could not be applied."""
    slate = _slate(live_session, model_id, "which walls have a fire rating of ZZ999?")
    subject_id = _subject_id(slate, "IfcWall")
    field = next((f for f in slate.fields if f.data_type == "text"), None)
    if subject_id is None or field is None:
        pytest.skip(f"model {model_id} offers no text field for this probe")
    result = _run(
        live_session,
        model_id,
        slate,
        AnswerPart(
            part_id="p1",
            request_text="walls with fire rating ZZ999",
            operation=OutputOperation.COUNT,
            subject_candidate_id=subject_id,
            conditions=[
                BoundCondition(
                    condition_id="c1",
                    candidate_id=field.candidate_id,
                    operator=BoundOperator.EQUALS,
                    value_text="ZZ999",
                    source_span="ZZ999",
                )
            ],
        ),
    )
    assert result.status is ResultStatus.UNAVAILABLE
    assert result.exact_total is None, "an unapplied condition must not report a broader total"


@pytest.mark.parametrize("model_id", MODEL_IDS)
def test_a_zero_or_unavailable_result_has_no_visual_result(live_session, model_id):
    """§9: exact zero / unavailable answers must not highlight a fallback set."""
    slate = _slate(live_session, model_id, "how many escalators are in this building?")
    absent = next((c for c in slate.subjects if not c.present and c.result_kind), None)
    if absent is None:
        pytest.skip("no absent concept available on this model")
    result = _run(
        live_session,
        model_id,
        slate,
        AnswerPart(
            part_id="p1",
            request_text="how many escalators",
            operation=OutputOperation.COUNT,
            subject_candidate_id=absent.candidate_id,
        ),
    )
    assert not result.has_visual_result


# ---------------------------------------------------------------------------
# Scope restricts, and the same predicate drives everything (§9)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("model_id", MODEL_IDS)
def test_a_floor_scope_narrows_the_result(live_session, model_id):
    slate = _slate(live_session, model_id, "how many doors are on the second floor?")
    subject_id = _subject_id(slate, "IfcDoor")
    band = next((c for c in slate.spatial if c.kind.value == "floor_band"), None)
    if subject_id is None or band is None:
        pytest.skip(f"model {model_id} has no doors or no floor bands")

    unscoped = _run(
        live_session,
        model_id,
        slate,
        AnswerPart(
            part_id="p1",
            request_text="doors",
            operation=OutputOperation.COUNT,
            subject_candidate_id=subject_id,
        ),
    )
    scoped = _run(
        live_session,
        model_id,
        slate,
        AnswerPart(
            part_id="p2",
            request_text="doors on the second floor",
            operation=OutputOperation.COUNT,
            subject_candidate_id=subject_id,
            scope_kind=ScopeKind.SPATIAL_CANDIDATE,
            scope_candidate_id=band.candidate_id,
        ),
    )
    assert scoped.status in (ResultStatus.EXACT, ResultStatus.ZERO)
    assert scoped.exact_total <= unscoped.exact_total
    assert scoped.interpretation, "the floor interpretation must be reported"


@pytest.mark.parametrize("model_id", MODEL_IDS)
def test_examples_come_from_the_same_predicate_as_the_count(live_session, model_id):
    """§9: answer and identities must derive from the same result."""
    slate = _slate(live_session, model_id, "show me the walls in this building")
    subject_id = _subject_id(slate, "IfcWall")
    if subject_id is None:
        pytest.skip(f"model {model_id} contains no IfcWall")
    result = _run(
        live_session,
        model_id,
        slate,
        AnswerPart(
            part_id="p1",
            request_text="walls",
            operation=OutputOperation.LIST,
            subject_candidate_id=subject_id,
        ),
    )
    family = set(result.predicate.ifc_classes)
    for example in result.examples:
        assert example.ifc_class in family


# ---------------------------------------------------------------------------
# Graph execution actually runs (§5.4, §13.4)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("model_id", MODEL_IDS)
def test_a_relationship_operation_actually_executes_traversal(live_session, model_id):
    """§5.4: graph must be wired in, not merely recorded as requested."""
    slate = _slate(live_session, model_id, "which walls are contained in the building storeys?")
    subject_id = _subject_id(slate, "IfcWall")
    relationship = next(
        (r for r in slate.relationships if r.ifc_class == "IfcRelContainedInSpatialStructure"),
        None,
    )
    if subject_id is None or relationship is None:
        pytest.skip(f"model {model_id} offers no containment relationship for walls")
    result = _run(
        live_session,
        model_id,
        slate,
        AnswerPart(
            part_id="p1",
            request_text="walls contained in storeys",
            operation=OutputOperation.RELATIONSHIP,
            subject_candidate_id=subject_id,
            relationship_candidate_id=relationship.candidate_id,
        ),
    )
    assert RetrievalMode.GRAPH in result.modes_executed
    assert result.status in (ResultStatus.EXACT, ResultStatus.ZERO, ResultStatus.UNAVAILABLE)
    if result.status is ResultStatus.EXACT:
        # Every claimed endpoint came from traversal, not a broad entity list.
        assert result.graph_endpoints
        assert result.exact_total == len(result.graph_endpoints)


@pytest.mark.parametrize("model_id", MODEL_IDS)
def test_an_unavailable_relationship_fabricates_no_connection(live_session, model_id):
    """§5.4/§6: a relationship the model does not record must produce
    unavailable evidence, never a plausible list of names."""
    slate = _slate(live_session, model_id, "which spaces are connected to the stairs?")
    subject_id = _subject_id(slate, "IfcSpace")
    if subject_id is None:
        pytest.skip(f"model {model_id} contains no IfcSpace")
    from app.query.binding.schemas import RelationshipCandidate

    slate.relationships = [
        RelationshipCandidate(
            candidate_id="rX",
            ifc_class="IfcRelConnectsElements",
            meaning="connection",
            available=False,
            instance_count=0,
        )
    ]
    result = _run(
        live_session,
        model_id,
        slate,
        AnswerPart(
            part_id="p1",
            request_text="spaces connected to stairs",
            operation=OutputOperation.RELATIONSHIP,
            subject_candidate_id=subject_id,
            relationship_candidate_id="rX",
        ),
    )
    assert result.status is ResultStatus.UNAVAILABLE
    assert not result.graph_endpoints
    assert not result.examples


@pytest.mark.parametrize("model_id", MODEL_IDS)
def test_graph_endpoints_are_filtered_to_the_requested_family(live_session, model_id):
    """§5.4: 'filter endpoint results to the requested endpoint semantics'."""
    slate = _slate(live_session, model_id, "which walls are contained in the building storeys?")
    subject_id = _subject_id(slate, "IfcWall")
    storey_id = _subject_id(slate, "IfcBuildingStorey")
    relationship = next(
        (r for r in slate.relationships if r.ifc_class == "IfcRelContainedInSpatialStructure"),
        None,
    )
    if not (subject_id and storey_id and relationship):
        pytest.skip(f"model {model_id} does not offer this endpoint combination")

    def _traverse(endpoint_candidate_id):
        return _run(
            live_session,
            model_id,
            slate,
            AnswerPart(
                part_id="p1",
                request_text="what the storeys contain",
                operation=OutputOperation.RELATIONSHIP,
                # Seed FROM the storeys, so traversal reaches a genuinely MIXED
                # set of contained element classes. Seeding from walls would
                # only ever reach storeys, making the filter assertion vacuous.
                subject_candidate_id=storey_id,
                relationship_candidate_id=relationship.candidate_id,
                endpoint_subject_candidate_id=endpoint_candidate_id,
            ),
        )

    unfiltered = _traverse(None)
    filtered = _traverse(subject_id)

    unfiltered_classes = {e.ifc_class for e in unfiltered.graph_endpoints}
    filtered_classes = {e.ifc_class for e in filtered.graph_endpoints}
    allowed = set(slate.subject(subject_id).family_members)

    assert len(unfiltered_classes) > 1, (
        "seed should reach a mixed set for this test to mean anything"
    )
    assert filtered_classes, "filtering must not empty a non-empty traversal"
    assert filtered_classes <= allowed
    assert filtered_classes < unfiltered_classes
    assert len(filtered.graph_endpoints) < len(unfiltered.graph_endpoints)


# ---------------------------------------------------------------------------
# Scoped RAG (§5.3, §13.4)
# ---------------------------------------------------------------------------


def test_scoped_rag_with_an_empty_scope_returns_nothing_and_does_not_widen(live_session):
    """§5.3: 'keep an empty scoped RAG result empty; do not widen to whole-model
    RAG'. Uses a stub encoder so no model load or GPU work is needed."""
    from app.query.rag.schemas import RagSearchPlan
    from app.query.rag.search import run_rag_search

    class _StubEncoder:
        def embed_query(self, text):
            return [0.0] * 1024

    result = run_rag_search(
        live_session,
        _StubEncoder(),
        RagSearchPlan(
            source_model_id=1,
            semantic_query="anything at all",
            search_entity_documents=True,
            search_relationship_documents=False,
            scope_entity_ids=[],
        ),
    )
    assert result.entity_candidates == []
    assert not result.sufficient_evidence
    assert any("structured scope" in w for w in result.warnings), (
        "an empty scope must be reported distinctly from a semantic miss"
    )


def test_scoped_rag_never_returns_anything_outside_its_scope(live_session):
    from app.query.rag.schemas import RagSearchPlan
    from app.query.rag.search import run_rag_search

    class _StubEncoder:
        def embed_query(self, text):
            return [0.0] * 1024

    scope = [
        r[0]
        for r in live_session.execute(
            sa.select(_ET.c.id).where(_ET.c.source_model_id == 1).order_by(_ET.c.id).limit(5)
        )
    ]
    result = run_rag_search(
        live_session,
        _StubEncoder(),
        RagSearchPlan(
            source_model_id=1,
            semantic_query="anything at all",
            search_entity_documents=True,
            search_relationship_documents=False,
            scope_entity_ids=scope,
        ),
    )
    for candidate in result.entity_candidates:
        assert candidate.canonical_id in scope


def test_unscoped_rag_still_searches_the_whole_model(live_session):
    """The scoping feature must not change default behaviour: `None` means
    unscoped, which is distinct from an empty list."""
    from app.query.rag.schemas import RagSearchPlan
    from app.query.rag.search import run_rag_search

    class _StubEncoder:
        def embed_query(self, text):
            return [0.0] * 1024

    result = run_rag_search(
        live_session,
        _StubEncoder(),
        RagSearchPlan(
            source_model_id=1,
            semantic_query="anything at all",
            search_entity_documents=True,
            search_relationship_documents=False,
            scope_entity_ids=None,
        ),
    )
    assert result.entity_candidates, "unscoped search must still return candidates"


# ---------------------------------------------------------------------------
# Building profile (§11.2)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("model_id", MODEL_IDS)
def test_building_profile_is_bounded_and_cheap(live_session, model_id):
    profile = build_building_profile(live_session, model_id)
    assert profile.statement_count <= 2, "a summary must not count every class"
    assert len(profile.occurrence_families) <= 12
    assert profile.total_entity_count > 0


@pytest.mark.parametrize("model_id", MODEL_IDS)
def test_building_profile_keeps_logical_floors_distinct_from_storey_entities(
    live_session, model_id
):
    """§11.4: a storey-entity count must never stand in for a logical floor
    count. Both are reported, as separate facts."""
    profile = build_building_profile(live_session, model_id)
    payload = profile.to_payload()
    assert "logical_floor_count" in payload and "storey_entity_count" in payload
    assert profile.logical_floor_count <= profile.storey_entity_count


@pytest.mark.parametrize("model_id", MODEL_IDS)
def test_building_profile_lists_only_occurrence_families(live_session, model_id):
    """A summary of "what the building contains" must not list type definitions."""
    from app.query.semantic.roles import SchemaRole, get_role_index
    from app.query.semantic.vocabulary.cache import get_model_vocabulary

    vocab = get_model_vocabulary(live_session, model_id)
    index = get_role_index(vocab.ifc_schema or "IFC2X3")
    profile = build_building_profile(live_session, model_id)
    for ifc_class, _count in profile.occurrence_families:
        assert index.role(ifc_class) is SchemaRole.OCCURRENCE


# ---------------------------------------------------------------------------
# No model call anywhere in execution (§10.1)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("model_id", MODEL_IDS)
def test_execution_makes_no_openai_call(live_session, model_id, monkeypatch):
    import app.llm.client as client_module

    def _explode(*a, **kw):  # pragma: no cover - must never run
        raise AssertionError("execution attempted an OpenAI call")

    monkeypatch.setattr(client_module, "get_llm_client", _explode)
    monkeypatch.setattr(client_module.OpenAIQueryClient, "_get_client", _explode)

    slate = _slate(live_session, model_id, "how many doors are in this building?")
    subject_id = _subject_id(slate, "IfcDoor")
    if subject_id is None:
        pytest.skip(f"model {model_id} contains no IfcDoor")
    result = _run(
        live_session,
        model_id,
        slate,
        AnswerPart(
            part_id="p1",
            request_text="doors",
            operation=OutputOperation.COUNT,
            subject_candidate_id=subject_id,
        ),
    )
    assert result.status is ResultStatus.EXACT
