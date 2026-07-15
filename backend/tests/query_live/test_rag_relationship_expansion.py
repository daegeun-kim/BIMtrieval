"""Direct relationship-endpoint expansion, unresolved endpoints, and
primary/context classification (spec_v004 §10, §11), live."""

from __future__ import annotations

from app.query.rag.hydration import hydrate_rag_result
from app.query.rag.relationship_expansion import expand_relationship_endpoints
from app.query.rag.schemas import RagCandidate, RagSearchResult

from .conftest import SOURCE_MODEL_ID

# Verified live: door 627 -IfcRelDefinesByProperties(431)-> IfcPropertySet 628.
PROPERTY_DEFINITION_RELATIONSHIP_ID = 431
DOOR_ENTITY_ID = 627
PROPERTY_SET_ENTITY_ID = 628


def test_expand_endpoints_resolves_known_relationship(live_session):
    expansion = expand_relationship_endpoints(
        live_session, SOURCE_MODEL_ID, PROPERTY_DEFINITION_RELATIONSHIP_ID
    )
    resolved_ids = {r.id for r in expansion.resolved_endpoints}
    assert resolved_ids == {DOOR_ENTITY_ID, PROPERTY_SET_ENTITY_ID}
    assert expansion.unresolved_endpoints == []
    assert expansion.total_member_count == 2


def _rel_candidate(relationship_id: int) -> RagCandidate:
    return RagCandidate(
        rag_document_id=relationship_id,
        source_kind="relationship",
        document_type="relationship_description",
        canonical_id=relationship_id,
        cosine_distance=0.2,
        similarity=0.8,
        per_kind_rank=1,
        embedding_model="BAAI/bge-m3",
        embedding_dim=1024,
        text_template_version="v001",
        document_text_excerpt="...",
        passed_threshold=True,
    )


def test_hydrate_rag_result_marks_relationship_primary_and_endpoints_context(live_session):
    result = RagSearchResult(
        source_model_id=SOURCE_MODEL_ID,
        semantic_query="property definitions for this door",
        threshold_profile="default_v001",
        threshold_value=0.5,
        relationship_candidates=[_rel_candidate(PROPERTY_DEFINITION_RELATIONSHIP_ID)],
    )
    primary, context, relationships_out, viewer_actions, warnings = hydrate_rag_result(
        live_session, SOURCE_MODEL_ID, result, expand_endpoints=True
    )
    assert primary == []  # no entity candidates were accepted directly
    assert {c.entity_id for c in context} == {DOOR_ENTITY_ID, PROPERTY_SET_ENTITY_ID}
    assert [r.relationship_id for r in relationships_out] == [PROPERTY_DEFINITION_RELATIONSHIP_ID]
    assert warnings == []
    assert viewer_actions.context_global_ids


def test_expansion_disabled_yields_no_context_entities(live_session):
    result = RagSearchResult(
        source_model_id=SOURCE_MODEL_ID,
        semantic_query="q",
        threshold_profile="default_v001",
        threshold_value=0.5,
        relationship_candidates=[_rel_candidate(PROPERTY_DEFINITION_RELATIONSHIP_ID)],
    )
    _primary, context, relationships_out, _va, _warnings = hydrate_rag_result(
        live_session, SOURCE_MODEL_ID, result, expand_endpoints=False
    )
    assert context == []
    assert len(relationships_out) == 1


def test_expansion_on_containment_hub_stays_bounded(live_session):
    """The single IfcRelContainedInSpatialStructure relationship has 3505
    RelatedElements — expansion must stay within MAX_EXPANDED_ENDPOINTS and
    warn rather than hydrate everything (spec_v002 §14: bounded evidence)."""
    expansion = expand_relationship_endpoints(live_session, SOURCE_MODEL_ID, 245)
    assert expansion.total_member_count > 200
    assert len(expansion.resolved_endpoints) <= 200
    assert expansion.warnings
