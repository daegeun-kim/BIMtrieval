"""Route-dispatch scaffold (spec_v002 Section 7.4).

Maps a validated QueryPlan.route to the query-path package that should
execute it. Actual execution lives in query/{catalog,sql,graph,rag,hybrid}
(v003/v004/v005 scope) — this module only fixes the dispatch contract.
"""

from __future__ import annotations

from app.shared.types import QueryRoute

_ROUTE_TO_PACKAGE: dict[QueryRoute, str] = {
    QueryRoute.SQL: "query.sql",
    QueryRoute.RAG: "query.rag",
    QueryRoute.GRAPH: "query.graph",
    QueryRoute.HYBRID: "query.hybrid",
    QueryRoute.EXPLAIN_GENERAL: "llm.answerer",
    QueryRoute.CLARIFY: "llm.answerer",
}


def resolve_route_package(route: QueryRoute) -> str:
    """Return the dotted package name responsible for executing `route`."""
    return _ROUTE_TO_PACKAGE[route]


def dispatch(route: QueryRoute, *args: object, **kwargs: object) -> object:
    raise NotImplementedError(
        f"Route execution for {route.value!r} is implemented in the v003/v004/v005 "
        "query paths, not in the Task 04 architecture scaffold."
    )
