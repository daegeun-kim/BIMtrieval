"""Grounded answer generation — OpenAI call 2 (spec_v005 §11).

The answer model receives ONLY the bounded evidence payload built from an
`EvidencePackage` (compact entity summaries, exact totals, facts, conflicts,
missing-coverage) plus, for `explain_general`, no model evidence at all. It
returns structured `AnswerOutput` carrying the user-facing text and the
internal `used_general_knowledge` flag the system records (spec_v005 §11, §16).

The backend, not the model, is authoritative for `answer_basis` — this module
never recomputes numbers or invents model facts; it only turns the already-
retrieved evidence into prose under the answerer prompt's constraints.
"""

from __future__ import annotations

from app.llm.client import AnswerResult, OpenAIQueryClient
from app.query.hybrid.evidence import build_answer_payload
from app.query.hybrid.schemas import EvidencePackage


def answer_from_evidence(client: OpenAIQueryClient, package: EvidencePackage) -> AnswerResult:
    """Grounded answer from a bounded, retrieved evidence package."""
    payload = build_answer_payload(package)
    return client.generate_answer(payload)


def answer_general(client: OpenAIQueryClient, question: str) -> AnswerResult:
    """Explain-general route: no model retrieval, general BIM knowledge only
    (spec_v005 §7). The empty evidence makes the general-knowledge basis explicit."""
    payload = {
        "question": question,
        "route": "explain_general",
        "note": (
            "No data was retrieved from any specific model. Answer from general BIM/IFC "
            "knowledge only and do not state facts about any particular model."
        ),
        "primary_entities": [],
        "context_entities": [],
        "relationships": [],
        "sql_facts": None,
        "exact_totals": {},
    }
    return client.generate_answer(payload)
