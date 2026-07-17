"""Task 17 §12-§13 regression through the real service/DB with a scripted LLM.

The policy plan (call 1) and the group answerer (call 2) are scripted; semantic
resolution, group construction, verification, allocation, and complete viewer
hydration run for real against the live model with real BGE-M3 embeddings. Live
OpenAI behavior is validated separately (§13 bounded live validation).
"""

from __future__ import annotations

import pytest

from app.api.schemas.request import SessionQueryRequest
from app.config.settings import get_settings
from app.llm.client import AnswerOutput, AnswerResult, PolicyResult, TokenUsage
from app.llm.schemas import Facet, RetrievalPolicy, RetrievalPolicyPlan, RoleHint
from app.query.rag.embedding_service import get_embedding_service
from app.query.semantic.resolution import clear_semantic_index_cache, resolve_facets
from app.query.service import QueryService
from app.shared.types import AnswerBasis, QueryRoute, QueryScope

SID = 1


@pytest.fixture(scope="module", autouse=True)
def _require_embeddings():
    try:
        get_embedding_service().ensure_loaded()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"embedding service not available: {exc}")
    clear_semantic_index_cache()


class _Log:
    def __init__(self):
        self.calls = []


class FakeClient:
    def __init__(self, policy, answer):
        self._p = policy
        self._a = answer
        self.log = _Log()

    def plan_retrieval_policy(self, ctx):
        self.log.calls.append({"role": "policy", "total_tokens": 1})
        return PolicyResult(plan=self._p, usage=TokenUsage(model="fake", total_tokens=1))

    def generate_group_answer(self, payload):
        out = self._a(payload) if callable(self._a) else self._a
        self.log.calls.append({"role": "group_answerer", "total_tokens": 1})
        return AnswerResult(output=out, usage=TokenUsage(model="fake", total_tokens=1))


def _facet(fid, sq, sql=True, rag=False):
    return Facet(
        facet_id=fid,
        question="q?",
        role_hint=RoleHint.DIRECT,
        semantic_query=sq,
        needs_exact_structured=sql,
        needs_entity_rag=rag,
    )


def _run(policy, answer, question, session="t17"):
    svc = QueryService(llm_client=FakeClient(policy, answer))
    req = SessionQueryRequest(session_id=session, question=question, active_source_model_id=SID)
    return svc.handle_query(req)


# --- §12 circulation --------------------------------------------------------


def test_circulation_stairs_primary_no_1723():
    policy = RetrievalPolicyPlan(
        scope=QueryScope.ACTIVE_MODEL,
        route=QueryRoute.HYBRID,
        source_model_id=SID,
        analysis_intent="circulation",
        facets=[
            _facet("vert", "vertical movement stairs between levels", sql=True, rag=True),
            _facet("horiz", "corridors horizontal circulation spaces", sql=True, rag=True),
        ],
        retrieval_policy=RetrievalPolicy(sql=True, rag_entity=True),
    )

    def answer(payload):
        stair = [g for g in payload["evidence_groups"] if g["label"].startswith("IfcStair objects")]
        generic = [
            g["group_id"]
            for g in payload["evidence_groups"]
            if g["label"].split()[0] in ("IfcWindow", "IfcWall", "IfcSlab", "IfcColumn")
        ]
        gid = stair[0]["group_id"] if stair else None
        return AnswerOutput(
            answer="Vertical circulation is represented by nine stairs; horizontal circulation "
            "cannot be assessed because explicit spaces are absent.",
            primary_group_ids=[gid] if gid else [],
            rejected_group_ids=generic,
            viewer_primary_group_ids=[gid] if gid else [],
        )

    env = _run(policy, answer, "Describe me the circulation of this building.", "circ")
    assert env.result_summary.exact_total == 9  # not 1723
    assert env.result_summary.viewer_match_count == 9  # all nine stair identities
    assert env.result_summary.truncated is False
    assert env.result_summary.class_counts == {"IfcStair": 9}
    assert env.answer_basis == AnswerBasis.EXACT_SQL


# --- §12 exact door count ---------------------------------------------------


def test_doors_sql_only_all_identities():
    policy = RetrievalPolicyPlan(
        scope=QueryScope.ACTIVE_MODEL,
        route=QueryRoute.HYBRID,
        source_model_id=SID,
        facets=[_facet("doors", "doors", sql=True, rag=False)],
        retrieval_policy=RetrievalPolicy(sql=True),
    )

    def answer(payload):
        door = [g for g in payload["evidence_groups"] if g["label"] == "IfcDoor objects"]
        gid = door[0]["group_id"]
        return AnswerOutput(
            answer="There are 205 doors.", primary_group_ids=[gid], viewer_primary_group_ids=[gid]
        )

    env = _run(policy, answer, "How many doors are in this building?", "doors")
    assert env.result_summary.exact_total == 205
    assert env.result_summary.viewer_match_count == 205  # all 205 identities, no cap
    assert env.answer_basis == AnswerBasis.EXACT_SQL


# --- §13 modality invariance under varied resolver fixtures -----------------


def test_retrieval_modes_independent_of_resolution(live_session):
    """The executed retrieval modes come from the frozen policy, not from what
    resolution returns. SQL-only policy never runs RAG regardless of candidates."""
    from app.query.hybrid.groups.builder import build_groups

    facets = [_facet("f", "vertical movement stairs", sql=True, rag=False)]
    frs = resolve_facets(live_session, facets, SID, embedding_service_getter=get_embedding_service)
    # SQL-only policy: no group may carry rag provenance even though candidates exist.
    groups = build_groups(
        live_session,
        frs,
        RetrievalPolicy(sql=True),
        SID,
        settings=get_settings(),
        embedding_service_getter=get_embedding_service,
    )
    assert all("rag_entity" not in g.source_kinds for g in groups)
    # An empty resolution must also not introduce RAG under a SQL-only policy.
    empty = [type(frs[0])(facet_id="f", role_hint="direct", semantic_query="x")]
    groups2 = build_groups(
        live_session,
        empty,
        RetrievalPolicy(sql=True),
        SID,
        settings=get_settings(),
        embedding_service_getter=get_embedding_service,
    )
    assert all("rag_entity" not in g.source_kinds for g in groups2)


# --- §9 complete viewer identities (real, above nothing engaging the cap) ----


def test_complete_viewer_hydration_real_class(live_session):
    from app.query.hybrid.groups.execute import all_identities
    from app.query.hybrid.groups.schemas import GroupPredicate, PredicateKind

    pred = GroupPredicate(kind=PredicateKind.ENTITY_CLASS.value, ifc_classes=("IfcCovering",))
    ident = all_identities(live_session, pred, SID)
    assert ident.exact_total == 1214
    assert len(ident.global_ids) == 1214  # every identity returned, no 2,000 cap


def test_select_viewer_identities_unbounded(live_session):
    from app.query.sql.entities import select_viewer_identities

    unbounded = select_viewer_identities(live_session, SID, ["IfcCovering"], None, None)
    assert len(unbounded.rows) == unbounded.exact_total == 1214
    assert unbounded.truncated is False
    capped = select_viewer_identities(live_session, SID, ["IfcCovering"], None, 100)
    assert len(capped.rows) == 100 and capped.truncated is True  # limit still works when set


# --- policy context isolation (structural modality guarantee) ---------------


def test_policy_context_has_no_active_model_leakage(live_session):
    import json

    from app.llm.context import build_policy_context
    from app.query.session import SessionState

    req = SessionQueryRequest(
        session_id="iso", question="describe circulation", active_source_model_id=SID
    )
    ctx = build_policy_context(live_session, req, SessionState(session_id="iso"), get_settings())
    blob = json.dumps(ctx).lower()
    for leak in ("ifcstair", "ifcdoor", "property_set", "quantity_set", "predefined", "ontology"):
        assert leak not in blob
