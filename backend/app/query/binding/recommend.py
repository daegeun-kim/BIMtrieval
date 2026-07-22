"""High-recall advisory recommendations over the complete manifest (task25 §3.1).

This replaces the Task 24 candidate slate, and the difference is the point.

The old slate was the binder's ALLOWED UNIVERSE: at most eight subjects, chosen
by lexical rules, with embeddings able only to reorder what exact matching had
already admitted. A concept the rules missed was unreachable, and a compound
question could lose a subject to a global cap.

Here the universe is the COMPLETE manifest. Every concept the model contains is
addressable by its stable semantic ID, and this module's job is only to help the
binder find the likely ones — recommendations are advisory, never a gate (§3.1).
Two consequences follow directly:

- semantic similarity may now ADMIT a concept, not merely rank one, because
  admitting a wrong candidate no longer excludes the right one;
- there is no global cap that can drop a subject, condition, or answer part.

Candidate IDs ARE manifest semantic IDs (`cls:IfcWall`,
`prop:Pset_WallCommon.IsExternal`). The old positional scheme (`s1`, `f2`) meant
an ID's meaning depended on ordering — and `_add_logical_floor_subject` really
did renumber every subject whenever floor language appeared. Content-derived IDs
are stable across questions, which makes prompt caching and diagnostics honest.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.config.settings import Settings
from app.query.binding.ledger import ConstraintLedger, LedgerItem
from app.query.binding.lexical import identifier_tokens, normalize_text, singularize
from app.query.binding.schemas import (
    CandidateSlate,
    FieldCandidate,
    MatchTier,
    RelationshipCandidate,
    SpatialCandidate,
    SpatialKind,
    SubjectCandidate,
    ValueCandidate,
)
from app.query.semantic.manifest import (
    KIND_ATTRIBUTE,
    KIND_PROPERTY,
    KIND_QUANTITY,
    KIND_RELATIONSHIP,
    ManifestConcept,
    SemanticManifest,
)
from app.query.semantic.roles import family_closure, is_result_kind, schema_role
from app.query.semantic.spatial import build_storey_model, mentions_floor_concept
from app.query.sql.field_registry import (
    ATTRIBUTE_COLUMN_FIELDS,
    ATTRIBUTE_JSON_FIELDS,
    TYPE_FACT_JSON_FIELDS,
)

__all__ = ["RecommendationInputs", "Recommendation", "build_recommendations"]

#: How many advisory recommendations to surface per material request span.
#: A BOUND ON HELP, not on choice: the binder may select any manifest ID
#: regardless of what appears here, so this number cannot drop a valid concept.
DEFAULT_PER_SPAN = 6

#: Ceiling on the advisory list as a whole, for prompt economy only.
DEFAULT_TOTAL = 40


@dataclass
class RecommendationInputs:
    question: str
    source_model_id: int
    history: list[dict[str, str]] = field(default_factory=list)
    selected_entities: list[dict[str, Any]] = field(default_factory=list)
    previous_scope: Any | None = None


@dataclass(frozen=True)
class Recommendation:
    """One advisory pointer from a request span to a manifest concept."""

    semantic_id: str
    kind: str
    label: str
    reason: str
    #: The ledger item this recommendation was raised for, when it came from one.
    ledger_item_id: str | None = None
    score: float = 0.0

    def to_payload(self) -> dict[str, Any]:
        payload = {
            "id": self.semantic_id,
            "kind": self.kind,
            "label": self.label,
            "why": self.reason,
        }
        if self.ledger_item_id:
            payload["for"] = self.ledger_item_id
        return payload


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def build_recommendations(
    session: Session,
    inputs: RecommendationInputs,
    manifest: SemanticManifest,
    ledger: ConstraintLedger,
    *,
    settings: Settings,
    embedding_service_getter: Callable[[], Any] | None = None,
    per_span: int = DEFAULT_PER_SPAN,
    total: int = DEFAULT_TOTAL,
) -> CandidateSlate:
    """Build the full candidate universe plus a ranked advisory shortlist."""
    slate = CandidateSlate(question=inputs.question, source_model_id=inputs.source_model_id)
    slate.detected_modifier_spans = list(ledger.spans)

    _load_universe(session, inputs, manifest, slate)
    slate.recommendations = _rank(
        inputs,
        manifest,
        ledger,
        slate,
        embedding_service_getter=embedding_service_getter,
        per_span=per_span,
        total=total,
    )
    slate.coverage_notes = _coverage_notes(manifest)
    return slate


# ---------------------------------------------------------------------------
# The complete universe
# ---------------------------------------------------------------------------


def _load_universe(
    session: Session,
    inputs: RecommendationInputs,
    manifest: SemanticManifest,
    slate: CandidateSlate,
) -> None:
    """Every manifest concept becomes an addressable candidate.

    No caps and no relevance filter: §3.1 requires that a valid semantic ID
    outside the shortlist still resolve, so the universe must be complete even
    though only the shortlist is highlighted in the prompt.
    """
    present = manifest.present_classes()

    schema = manifest.ifc_schema or "IFC2X3"
    for concept in manifest.classes():
        ifc_class = concept.ifc_class or ""
        role = schema_role(ifc_class, schema)
        family = family_closure(ifc_class, present, schema)
        slate.subjects.append(
            SubjectCandidate(
                candidate_id=concept.semantic_id,
                label=ifc_class,
                ifc_class=ifc_class,
                schema_role=role.value,
                # A present class the ontology cannot describe still queries as
                # itself, so it must carry a non-empty family or closure drops it.
                family_members=family or (ifc_class,),
                present=True,
                exact_count=concept.total_count or None,
                result_kind=is_result_kind(role),
                match_tier=MatchTier.CONTEXT,
                match_reason="present in the active model",
                specificity=len(identifier_tokens(ifc_class)),
            )
        )

    for concept in manifest.fields():
        candidate = _field_candidate(concept)
        if candidate is not None:
            slate.fields.append(candidate)

    _load_values(manifest, slate)
    _load_spatial(session, inputs, slate)

    for concept in manifest.of_kind(KIND_RELATIONSHIP):
        slate.relationships.append(
            RelationshipCandidate(
                candidate_id=concept.semantic_id,
                ifc_class=concept.ifc_class or "",
                meaning=concept.text,
                endpoint_roles=concept.applies_to,
                available=concept.total_count > 0,
                instance_count=concept.total_count,
            )
        )


def _field_kind_for(concept: ManifestConcept) -> str | None:
    """Map a manifest concept onto a physically addressable SQL field kind.

    Returns None when the concept is real and visible in the manifest but has no
    SQL addressing today (materials and classifications). Those stay selectable
    as manifest concepts — so the binder can cite them and the answer can explain
    the limitation — but they never compile into a filter, because inventing a
    predicate for them would produce a confidently wrong count.
    """
    if concept.kind == KIND_PROPERTY:
        return "property" if concept.field_name and concept.set_name else None
    if concept.kind == KIND_QUANTITY:
        return "quantity" if concept.field_name and concept.set_name else None
    if concept.kind == KIND_ATTRIBUTE:
        name = concept.field_name or ""
        if name in TYPE_FACT_JSON_FIELDS:
            return "type_fact"
        if name in ATTRIBUTE_JSON_FIELDS or name in ATTRIBUTE_COLUMN_FIELDS:
            return "attribute"
    return None


def _field_candidate(concept: ManifestConcept) -> FieldCandidate | None:
    field_kind = _field_kind_for(concept)
    if field_kind is None:
        return None
    applicable = concept.applies_to or ((concept.ifc_class,) if concept.ifc_class else ())
    return FieldCandidate(
        candidate_id=concept.semantic_id,
        field_kind=field_kind,
        set_name=concept.set_name if field_kind in ("property", "quantity") else None,
        field_name=concept.field_name or "",
        data_type=concept.data_type or "text",
        operators=concept.operators,
        applicable_classes=tuple(c for c in applicable if c),
        populated_count=concept.populated_count,
        total_count=concept.total_count,
        sample_values=tuple(v for v, _ in concept.values[:6]),
        match_tier=MatchTier.CONTEXT,
    )


def _load_values(manifest: SemanticManifest, slate: CandidateSlate) -> None:
    """Enumerated values become addressable candidates.

    High-cardinality (`searchable`) fields contribute no value candidates here;
    a value the user names is resolved by authoritative lookup at query time
    instead (§2.2), which is what keeps capability without dumping data.
    """
    for concept in manifest.fields():
        if concept.searchable or not concept.values:
            continue
        for value, count in concept.values:
            slate.values.append(
                ValueCandidate(
                    candidate_id=f"val:{concept.semantic_id}:{value}",
                    field_candidate_id=concept.semantic_id,
                    value=value,
                    occurrence_count=count,
                    ifc_class=concept.ifc_class,
                )
            )


def _load_spatial(session: Session, inputs: RecommendationInputs, slate: CandidateSlate) -> None:
    """Scope selections and spatial conditions, kept typed and distinct.

    Floor bands flow through the general spatial semantics; there is deliberately
    no logical-floor SUBJECT any more (§2.3) — a floor is somewhere to look, or a
    property to group by, never the thing being counted unless storeys are asked
    about explicitly.
    """
    slate.spatial.append(
        SpatialCandidate(
            candidate_id="scope:active_model",
            kind=SpatialKind.ACTIVE_MODEL,
            label="the whole active model",
        )
    )
    if inputs.selected_entities:
        slate.spatial.append(
            SpatialCandidate(
                candidate_id="scope:selection",
                kind=SpatialKind.SELECTION,
                label="the objects currently selected in the viewer",
            )
        )
    if inputs.previous_scope is not None:
        slate.spatial.append(
            SpatialCandidate(
                candidate_id="scope:previous_result",
                kind=SpatialKind.PREVIOUS_RESULT,
                label="the previous result",
            )
        )

    if not mentions_floor_concept(inputs.question):
        return
    try:
        storey_model = build_storey_model(session, inputs.source_model_id)
    except Exception:  # noqa: BLE001 - spatial data is optional, never fatal
        return
    for band in getattr(storey_model, "bands", ()) or ():
        slate.spatial.append(
            SpatialCandidate(
                candidate_id=f"floor:{band.index}",
                kind=SpatialKind.FLOOR_BAND,
                label=f"floor level {band.index + 1} (elevation {band.min_elevation:g})",
                storey_global_ids=tuple(band.global_ids),
                interpretation=band.describe(),
            )
        )


# ---------------------------------------------------------------------------
# Ranking
# ---------------------------------------------------------------------------


def _rank(
    inputs: RecommendationInputs,
    manifest: SemanticManifest,
    ledger: ConstraintLedger,
    slate: CandidateSlate,
    *,
    embedding_service_getter: Callable[[], Any] | None,
    per_span: int,
    total: int,
) -> list[Recommendation]:
    """Rank concepts per MATERIAL LEDGER ITEM, then merge.

    Diversifying per item is what stops one noun consuming a compound question:
    "how many doors and how many fire-rated walls" raises recommendations for
    each item separately, so neither can crowd the other out of the shortlist
    (§3.1).
    """
    out: list[Recommendation] = []
    seen: set[str] = set()

    for item in ledger.required_items():
        matches = _matches_for(item, manifest, embedding_service_getter)
        kept = 0
        for score, concept, reason in matches:
            if kept >= per_span:
                break
            if concept.semantic_id in seen:
                continue
            seen.add(concept.semantic_id)
            out.append(
                Recommendation(
                    semantic_id=concept.semantic_id,
                    kind=concept.kind,
                    label=concept.label,
                    reason=reason,
                    ledger_item_id=item.item_id,
                    score=score,
                )
            )
            kept += 1

    # Exact matches always outrank supplements, and within a tie the more
    # specific concept wins over the more numerous one — the recurring defect
    # shape is a broad class displacing the precise one the user named.
    out.sort(key=lambda r: (-r.score, r.label))
    return out[:total]


def _matches_for(
    item: LedgerItem,
    manifest: SemanticManifest,
    embedding_service_getter: Callable[[], Any] | None,
) -> list[tuple[float, ManifestConcept, str]]:
    tokens = {singularize(t) for t in identifier_tokens(item.text)}
    if not tokens:
        return []

    scored: list[tuple[float, ManifestConcept, str]] = []
    for concept in manifest.concepts.values():
        score, reason = _score(concept, tokens, item)
        if score > 0:
            scored.append((score, concept, reason))

    if embedding_service_getter is not None and len(scored) < 3:
        scored.extend(_semantic_matches(item, manifest, embedding_service_getter, scored))

    scored.sort(key=lambda t: (-t[0], t[1].label))
    return scored


def _score(concept: ManifestConcept, tokens: set[str], item: LedgerItem) -> tuple[float, str]:
    """Lexical scoring over the concept's own identifiers and value vocabulary."""
    concept_tokens = {singularize(t) for t in identifier_tokens(concept.text or concept.label)}
    concept_tokens.discard("ifc")
    if not concept_tokens:
        return 0.0, ""

    overlap = tokens & concept_tokens
    if overlap == concept_tokens and concept_tokens:
        # Every word of the concept's name appears in the request span.
        return 10.0 + len(concept_tokens), "every word of this concept's name was asked for"
    if overlap:
        return 3.0 + len(overlap) / len(concept_tokens), "part of this concept's name was asked for"

    # A stored VALUE naming the request span is strong evidence — this is how
    # "fire rated" reaches Pset_WallCommon.FireRating even though the words do
    # not appear in the field name.
    for value, _count in concept.values:
        value_tokens = {singularize(t) for t in identifier_tokens(value)}
        if value_tokens and value_tokens <= tokens:
            return 6.0, f"this concept stores the value {value!r}"
    return 0.0, ""


def _semantic_matches(
    item: LedgerItem,
    manifest: SemanticManifest,
    embedding_service_getter: Callable[[], Any],
    existing: list[tuple[float, ManifestConcept, str]],
) -> list[tuple[float, ManifestConcept, str]]:
    """Embedding supplements, used only where lexical matching came up short.

    Unlike Task 24, a supplement here can genuinely ADMIT a concept, because the
    binder is not restricted to this list — a wrong suggestion costs prompt space
    rather than correctness. Scores stay BELOW every lexical tier so a similarity
    hit can never displace a concept the user named outright.
    """
    try:
        service = embedding_service_getter()
        if service is None:
            return []
        already = {c.semantic_id for _, c, _ in existing}
        pool = [c for c in manifest.concepts.values() if c.semantic_id not in already and c.text]
        if not pool:
            return []
        import numpy as np

        query_vec = np.asarray(service.embed_texts([item.text])[0], dtype="float32")
        matrix = np.asarray(service.embed_texts([c.text for c in pool]), dtype="float32")
        query_vec /= np.linalg.norm(query_vec) or 1.0
        matrix /= np.clip(np.linalg.norm(matrix, axis=1, keepdims=True), 1e-9, None)
        sims = matrix @ query_vec
        order = np.argsort(-sims)[:3]
        return [
            (float(sims[i]), pool[i], f"semantically similar to {item.text!r}")
            for i in order
            if sims[i] > 0
        ]
    except Exception:  # noqa: BLE001 - recommendations degrade, never fail the query
        return []


def _coverage_notes(manifest: SemanticManifest) -> list[str]:
    """What this model genuinely cannot answer, stated once and plainly."""
    notes: list[str] = []
    for capability in manifest.missing_capabilities:
        reason = capability.get("reason")
        if reason and reason not in notes:
            notes.append(reason)
    return notes[:6]


def normalized_question(question: str) -> str:
    return normalize_text(question)
