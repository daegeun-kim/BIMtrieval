"""Shared enums referenced by planner schemas, API schemas, and the query service.

Governed by specs/spec_v002_query_architecture.md. Values are fixed vocabularies —
callers (including the LLM planner) must not introduce values outside these sets.
"""

from __future__ import annotations

from enum import Enum


class QueryScope(str, Enum):
    """spec_v002 Section 4."""

    MODEL_CATALOG = "model_catalog"
    ACTIVE_MODEL = "active_model"


class QueryRoute(str, Enum):
    """spec_v002 Section 7.4."""

    SQL = "sql"
    RAG = "rag"
    GRAPH = "graph"
    HYBRID = "hybrid"
    EXPLAIN_GENERAL = "explain_general"
    CLARIFY = "clarify"


class AnswerBasis(str, Enum):
    """spec_v002 Section 13."""

    EXACT_SQL = "exact_sql"
    SEMANTIC_RETRIEVAL = "semantic_retrieval"
    GRAPH_TRAVERSAL = "graph_traversal"
    HYBRID_EVIDENCE = "hybrid_evidence"
    GENERAL_KNOWLEDGE = "general_knowledge"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class MetadataProvenance(str, Enum):
    """spec_v002 Section 5.1 — catalog metadata provenance."""

    IFC_EXTRACTED = "ifc_extracted"
    MANUAL = "manual"
    DERIVED_EXACT = "derived_exact"


class CombinationMode(str, Enum):
    """spec_v002 Section 8/12 — hybrid SQL/RAG combination semantics."""

    INTERSECTION = "intersection"
    UNION = "union"


class ModelStatus(str, Enum):
    """spec_v002 Section 5 — model availability/status."""

    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    PROCESSING = "processing"


class ResponseStatus(str, Enum):
    """spec_v002 Section 16.2 — top-level /api/query response status."""

    SUCCESS = "success"
    ERROR = "error"
