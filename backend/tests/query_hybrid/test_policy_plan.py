"""Query-only retrieval-policy schema + validation + modality isolation
(Task 17 §2, §11, §13 dataflow isolation). No DB / no OpenAI."""

from __future__ import annotations

import json

from app.llm.prompts import POLICY_PLANNER_PROMPT_VERSION, policy_planner_prompt
from app.llm.schemas import Facet, RetrievalPolicy, RetrievalPolicyPlan, RoleHint
from app.llm.validation import frozen_policy, policy_hash, validate_policy_plan
from app.shared.types import QueryRoute, QueryScope


def _facet(fid, sql=False, rag=False, graph=False):
    return Facet(
        facet_id=fid,
        question="q?",
        role_hint=RoleHint.DIRECT,
        semantic_query="concept text",
        needs_exact_structured=sql,
        needs_entity_rag=rag,
        needs_graph=graph,
    )


def _plan(facets, policy):
    return RetrievalPolicyPlan(
        scope=QueryScope.ACTIVE_MODEL,
        route=QueryRoute.HYBRID,
        source_model_id=1,
        facets=facets,
        retrieval_policy=policy,
    )


def test_valid_active_plan():
    plan = _plan([_facet("a", sql=True, rag=True)], RetrievalPolicy(sql=True, rag_entity=True))
    assert validate_policy_plan(plan) == []


def test_frozen_policy_is_union_of_facet_needs():
    plan = _plan(
        [_facet("a", sql=True), _facet("b", rag=True), _facet("c", graph=True)],
        RetrievalPolicy(sql=True, rag_entity=True, graph=True),
    )
    fp = frozen_policy(plan)
    assert (fp.sql, fp.rag_entity, fp.rag_relationship, fp.graph) == (True, True, False, True)


def test_declared_policy_must_match_union():
    # facet needs only SQL, but the declared policy claims graph too → error
    plan = _plan([_facet("a", sql=True)], RetrievalPolicy(sql=True, graph=True))
    assert any("union of facet needs" in e for e in validate_policy_plan(plan))


def test_duplicate_facet_ids_rejected():
    plan = _plan([_facet("a", sql=True), _facet("a", sql=True)], RetrievalPolicy(sql=True))
    assert any("unique" in e for e in validate_policy_plan(plan))


def test_catalog_route_requires_catalog_plan():
    plan = RetrievalPolicyPlan(scope=QueryScope.MODEL_CATALOG, route=QueryRoute.SQL)
    assert any("catalog route requires catalog_plan" in e for e in validate_policy_plan(plan))


def test_policy_hash_stable_and_distinct():
    a = policy_hash(RetrievalPolicy(sql=True))
    b = policy_hash(RetrievalPolicy(sql=True))
    c = policy_hash(RetrievalPolicy(sql=True, rag_entity=True))
    assert a == b and a != c


def test_policy_schema_is_openai_strict_sized():
    s = RetrievalPolicyPlan.model_json_schema()
    assert len(json.dumps(s)) < 15000  # within strict structured-output limits


def test_prompt_is_v002_and_query_only():
    assert POLICY_PLANNER_PROMPT_VERSION == "policy_planner_v002"
    text = policy_planner_prompt().lower()
    assert "from the user's query alone" in text or "from the query" in text
    assert "facet" in text


def test_prompt_requires_typed_conditions_and_stays_query_only():
    """Task 23 §1: the planner must be told to emit conditions as typed data and
    must still be forbidden from seeing/emitting model-specific detail."""
    text = policy_planner_prompt().lower()
    assert "conditions" in text
    # The core instruction: a condition living only in prose is lost.
    assert "only inside" in text or "only in prose" in text
    # Query-only isolation is unchanged from v001.
    assert "no observed values" in text
    assert "do not emit final ifc classes" in text
    # It must not resolve floor language itself.
    assert "do not resolve values yourself" in text
