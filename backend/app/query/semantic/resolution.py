"""Pre-planner semantic resolution (Task 16 §4).

Before LLM call 1, search the versioned IFC ontology and the active model's
observed vocabulary with the user's question (plus bounded history/selection
context) and return threshold-free top-k candidates. The result is ADVISORY:

- it does not automatically accept a class;
- it does not block classes absent from any list;
- it does not assert that the top-1 candidate is relevant;
- it gives the planner a bounded view of how IFC and the active model may
  represent the concept, emphasizing content + exact presence/count +
  provenance rather than raw similarity scores.

Similarity/rank is retained internally (trace/eval only). If the embedding
service is unavailable the resolution degrades truthfully to the exact schema
catalog and normalized name matching so SQL stays usable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.config.settings import Settings, get_settings
from app.query.rag.errors import EmbeddingServiceUnavailableError
from app.query.semantic.ontology.loader import OntologyResourceError, get_ontology_index
from app.query.semantic.vocabulary.cache import get_model_vocabulary
from app.query.semantic.vocabulary.profiles import (
    ClassProfile,
    ModelVocabulary,
    ObservedFactProfile,
)
from app.shared.errors import DegradedCapabilityError

# ---------------------------------------------------------------------------
# Result shapes
# ---------------------------------------------------------------------------


@dataclass
class OntologyCandidate:
    ifc_class: str
    schema: str
    present_in_model: bool
    exact_model_count: int
    abstract: bool
    predefined_types: list[str]
    profile_excerpt: str
    similarity: float  # internal only


@dataclass
class ModelClassCandidate:
    ifc_class: str
    kind: str
    exact_model_count: int
    present_in_ontology: bool
    profile_excerpt: str
    similarity: float  # internal only


@dataclass
class ModelFactCandidate:
    ifc_class: str
    fact_kind: str
    source: str
    set_name: str | None
    field_name: str | None
    observed_value: str
    occurrence_count: int
    queryable: bool
    profile_excerpt: str
    similarity: float  # internal only
    # The safe typed reference for automatic structured verification (Task 16 §6).
    queryable_ref: Any = None


@dataclass
class SemanticResolution:
    question: str
    source_model_id: int | None
    degraded: bool = False
    degraded_reason: str | None = None
    ontology_candidates: list[OntologyCandidate] = field(default_factory=list)
    model_class_candidates: list[ModelClassCandidate] = field(default_factory=list)
    model_fact_candidates: list[ModelFactCandidate] = field(default_factory=list)

    def to_planner_context(self, max_chars: int = 400) -> dict:
        """Bounded, provenance-first view for the planner. Emphasizes content,
        exact presence/count, and provenance — NOT similarity scores."""
        return {
            "degraded": self.degraded,
            "note": (
                "Advisory candidates from IFC ontology + this model's observed vocabulary. "
                "They are suggestions, not facts: verify with probes and judge relevance. "
                "Absence of a class here does not mean it cannot be considered."
            ),
            "ontology_candidates": [
                {
                    "ifc_class": c.ifc_class,
                    "schema": c.schema,
                    "present_in_model": c.present_in_model,
                    "exact_model_count": c.exact_model_count,
                    "abstract": c.abstract,
                    # Schema-level ONLY — what this class can carry in IFC, NOT what this
                    # model actually populates. Never filter on these without a model fact.
                    "schema_possible_predefined_types": c.predefined_types[:8],
                    "profile_excerpt": c.profile_excerpt[:max_chars],
                }
                for c in self.ontology_candidates
            ],
            "model_class_candidates": [
                {
                    "ifc_class": c.ifc_class,
                    "kind": c.kind,
                    "exact_model_count": c.exact_model_count,
                    "profile_excerpt": c.profile_excerpt[:max_chars],
                }
                for c in self.model_class_candidates
            ],
            "model_fact_candidates": [
                {
                    "ifc_class": c.ifc_class,
                    "fact_kind": c.fact_kind,
                    "source": c.source,
                    "set_name": c.set_name,
                    "field_name": c.field_name,
                    "observed_value": c.observed_value,
                    "occurrence_count": c.occurrence_count,
                    "queryable": c.queryable,
                }
                for c in self.model_fact_candidates
            ],
        }

    def trace_summary(self) -> dict:
        return {
            "degraded": self.degraded,
            "ontology_top": [
                (c.ifc_class, round(c.similarity, 3)) for c in self.ontology_candidates[:5]
            ],
            "model_fact_top": [
                (c.ifc_class, c.fact_kind, c.observed_value, round(c.similarity, 3))
                for c in self.model_fact_candidates[:5]
            ],
        }


# ---------------------------------------------------------------------------
# Model semantic index (embedded vocabulary), cached per model
# ---------------------------------------------------------------------------


@dataclass
class _IndexedItem:
    kind: str  # "class" | "fact"
    ref: Any


@dataclass
class ModelSemanticIndex:
    source_model_id: int
    embedding_model: str
    items: list[_IndexedItem]
    vectors: Any  # numpy.ndarray (N, dim)


_INDEX_CACHE: dict[tuple, ModelSemanticIndex] = {}


def clear_semantic_index_cache() -> None:
    _INDEX_CACHE.clear()


def _build_model_index(vocab: ModelVocabulary, embedding_service: Any) -> ModelSemanticIndex:
    import numpy as np

    from app.query.rag.embedding_service import EMBEDDING_MODEL_NAME

    items: list[_IndexedItem] = []
    texts: list[str] = []
    for c in vocab.classes:
        items.append(_IndexedItem(kind="class", ref=c))
        texts.append(c.profile_text())
    for f in vocab.facts:
        items.append(_IndexedItem(kind="fact", ref=f))
        texts.append(f.profile_text())
    vectors = np.asarray(embedding_service.embed_documents(texts), dtype=np.float32)
    return ModelSemanticIndex(
        source_model_id=vocab.source_model_id,
        embedding_model=EMBEDDING_MODEL_NAME,
        items=items,
        vectors=vectors,
    )


def get_model_semantic_index(
    session: Session, source_model_id: int, embedding_service: Any, settings: Settings
) -> ModelSemanticIndex:
    from app.query.rag.embedding_service import EMBEDDING_MODEL_NAME

    vocab = get_model_vocabulary(session, source_model_id, settings)
    key = (
        source_model_id,
        vocab.file_fingerprint,
        vocab.extraction_version,
        vocab.profile_builder_version,
        EMBEDDING_MODEL_NAME,
    )
    cached = _INDEX_CACHE.get(key)
    if cached is not None:
        return cached
    index = _build_model_index(vocab, embedding_service)
    _INDEX_CACHE[key] = index
    return index


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------


def _cosine_topk(matrix: Any, query_vec: Any, k: int) -> list[tuple[int, float]]:
    """Return up to k (row_index, cosine) pairs, highest first. Vectors are
    L2-normalized so cosine == dot product."""
    import numpy as np

    if matrix is None or getattr(matrix, "shape", (0,))[0] == 0:
        return []
    scores = matrix @ np.asarray(query_vec, dtype=matrix.dtype)
    k = min(k, scores.shape[0])
    if k <= 0:
        return []
    top = np.argpartition(-scores, k - 1)[:k]
    top = top[np.argsort(-scores[top])]
    return [(int(i), float(scores[i])) for i in top]


def _build_query_text(
    question: str, history: list[dict] | None, selection: list[dict] | None
) -> str:
    parts = [question]
    if selection:
        classes = [s.get("ifc_class") for s in selection if s.get("ifc_class")]
        if classes:
            parts.append("selected: " + ", ".join(classes[:5]))
    if history:
        for turn in reversed(history):
            if turn.get("role") == "user" and turn.get("content"):
                parts.append(turn["content"])
                break
    return " ".join(p for p in parts if p)[:2000]


def resolve(
    session: Session,
    question: str,
    source_model_id: int | None,
    *,
    embedding_service_getter: Callable[[], Any],
    settings: Settings | None = None,
    history: list[dict] | None = None,
    selection: list[dict] | None = None,
) -> SemanticResolution:
    """Threshold-free pre-planner semantic resolution (Task 16 §4)."""
    settings = settings or get_settings()
    result = SemanticResolution(question=question, source_model_id=source_model_id)
    if source_model_id is None:
        return result  # catalog scope has no active-model vocabulary to resolve

    vocab = get_model_vocabulary(session, source_model_id, settings)
    present = vocab.present_classes()

    try:
        service = embedding_service_getter()
        query_vec = service.embed_query(_build_query_text(question, history, selection))
    except (EmbeddingServiceUnavailableError, DegradedCapabilityError) as exc:
        result.degraded = True
        result.degraded_reason = f"semantic embedding unavailable: {exc}"
        _degraded_fallback(result, vocab)
        return result

    # --- ontology candidates (committed index) ---
    try:
        onto_index = get_ontology_index(vocab.ifc_schema or "IFC2X3")
        for i, sim in _cosine_topk(
            onto_index.vectors, query_vec, settings.semantic_resolution_top_k
        ):
            e = onto_index.entities[i]
            result.ontology_candidates.append(
                OntologyCandidate(
                    ifc_class=e.ifc_class,
                    schema=e.schema_name,
                    present_in_model=e.ifc_class in present,
                    exact_model_count=vocab.class_count(e.ifc_class),
                    abstract=e.abstract,
                    predefined_types=e.predefined_types,
                    profile_excerpt=e.short_definition,
                    similarity=sim,
                )
            )
    except OntologyResourceError as exc:
        # Unbundled/absent ontology → degrade truthfully to model vocabulary only.
        result.degraded_reason = f"ontology unavailable: {exc}"

    # --- model vocabulary candidates ---
    try:
        model_index = get_model_semantic_index(session, source_model_id, service, settings)
    except (EmbeddingServiceUnavailableError, DegradedCapabilityError) as exc:
        result.degraded = True
        result.degraded_reason = f"model vocabulary embedding unavailable: {exc}"
        _degraded_fallback(result, vocab)
        return result

    class_k = settings.semantic_resolution_model_top_k
    fact_k = settings.semantic_resolution_model_top_k
    class_hits = 0
    fact_hits = 0
    seen_facts: set[tuple] = set()
    # Draw a wider pool than we surface: coverage facts (field-availability, not
    # concept identity) and duplicate values are filtered out, so the surfaced
    # candidates stay concept-focused. Coverage facts remain in the index for
    # dedicated coverage/vocabulary probes (Task 16 §5, §6).
    pool = _cosine_topk(model_index.vectors, query_vec, (class_k + fact_k) * 4)
    for i, sim in pool:
        item = model_index.items[i]
        if item.kind == "class" and class_hits < class_k:
            c: ClassProfile = item.ref
            result.model_class_candidates.append(
                ModelClassCandidate(
                    ifc_class=c.ifc_class,
                    kind=c.kind,
                    exact_model_count=c.instance_count,
                    present_in_ontology=c.present_in_ontology,
                    profile_excerpt=c.excerpt(settings.vocab_max_profile_excerpt_chars),
                    similarity=sim,
                )
            )
            class_hits += 1
        elif item.kind == "fact" and fact_hits < fact_k:
            f: ObservedFactProfile = item.ref
            if f.fact_kind == "property_coverage":
                continue
            dedupe_key = (f.ifc_class, f.fact_kind, f.observed_value)
            if dedupe_key in seen_facts:
                continue
            seen_facts.add(dedupe_key)
            result.model_fact_candidates.append(
                ModelFactCandidate(
                    ifc_class=f.ifc_class,
                    fact_kind=f.fact_kind,
                    source=f.source,
                    set_name=f.set_name,
                    field_name=f.field_name,
                    observed_value=f.observed_value,
                    occurrence_count=f.occurrence_count,
                    queryable=f.queryable is not None,
                    profile_excerpt=f.excerpt(settings.vocab_max_profile_excerpt_chars),
                    similarity=sim,
                    queryable_ref=f.queryable,
                )
            )
            fact_hits += 1
        if class_hits >= class_k and fact_hits >= fact_k:
            break
    return result


def _degraded_fallback(result: SemanticResolution, vocab: ModelVocabulary) -> None:
    """When embedding is unavailable, surface the exact schema catalog + a
    normalized name match so the planner still sees present classes and SQL is
    usable (Task 16 §4, §14 preserve SQL-only usability)."""
    q = result.question.lower()
    for c in vocab.classes:
        label = c.ifc_class.lower()
        stem = label[3:] if label.startswith("ifc") else label
        matched = stem and stem in q
        result.model_class_candidates.append(
            ModelClassCandidate(
                ifc_class=c.ifc_class,
                kind=c.kind,
                exact_model_count=c.instance_count,
                present_in_ontology=c.present_in_ontology,
                profile_excerpt=c.excerpt(400),
                similarity=1.0 if matched else 0.0,
            )
        )
    # Deterministic: exact-name matches first, then by count.
    result.model_class_candidates.sort(key=lambda c: (-c.similarity, -c.exact_model_count))
    result.model_class_candidates = result.model_class_candidates[:15]
