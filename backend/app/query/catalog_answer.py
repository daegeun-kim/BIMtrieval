"""Model-catalog questions (Task 24 §11.1).

Catalog scope has no active model, so there is nothing to bind a slate against.
It stays a model-catalog operation but uses the SAME final-answer contract as
every other question, so response style is uniform (§11.1).

§11.1 also requires: "Include all safe recorded display metadata needed to
identify a model, including the existing filename when a display name is
absent. Do not fabricate missing catalog metadata."

That first clause fixes a specific recorded defect — a catalog answer described
a model as having "no display name or version information" while its filename
was recorded all along. The filename is genuine, safe, recorded metadata and is
exactly what a user needs to tell two models apart, so it is included as a
fallback identity rather than withheld.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.schemas.request import SessionQueryRequest
from app.api.schemas.response import EvidenceSummary, ModelCandidate, QueryResponseEnvelope
from app.shared.types import AnswerBasis, QueryRoute, QueryScope, ResponseStatus
from app.viewer.actions import build_await_confirmation_actions

__all__ = ["answer_catalog_question", "is_catalog_question", "load_catalog_models"]

#: Bounded catalog read. A catalog is a short list by nature.
_MAX_MODELS = 50


def is_catalog_question(active_source_model_id: int | None) -> bool:
    """Catalog scope is decided by the absence of an active model, not by wording."""
    return active_source_model_id is None


def load_catalog_models(session: Session) -> list[dict[str, Any]]:
    """Safe, recorded display metadata for every catalogued model.

    `file_name` is read so a model with no display name can still be identified.
    Nothing here is derived or invented: every field is a stored column, and a
    missing one stays missing.
    """
    rows = session.execute(
        text(
            "SELECT id, display_name, version_label, is_current, status, file_name, ifc_schema "
            "FROM ifc_source_models ORDER BY id LIMIT :cap"
        ),
        {"cap": _MAX_MODELS},
    ).mappings()
    return [dict(row) for row in rows]


def _identity(row: dict[str, Any]) -> str:
    """The best available human identity for one model, never fabricated."""
    for key in ("display_name", "file_name"):
        value = row.get(key)
        if value:
            return str(value)
    return f"model {row['id']}"


def _describe(row: dict[str, Any]) -> str:
    parts = [f"{_identity(row)} (id {row['id']})"]
    if row.get("version_label"):
        parts.append(f"version {row['version_label']}")
    if row.get("is_current"):
        parts.append("current")
    if row.get("status"):
        parts.append(str(row["status"]))
    if row.get("ifc_schema"):
        parts.append(str(row["ifc_schema"]))
    return " — ".join(parts)


def answer_catalog_question(
    session: Session,
    request: SessionQueryRequest,
    request_id: str,
    client: Any,
) -> QueryResponseEnvelope:
    """Answer a catalog question deterministically.

    No model call is made: the catalog is a short list of recorded facts, and
    generating prose for it would add a provider round-trip and a fabrication
    risk for no benefit. The response still uses the standard envelope, so the
    frontend sees one shape (§11.1).
    """
    rows = load_catalog_models(session)
    if not rows:
        answer = "There are no models in the catalog yet."
    else:
        listed = "\n".join(f"- {_describe(row)}" for row in rows)
        plural = "model" if len(rows) == 1 else "models"
        verb = "is" if len(rows) == 1 else "are"
        answer = (
            f"There {verb} {len(rows)} {plural} available:\n{listed}\n\n"
            "Tell me which one to load, and I'll answer questions about it."
        )

    candidates = [
        ModelCandidate(
            source_model_id=row["id"],
            display_name=row.get("display_name") or row.get("file_name"),
            version_label=row.get("version_label"),
            is_current=row.get("is_current"),
        )
        for row in rows
    ]

    return QueryResponseEnvelope(
        request_id=request_id,
        session_id=request.session_id,
        status=ResponseStatus.SUCCESS,
        scope=QueryScope.MODEL_CATALOG,
        route=QueryRoute.SQL,
        answer_basis=AnswerBasis.EXACT_SQL,
        answer=answer,
        active_source_model_id=None,
        model_candidates=candidates,
        viewer_actions=build_await_confirmation_actions(),
        evidence_summary=EvidenceSummary(
            basis=AnswerBasis.EXACT_SQL, sql_match_count=len(candidates)
        ),
        warnings=[],
    )
